"""WhatsApp via jarvis-whatsapp-automation Node bridge (Baileys) — POST /send."""

from __future__ import annotations

import base64
import io
import logging
import webbrowser
from typing import Any

import httpx

from app.config import get_settings
from app.skills.base import SkillBase

logger = logging.getLogger(__name__)


def _jid_from_contact(contact: str) -> str | None:
    raw = (contact or "").strip()
    if "@" in raw:
        return raw if raw.endswith("@s.whatsapp.net") or raw.endswith("@g.us") else None
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) < 8:
        return None
    return f"{digits}@s.whatsapp.net"


async def _check_bridge_status() -> dict[str, Any]:
    """Check if the WhatsApp bridge is running and connected."""
    base = get_settings().whatsapp_node_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base}/health")
            if r.status_code == 200:
                return r.json()
            return {"status": "disconnected"}
    except Exception:
        return {"status": "unreachable"}


def _open_qr_in_browser(qr_url: str) -> bool:
    """Open QR code URL in the default browser."""
    try:
        return webbrowser.open(qr_url)
    except Exception as exc:
        logger.warning(f"Failed to open QR URL in browser: {exc}")
        return False


class WhatsAppSkill(SkillBase):
    name = "whatsapp"
    description = (
        "Send WhatsApp messages through the Baileys bridge "
        "(integrations/jarvis-whatsapp-automation — node index.js)."
    )
    priority = 8
    keywords = ["whatsapp", "send message", "message to", "text to", "wa message"]

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["send_message", "show_qr"]},
                "contact": {
                    "type": "string",
                    "description": "Phone with country code (digits) or full WhatsApp JID",
                },
                "message": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        # Handle show_qr action
        if action == "show_qr":
            base = get_settings().whatsapp_node_url.rstrip("/")
            qr_url = f"{base}/qr"
            
            # Automatically open QR code in browser
            browser_opened = _open_qr_in_browser(qr_url)
            
            if browser_opened:
                return {
                    "message": (
                        f"📱 **WhatsApp QR Code Opened in Browser**\n\n"
                        f"I've opened the QR code page in your browser. Follow these steps:\n\n"
                        f"1. Open WhatsApp on your phone\n"
                        f"2. Go to **Settings → Linked Devices**\n"
                        f"3. Tap **Link a Device**\n"
                        f"4. Scan the QR code displayed in your browser\n\n"
                        f"If the browser didn't open, visit: {qr_url}"
                    ),
                    "skill_type": "whatsapp",
                    "data": {"qr_url": qr_url, "needs_qr": True, "browser_opened": True},
                }
            else:
                return {
                    "message": (
                        f"📱 **Scan QR Code to Link WhatsApp**\n\n"
                        f"Open this URL in your browser: {qr_url}\n\n"
                        f"Then follow these steps:\n"
                        f"1. Open WhatsApp on your phone\n"
                        f"2. Go to **Settings → Linked Devices**\n"
                        f"3. Tap **Link a Device**\n"
                        f"4. Scan the QR code"
                    ),
                    "skill_type": "whatsapp",
                    "data": {"qr_url": qr_url, "needs_qr": True, "browser_opened": False},
                }

        if action != "send_message":
            return {"message": f"Unknown action {action}"}

        contact = (parameters.get("contact") or "").strip()
        message = (parameters.get("message") or "").strip()
        if not contact or not message:
            return {"message": "contact and message required"}

        jid = _jid_from_contact(contact)
        if not jid:
            return {
                "message": (
                    f"I cannot find a phone number for '{contact}'. "
                    "Please provide the exact phone number with the country code (e.g., 919876543210)."
                )
            }

        # Check bridge status first
        base = get_settings().whatsapp_node_url.rstrip("/")
        status = await _check_bridge_status()
        bridge_status = status.get("status", "unknown")
        
        if bridge_status == "unreachable":
            qr_url = f"{base}/qr"
            return {
                "message": (
                    f"⚠️ **WhatsApp Bridge Not Running**\n\n"
                    f"The WhatsApp bridge service is not running. Start it with:\n\n"
                    f"```bash\n"
                    f"cd integrations/jarvis-whatsapp-automation\n"
                    f"node index.js\n"
                    f"```\n\n"
                    f"After starting, the QR code will be available at: {qr_url}\n"
                    f"Or say **'show whatsapp qr'** to open it automatically."
                ),
                "skill_type": "whatsapp",
                "data": {"bridge_status": "unreachable", "needs_qr": True, "qr_url": qr_url},
                "success": False,
            }
        
        if bridge_status not in ("connected",):
            qr_url = f"{base}/qr"
            
            # Automatically open QR code in browser for user convenience
            browser_opened = _open_qr_in_browser(qr_url)
            
            if browser_opened:
                return {
                    "message": (
                        f"📱 **WhatsApp Not Connected - QR Code Opened**\n\n"
                        f"I've opened the QR code page in your browser. Follow these steps:\n\n"
                        f"1. Open WhatsApp on your phone\n"
                        f"2. Go to **Settings → Linked Devices**\n"
                        f"3. Tap **Link a Device**\n"
                        f"4. Scan the QR code displayed in your browser\n\n"
                        f"Once scanned, try sending your message again.\n\n"
                        f"If the browser didn't open, visit: {qr_url}"
                    ),
                    "skill_type": "whatsapp",
                    "data": {"bridge_status": bridge_status, "needs_qr": True, "qr_url": qr_url, "browser_opened": True},
                    "success": False,
                }
            else:
                return {
                    "message": (
                        f"📱 **WhatsApp Not Connected**\n\n"
                        f"Please scan the QR code to link your WhatsApp account.\n\n"
                        f"**Open this URL in your browser:** {qr_url}\n\n"
                        f"Then follow these steps:\n"
                        f"1. Open WhatsApp on your phone\n"
                        f"2. Go to **Settings → Linked Devices**\n"
                        f"3. Tap **Link a Device**\n"
                        f"4. Scan the QR code\n\n"
                        f"Once scanned, try sending your message again."
                    ),
                    "skill_type": "whatsapp",
                    "data": {"bridge_status": bridge_status, "needs_qr": True, "qr_url": qr_url, "browser_opened": False},
                    "success": False,
                }

        url = f"{base}/send"
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                r = await client.post(url, json={"chat_id": jid, "message": message})
        except httpx.RequestError as e:
            return {
                "message": (
                    f"WhatsApp bridge is not running. Start it with:\n"
                    f"```\ncd integrations/jarvis-whatsapp-automation && node index.js\n```\n"
                    f"Error: {e}"
                ),
                "success": False,
            }

        if r.status_code == 503:
            qr_url = f"{base}/qr"
            return {
                "message": f"WhatsApp bridge is not connected. Scan QR code at:\n{qr_url}",
                "data": {"needs_qr": True, "qr_url": qr_url},
                "success": False,
            }
        if r.status_code >= 400:
            return {"message": f"Bridge error HTTP {r.status_code}: {r.text[:200]}", "success": False}

        msg = f"✅ WhatsApp message sent to {contact}."
        return {"message": msg, "summary_text": msg, "skill_type": "whatsapp"}
