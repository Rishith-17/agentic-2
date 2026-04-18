"""Runtime controller for Jarvis Vision Mode."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone

from app.vision.capture import CapturedFrame, ScreenCaptureService
from app.vision.nim_client import VisionNimClient
from app.vision.router import VisionModelRouter
from app.vision.schemas import VisionHintPayload, VisionState
from app.vision.voice import VoiceTriggerService

logger = logging.getLogger(__name__)


class VisionController:
    """Coordinates capture, model routing, throttling, and latest hint state."""

    def __init__(self, state) -> None:
        self._app_state = state
        self._capture = ScreenCaptureService()
        self._router = VisionModelRouter(
            fast_model=state.settings.vision_fast_model,
            smart_model=state.settings.vision_smart_model,
        )
        self._nim = VisionNimClient(
            http_client=state.client,
            base_url=state.settings.nim_base_url,
            api_key=state.settings.nim_api_key,
        )
        self._voice = VoiceTriggerService(state.settings)
        self._state = VisionState()
        self._frame_queue: asyncio.Queue[tuple[CapturedFrame, str]] = asyncio.Queue(maxsize=1)
        self._producer_task: asyncio.Task | None = None
        self._consumer_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._previous_signature: list[int] = []

    def snapshot(self) -> dict:
        return self._state.model_dump()

    async def start(self, *, mode: str = "passive", user_query: str = "", reason: str = "") -> dict:
        async with self._lock:
            self._state.enabled = True
            self._state.mode = mode
            self._state.active_reason = reason or user_query
            self._state.last_error = ""
            self._state.attention = mode == "active"
            if self._producer_task is None or self._producer_task.done():
                self._producer_task = asyncio.create_task(self._capture_loop())
            if self._consumer_task is None or self._consumer_task.done():
                self._consumer_task = asyncio.create_task(self._process_loop())
        if user_query or mode == "active":
            await self.analyze_once(user_query=user_query, mode=mode)
        return self.snapshot()

    async def stop(self) -> dict:
        async with self._lock:
            self._state.enabled = False
            self._state.processing = False
            self._state.mode = "passive"
            self._state.active_reason = ""
            self._state.attention = False
        return self.snapshot()

    async def shutdown(self) -> None:
        self._voice.stop()
        for task in (self._producer_task, self._consumer_task):
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def analyze_once(self, *, user_query: str = "", mode: str | None = None) -> dict:
        frame = await asyncio.to_thread(self._capture.capture)
        self._state.last_frame_at = frame.captured_at
        hint = await self._run_analysis(frame, user_query=user_query, mode=mode or self._state.mode, force_smart=(mode == "active" and bool(user_query)))
        self._state.latest = hint
        return self.snapshot()

    async def set_click_through(self, value: bool) -> dict:
        self._state.click_through = value
        return self.snapshot()

    async def start_voice_listener(self) -> dict:
        loop = asyncio.get_running_loop()

        def on_phrase(phrase: str) -> None:
            asyncio.run_coroutine_threadsafe(self._handle_voice_phrase(phrase), loop)

        self._voice.start(on_phrase)
        self._state.voice_enabled = True
        return self.snapshot()

    async def stop_voice_listener(self) -> dict:
        self._voice.stop()
        self._state.voice_enabled = False
        return self.snapshot()

    async def activate_from_phrase(self, phrase: str) -> dict:
        return await self._handle_voice_phrase(phrase)

    async def _handle_voice_phrase(self, phrase: str) -> dict:
        lowered = phrase.lower().strip()
        if "stop watching" in lowered:
            return await self.stop()
        return await self.start(mode="active", user_query=phrase, reason=phrase)

    async def _capture_loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds())
            if not self._state.enabled:
                continue
            try:
                frame = await asyncio.to_thread(self._capture.capture)
                self._state.last_frame_at = frame.captured_at
                diff_score = self._compute_diff_score(frame)
                self._state.last_diff_score = diff_score
                if self._should_skip_frame(diff_score):
                    self._state.skipped_frames += 1
                    continue
                if self._frame_queue.full():
                    with suppress(asyncio.QueueEmpty):
                        self._frame_queue.get_nowait()
                self._frame_queue.put_nowait((frame, self._state.active_reason))
            except Exception as exc:
                logger.exception("Vision capture loop failed")
                self._state.last_error = str(exc)

    async def _process_loop(self) -> None:
        while True:
            frame, user_query = await self._frame_queue.get()
            if not self._state.enabled:
                continue
            try:
                self._state.processing = True
                hint = await self._run_analysis(frame, user_query=user_query, mode=self._state.mode)
                self._state.latest = hint
            except Exception as exc:
                logger.exception("Vision analysis failed")
                self._state.last_error = str(exc)
                self._state.latest = VisionHintPayload(
                    summary="Jarvis hit a vision processing error.",
                    urgency="medium",
                    priority="critical",
                    action_required=True,
                    suggestions=[],
                    mode=self._state.mode,
                    model="",
                    follow_up="Try again in a moment.",
                )
            finally:
                self._state.processing = False

    async def _run_analysis(self, frame: CapturedFrame, *, user_query: str, mode: str, force_smart: bool = False) -> VisionHintPayload:
        model = self._router.pick_model(
            mode=mode,
            user_query=user_query,
            last_summary=self._state.latest.summary,
            attention=self._state.attention,
            force_smart=force_smart,
        )
        hint = await self._nim.analyze_screen(
            model=model,
            base64_image=frame.base64_image,
            mode=mode,
            user_query=user_query,
        )
        if hint.priority == "critical" and model != self._app_state.settings.vision_smart_model:
            self._state.mode = "active"
            self._state.attention = True
            self._state.active_reason = user_query or hint.summary
            hint = await self._nim.analyze_screen(
                model=self._app_state.settings.vision_smart_model,
                base64_image=frame.base64_image,
                mode="active",
                user_query=user_query or hint.summary,
            )

        hint = self._post_process_hint(hint)
        hint.created_at = datetime.now(timezone.utc).isoformat()
        return hint

    def _post_process_hint(self, hint: VisionHintPayload) -> VisionHintPayload:
        if hint.no_action or hint.summary == "NO_ACTION":
            hint.mode = self._state.mode
            if self._state.mode == "active" and self._state.active_reason:
                self._state.attention = False
            return self._suppressed_payload()

        if hint.priority == "critical":
            self._state.mode = "active"
            self._state.attention = True
            hint.mode = "active"
            hint.action_required = True
        elif hint.priority == "actionable":
            self._state.attention = False
            hint.action_required = True
        else:
            self._state.attention = False

        if not hint.suggestions and hint.action_required:
            hint.suggestions = []
        return hint

    def _suppressed_payload(self) -> VisionHintPayload:
        latest = self._state.latest
        if latest and not latest.no_action and latest.priority != "critical":
            latest.no_action = True
            return latest
        return VisionHintPayload(summary="NO_ACTION", no_action=True, priority="passive", mode=self._state.mode)

    def _compute_diff_score(self, frame: CapturedFrame) -> float:
        current = frame.diff_signature
        if not current:
            return 1.0
        if not self._previous_signature:
            self._previous_signature = current
            return 1.0
        length = min(len(current), len(self._previous_signature))
        if length == 0:
            return 1.0
        total = sum(abs(current[idx] - self._previous_signature[idx]) for idx in range(length))
        score = total / (length * 255.0)
        self._previous_signature = current
        return round(score, 5)

    def _should_skip_frame(self, diff_score: float) -> bool:
        if self._state.mode == "active":
            return False
        if self._state.attention:
            return False
        if self._state.active_reason:
            return False
        threshold = getattr(self._app_state.settings, "vision_diff_threshold", 0.018)
        return diff_score < float(threshold)

    def _interval_seconds(self) -> float:
        return float(self._app_state.settings.vision_active_interval if self._state.mode == "active" else self._app_state.settings.vision_passive_interval)
