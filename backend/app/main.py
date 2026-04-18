"""FastAPI entrypoint for Jarvis AI Desktop Assistant."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import subprocess
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import psutil
from fastapi import Depends, FastAPI, File, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.core.pipeline import run_text_pipeline, run_voice_pipeline
from app.dependencies import AppState, get_app_state, init_app, verify_token
from app.services.wake_porcupine import WakeWordService
from app.vision.schemas import VisionActivateRequest, VisionOverlaySettings, VisionStartRequest
from preflight_check import run_preflight_sync

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── WhatsApp bridge helpers ────────────────────────────────────────────────────

BRIDGE_DIR = Path(__file__).parent.parent.parent / "integrations" / "jarvis-whatsapp-automation"
_bridge_monitor_task: asyncio.Task | None = None


def _launch_bridge() -> subprocess.Popen | None:
    """Start the Node WhatsApp bridge process and return the Popen handle."""
    try:
        proc = subprocess.Popen(
            ["node", "index.js"],
            cwd=str(BRIDGE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=(os.name == "nt"),
        )
        logger.info("WhatsApp bridge launched (PID: %s)", proc.pid)
        return proc
    except Exception as exc:
        logger.error("Failed to launch WhatsApp bridge: %s", exc)
        return None


async def _bridge_monitor(state: AppState) -> None:
    """Poll the bridge /health endpoint; restart the process if it dies."""
    node_url = state.settings.whatsapp_node_url.rstrip("/")
    health_url = f"{node_url}/health"
    restart_delay = 5  # seconds between restart attempts

    while True:
        await asyncio.sleep(15)  # check every 15 s
        proc = state.whatsapp_process

        # 1. Check if the OS process is still alive
        process_alive = proc is not None and proc.poll() is None

        if not process_alive:
            logger.warning("WhatsApp bridge process died — restarting in %ss", restart_delay)
            await asyncio.sleep(restart_delay)
            state.whatsapp_process = _launch_bridge()
            continue

        # 2. Check the HTTP health endpoint
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(health_url)
            if r.status_code != 200:
                logger.warning("WhatsApp bridge unhealthy (HTTP %s) — restarting", r.status_code)
                proc.terminate()
                await asyncio.sleep(restart_delay)
                state.whatsapp_process = _launch_bridge()
        except httpx.RequestError:
            # Bridge may still be starting up; not fatal yet
            logger.debug("WhatsApp bridge health check unreachable (may be starting)")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bridge_monitor_task

    # ── Dependency check (non-fatal — logs warnings for missing packages) ──
    from app.utils.dep_check import check_dependencies
    check_dependencies()

    st = await init_app()

    # Auto-start WhatsApp bridge
    st.whatsapp_process = _launch_bridge()

    # Start background monitor
    _bridge_monitor_task = asyncio.create_task(_bridge_monitor(st))

    # Start metrics broadcast loop for WebSocket clients
    _metrics_task = asyncio.create_task(_metrics_broadcast_loop())

    # Start Wake Word Listener if configured
    if st.wake:
        def on_wake() -> None:
            logger.info("WAKE WORD DETECTED")

        success = st.wake.start(on_wake)
        if success:
            logger.info("Porcupine wake word service started")
        else:
            logger.warning("Porcupine wake word service failed to start (check access key)")

    yield

    # ── Shutdown ──
    if _bridge_monitor_task:
        _bridge_monitor_task.cancel()
    _metrics_task.cancel()

    if st.whatsapp_process:
        logger.info("Stopping WhatsApp bridge...")
        st.whatsapp_process.terminate()
        try:
            st.whatsapp_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            st.whatsapp_process.kill()

    if st.wake:
        st.wake.stop()
    if st.vision:
        await st.vision.shutdown()


app = FastAPI(title="Jarvis AI Assistant", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── WebSocket connection manager ──────────────────────────────────────────────

class _WSManager:
    """Tracks active WebSocket connections and broadcasts JSON messages."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("WS client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections = [c for c in self._connections if c is not ws]
        logger.info("WS client disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = _WSManager()


def _collect_metrics() -> dict[str, Any]:
    cpu = psutil.cpu_percent(interval=None)
    vm = psutil.virtual_memory()
    net = psutil.net_io_counters()
    try:
        freq = psutil.cpu_freq()
        mhz = round(freq.current, 0) if freq else None
    except Exception:
        mhz = None
    return {
        "type": "metrics",
        "cpu_percent": round(cpu, 1),
        "ram_percent": round(vm.percent, 1),
        "ram_used_gb": round(vm.used / (1024 ** 3), 2),
        "ram_total_gb": round(vm.total / (1024 ** 3), 2),
        "net_sent_mb": round(net.bytes_sent / (1024 ** 2), 1),
        "net_recv_mb": round(net.bytes_recv / (1024 ** 2), 1),
        "cpu_freq_mhz": mhz,
        "logic_core_percent": round(cpu, 1),
    }


async def _metrics_broadcast_loop() -> None:
    """Background task: push metrics to all WS clients at ~1 Hz."""
    # Prime the psutil CPU counter (first call always returns 0.0)
    psutil.cpu_percent(interval=None)
    while True:
        await asyncio.sleep(1)
        if ws_manager._connections:
            await ws_manager.broadcast(_collect_metrics())


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """
    Real-time channel for the Electron HUD.

    Message types sent by server:
      {"type": "metrics", "cpu_percent": ..., "ram_percent": ..., ...}
      {"type": "token",   "text": "<partial LLM token>"}
      {"type": "reply",   "text": "<full reply>", "skill_type": "..."}
      {"type": "error",   "message": "..."}

    The client may send:
      {"type": "ping"}  → server replies {"type": "pong"}
    """
    # Token-based auth over WS: check query param ?token=<api_token>
    state = get_app_state()
    if state.settings.auth_enabled:
        token_param = ws.query_params.get("token", "")
        if token_param != state.api_token:
            await ws.close(code=4401)
            return

    await ws_manager.connect(ws)
    # Send an immediate metrics snapshot so the HUD doesn't wait 1 s
    await ws.send_json(_collect_metrics())
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception as exc:
        logger.warning("WS error: %s", exc)
        ws_manager.disconnect(ws)


@app.get("/health")
async def health(state: AppState = Depends(get_app_state)) -> dict[str, Any]:
    s = state.settings
    if s.nim_api_key:
        engine = f"NIM {s.nim_fast_model.split('/')[-1]}"
    else:
        engine = f"OLLAMA {s.ollama_model}"
    return {
        "status": "ok",
        "skills": state.registry.list_names(),
        "engine": engine,
        "version": "1.4",
    }


class WhatsAppIncomingBody(BaseModel):
    """Payload from jarvis-whatsapp-automation index.js (Baileys messages.upsert → Python)."""

    chat_id: str
    sender: str
    text: str
    is_group: bool = False


async def _handle_whatsapp_incoming(state: AppState, body: WhatsAppIncomingBody) -> None:
    """Filter groups, fetch history, propose a human-like reply, and store as pending."""
    # 1. No group reply
    if body.is_group:
        logger.info("Ignoring WhatsApp group message from %s", body.sender)
        return

    # 2. Log incoming message
    await state.sqlite.log_whatsapp_message(body.chat_id, body.sender, body.text, is_ai=False)

    # 3. Fetch History for Context
    history = await state.sqlite.get_whatsapp_history(body.chat_id, limit=5)
    hist_text = "\n".join([f"{'Assistant' if h['is_ai'] else 'User'}: {h['text']}" for h in history[:-1]]) # Exclude current

    # 4. Refine AI Pipeline with advanced context
    # Instruction for human-like tone, emotion, and summarization
    personality = (
        "PERSONALITY: You are a helpful, emotionally intelligent human assistant. "
        "Summarize the context if needed and reply naturally. "
        "Avoid robotic phrases. Matches the user's tone (formal/informal)."
    )
    ctx = f"{personality}\n\nChat History:\n{hist_text}\n\nCurrent Message from {body.sender}: {body.text}"
    
    try:
        out = await run_text_pipeline(state, body.text, context=ctx)
        reply = (out.get("reply") or "").strip()
        
        if not reply:
            return

        # 5. Store as Pending (Wait for user permission)
        reply_id = str(uuid.uuid4())
        state.pending_replies[reply_id] = {
            "id": reply_id,
            "chat_id": body.chat_id,
            "sender": body.sender,
            "incoming_text": body.text,
            "proposed_reply": reply,
            "type": "whatsapp",
            "created_at": datetime.utcnow().isoformat()
        }
        logger.info("Stored pending WhatsApp reply %s for %s", reply_id, body.sender)
    except Exception:
        logger.exception("WhatsApp incoming pipeline failed")


@app.post("/update_status")
async def whatsapp_update_status(body: dict[str, Any]) -> dict[str, str]:
    """Compatibility endpoint for jarvis-whatsapp-automation `index.js` (QR + connection events)."""
    st = body.get("status")
    state = get_app_state()

    if st == "scan_qr" and body.get("qr_code"):
        qr_data = body.get("qr_code", "")
        logger.info("WhatsApp bridge: awaiting QR scan (qr length=%s)", len(str(qr_data)))
        # Store QR for the frontend to display
        state.whatsapp_qr = str(qr_data)
    elif st == "connected":
        logger.info("WhatsApp bridge: connected as %s", body.get("user", "?"))
        state.whatsapp_qr = ""  # Clear QR once connected
    elif st == "disconnected":
        logger.warning("WhatsApp bridge: disconnected")
    else:
        logger.info("WhatsApp bridge status: %s", body)
    return {"status": "ok"}


@app.get("/api/whatsapp/qr")
async def get_whatsapp_qr(state: AppState = Depends(get_app_state)) -> dict[str, Any]:
    """Return the current WhatsApp QR code (as text) for the frontend to render."""
    qr = getattr(state, "whatsapp_qr", "")
    bridge_status = "unknown"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{state.settings.whatsapp_node_url.rstrip('/')}/health")
            if r.status_code == 200:
                bridge_status = r.json().get("status", "unknown")
    except Exception:
        bridge_status = "unreachable"

    return {
        "qr":     qr,
        "status": bridge_status,
        "has_qr": bool(qr),
    }


@app.get("/api/notifications")
async def list_notifications(
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> list[dict[str, Any]]:
    """Return all pending actions (e.g. WhatsApp replies) awaiting approval."""
    return list(state.pending_replies.values())


class ApproveBody(BaseModel):
    id: str


@app.post("/api/notifications/approve")
async def approve_notification(
    body: ApproveBody,
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    """Send the pending reply and clear it."""
    item = state.pending_replies.pop(body.id, None)
    if not item:
        return {"ok": False, "error": "Notification not found"}
    
    node = state.settings.whatsapp_node_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            await client.post(
                f"{node}/send", 
                json={"chat_id": item["chat_id"], "message": item["proposed_reply"]}
            )
        # Log outgoing message
        await state.sqlite.log_whatsapp_message(item["chat_id"], "JARVIS", item["proposed_reply"], is_ai=True)
        return {"ok": True}
    except Exception as e:
        logger.error("Failed to send approved WhatsApp reply: %s", e)
        return {"ok": False, "error": str(e)}


@app.post("/api/notifications/reject")
async def reject_notification(
    body: ApproveBody,
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    """Discard the pending reply."""
    state.pending_replies.pop(body.id, None)
    return {"ok": True}


@app.post("/incoming")
async def whatsapp_incoming(
    body: WhatsAppIncomingBody,
    state: AppState = Depends(get_app_state),
) -> dict[str, str]:
    """Inbound messages from Baileys bridge — same contract as upstream Flask `/incoming`."""
    asyncio.create_task(_handle_whatsapp_incoming(state, body))
    return {"status": "queued"}



# ── Food & Grocery Address Endpoints ──────────────────────────────────────────

@app.get("/api/food/addresses")
async def get_food_addresses(
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    addresses = await state.sqlite.get_addresses()
    return {"ok": True, "addresses": addresses}


class SetActiveAddressBody(BaseModel):
    label: str


@app.post("/api/food/addresses/active")
async def set_active_food_address(
    body: SetActiveAddressBody,
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    success = await state.sqlite.set_active_address(body.label)
    if success:
        logger.info("Active delivery address set to: %s", body.label)
        return {"ok": True}
    return {"ok": False, "error": "Address not found"}


class AddAddressBody(BaseModel):
    label: str
    city: str
    lat: float
    lng: float
    house_number: str = ""
    street_name: str = ""
    zipcode: str = ""
    landmark: str = ""
    set_active: bool = False


@app.post("/api/food/addresses")
async def add_food_address(
    body: AddAddressBody,
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    await state.sqlite.add_address(
        label=body.label,
        city=body.city,
        lat=body.lat,
        lng=body.lng,
        house_number=body.house_number,
        street_name=body.street_name,
        zipcode=body.zipcode,
        landmark=body.landmark,
        set_active=body.set_active
    )
    return {"ok": True}


@app.delete("/api/food/addresses/{label}")
async def delete_food_address(
    label: str,
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    await state.sqlite.delete_address(label)
    logger.info("Delivery address deleted: %s", label)
    return {"ok": True}


@app.get("/api/system/metrics")
async def system_metrics(_auth: None = Depends(verify_token)) -> dict[str, Any]:
    cpu = psutil.cpu_percent(interval=0.15)
    vm = psutil.virtual_memory()
    net = psutil.net_io_counters()
    try:
        freq = psutil.cpu_freq()
        mhz = round(freq.current, 0) if freq else None
    except Exception:
        mhz = None
    return {
        "cpu_percent": round(cpu, 1),
        "ram_percent": round(vm.percent, 1),
        "ram_used_gb": round(vm.used / (1024**3), 2),
        "ram_total_gb": round(vm.total / (1024**3), 2),
        "net_sent_mb": round(net.bytes_sent / (1024**2), 1),
        "net_recv_mb": round(net.bytes_recv / (1024**2), 1),
        "cpu_freq_mhz": mhz,
        "logic_core_percent": round(cpu, 1),
    }


@app.get("/api/system/health")
async def system_health(_auth: None = Depends(verify_token)) -> dict[str, Any]:
    """Automation + browser readiness health report for UI/ops."""
    report = run_preflight_sync(cache_ttl_s=60, force_refresh=False)
    return {
        "automation_ready": report.get("automation_ready", False),
        "browser_status": report.get("browser_status", "unknown"),
        "platforms": report.get("platforms", {}),
        "checks": report.get("checks", []),
        "critical_failures": report.get("critical_failures", []),
        "timestamp": report.get("timestamp"),
    }


@app.get("/api/system/logs")
async def system_logs(
    lines: int = Query(120, ge=20, le=1000),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    """
    Aggregate recent MCP log tails + current preflight failures.
    """
    repo_root = Path(__file__).resolve().parents[2]
    log_paths = [
        repo_root / "mcp_servers" / "data" / "logs" / "swiggy_server.log",
        repo_root / "mcp_servers" / "data" / "logs" / "zepto_server.log",
        repo_root / "mcp_servers" / "data" / "logs" / "zomato_server.log",
        repo_root / "mcp_servers" / "data" / "logs" / "blinkit_server.log",
    ]

    logs: dict[str, Any] = {}
    for path in log_paths:
        name = path.name
        if not path.exists():
            logs[name] = {"exists": False, "lines": []}
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                tail = list(deque(f, maxlen=lines))
            logs[name] = {"exists": True, "lines": [ln.rstrip("\n") for ln in tail]}
        except Exception as exc:
            logs[name] = {"exists": True, "error": str(exc), "lines": []}

    preflight = run_preflight_sync(cache_ttl_s=10, force_refresh=False)
    return {
        "ok": True,
        "logs": logs,
        "preflight_critical_failures": preflight.get("critical_failures", []),
    }


class ChatBody(BaseModel):
    message: str = Field(..., min_length=1)
    context: str | None = None
    user_confirmed: bool = False
    session_id: str = "default"


class AgentExecuteBody(BaseModel):
    task: str = Field(..., min_length=1)
    session_id: str = "default"
    user_confirmed: bool = False
    context: str | None = None


@app.post("/api/chat")
async def chat(
    body: ChatBody,
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    out = await run_text_pipeline(
        state,
        body.message,
        context=body.context,
        user_confirmed=body.user_confirmed,
        session_id=body.session_id,
    )
    tts = out.pop("tts_audio", None)
    if tts:
        out["tts_audio_base64"] = base64.b64encode(tts).decode("ascii") if tts else None
    return out


@app.post("/api/agent/execute")
async def agent_execute(
    body: AgentExecuteBody,
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    """
    Structured execution endpoint for dashboard task orchestration.
    """
    out = await run_text_pipeline(
        state,
        body.task,
        context=body.context,
        user_confirmed=body.user_confirmed,
        session_id=body.session_id,
    )

    plan = out.get("plan") or {}
    skill_result = out.get("skill_result") or {}
    steps: list[dict[str, Any]] = [
        {
            "phase": "planning",
            "status": "ok",
            "skill": plan.get("skill"),
            "action": plan.get("action"),
            "needs_skill": plan.get("needs_skill"),
        }
    ]
    if plan.get("needs_skill"):
        steps.append(
            {
                "phase": "skill_execution",
                "status": "ok" if skill_result.get("ok", True) else "error",
                "skill": plan.get("skill"),
                "action": plan.get("action"),
                "needs_confirmation": skill_result.get("needs_confirmation", False),
                "error": skill_result.get("error"),
            }
        )

    return {
        "ok": True,
        "task": body.task,
        "session_id": body.session_id,
        "steps": steps,
        "result": out,
    }


class ExecuteBody(BaseModel):
    skill: str
    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    user_confirmed: bool = False


@app.post("/api/execute")
async def execute_direct(
    body: ExecuteBody,
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    return await state.router.route(
        body.skill,
        body.action,
        body.parameters,
        user_confirmed=body.user_confirmed,
    )


@app.get("/api/skills")
async def list_skills(
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    return {"skills": state.registry.all_meta()}


@app.post("/api/voice")
async def voice(
    file: UploadFile = File(...),
    user_confirmed: bool = Query(False),
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    data = await file.read()
    out = await run_voice_pipeline(state, data, user_confirmed=user_confirmed)
    tts = out.pop("tts_audio", None)
    if tts:
        out["tts_audio_base64"] = base64.b64encode(tts).decode("ascii") if tts else None
    return out


@app.get("/api/alerts/check")
async def check_alerts(
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    from app.skills.alerts import AlertsSkill

    skill = AlertsSkill()
    return await skill.execute("check_now", {})


@app.post("/api/wake/start")
async def wake_start(
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    s = state.settings
    if state.wake:
        return {"started": True, "message": "Wake listener already running"}
    svc = WakeWordService(s.porcupine_access_key, s.porcupine_keyword_path)

    def on_wake() -> None:
        logger.info("Wake word detected")

    if not svc.start(on_wake):
        return {"started": False, "message": "Porcupine not configured or failed to start"}
    state.wake = svc
    return {"started": True, "message": "Listening for wake word"}


@app.post("/api/wake/stop")
async def wake_stop(
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    if state.wake:
        state.wake.stop()
        state.wake = None
    return {"stopped": True}


@app.get("/api/vision/status")
async def vision_status(
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    if not state.vision:
        return {"enabled": False, "last_error": "Vision controller unavailable"}
    return state.vision.snapshot()


@app.post("/api/vision/start")
async def vision_start(
    body: VisionStartRequest,
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    if not state.vision:
        return {"enabled": False, "last_error": "Vision controller unavailable"}
    return await state.vision.start(mode=body.mode, user_query=body.user_query, reason=body.reason)


@app.post("/api/vision/stop")
async def vision_stop(
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    if not state.vision:
        return {"enabled": False, "last_error": "Vision controller unavailable"}
    return await state.vision.stop()


@app.post("/api/vision/analyze")
async def vision_analyze(
    body: VisionStartRequest,
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    if not state.vision:
        return {"enabled": False, "last_error": "Vision controller unavailable"}
    return await state.vision.analyze_once(user_query=body.user_query, mode=body.mode)


@app.post("/api/vision/voice/start")
async def vision_voice_start(
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    if not state.vision:
        return {"enabled": False, "last_error": "Vision controller unavailable"}
    return await state.vision.start_voice_listener()


@app.post("/api/vision/voice/stop")
async def vision_voice_stop(
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    if not state.vision:
        return {"enabled": False, "last_error": "Vision controller unavailable"}
    return await state.vision.stop_voice_listener()


@app.post("/api/vision/voice/activate")
async def vision_voice_activate(
    body: VisionActivateRequest,
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    if not state.vision:
        return {"enabled": False, "last_error": "Vision controller unavailable"}
    return await state.vision.activate_from_phrase(body.phrase)


@app.post("/api/vision/overlay")
async def vision_overlay_settings(
    body: VisionOverlaySettings,
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    if not state.vision:
        return {"enabled": False, "last_error": "Vision controller unavailable"}
    return await state.vision.set_click_through(body.click_through)


def create_app() -> FastAPI:
    return app


# ── Location API ──────────────────────────────────────────────────────────────

class LocationBody(BaseModel):
    city: str = ""
    lat: float | None = None
    lng: float | None = None


@app.post("/api/location")
async def set_location(
    body: LocationBody,
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    """Store user location (from browser geolocation or manual city entry)."""
    state.user_location = {
        "city": body.city,
        "lat":  body.lat,
        "lng":  body.lng,
    }
    if body.city or (body.lat is not None and body.lng is not None):
        label = "Live Detect"
        await state.sqlite.add_address(
            label=label,
            city=body.city or "Current Location",
            lat=body.lat or 0.0,
            lng=body.lng or 0.0,
            landmark="Auto-detected from Jarvis desktop",
            set_active=True,
        )
    # Also update MCP server env vars so Swiggy/Zomato use the right coords
    if body.lat and body.lng:
        os.environ["SWIGGY_LAT"] = str(body.lat)
        os.environ["SWIGGY_LNG"] = str(body.lng)
        os.environ["ZOMATO_LAT"] = str(body.lat)
        os.environ["ZOMATO_LNG"] = str(body.lng)
    logger.info("Location set: %s (%.4f, %.4f)", body.city, body.lat or 0, body.lng or 0)
    return {"ok": True, "location": state.user_location}


@app.get("/api/location")
async def get_location(
    state: AppState = Depends(get_app_state),
    _auth: None = Depends(verify_token),
) -> dict[str, Any]:
    """Return the currently stored user location."""
    return {"location": state.user_location}

