"""NVIDIA NIM client for multimodal screen understanding."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.vision.prompts import VISION_SYSTEM_PROMPT, build_user_prompt
from app.vision.schemas import VisionHintPayload, VisionSuggestion

logger = logging.getLogger(__name__)


class VisionNimClient:
    """Calls NVIDIA NIM vision models with the current screen frame."""

    def __init__(self, *, http_client: httpx.AsyncClient, base_url: str, api_key: str) -> None:
        self._client = http_client
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def analyze_screen(
        self,
        *,
        model: str,
        base64_image: str,
        mode: str,
        user_query: str = "",
    ) -> VisionHintPayload:
        if not self._api_key:
            return VisionHintPayload(
                summary="Vision Mode needs an NVIDIA NIM API key before it can analyze the screen.",
                urgency="medium",
                priority="actionable",
                action_required=True,
                suggestions=[
                    VisionSuggestion(
                        title="Set NIM key",
                        text="Add NIM_API_KEY to backend/.env, then restart Vision Mode.",
                        anchor="top-right",
                        kind="warning",
                    )
                ],
                mode=mode,
                model=model,
                follow_up="Once configured, Jarvis will start live screen guidance.",
            )

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": build_user_prompt(mode, user_query)},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}},
                    ],
                },
            ],
            "temperature": 0.2,
            "top_p": 0.7,
            "max_tokens": 900,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        response = await self._client.post(f"{self._base_url}/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return self._parse_payload(content, mode=mode, model=model)

    def _parse_payload(self, content: str, *, mode: str, model: str) -> VisionHintPayload:
        raw = self._extract_json(content)
        try:
            parsed = VisionHintPayload.model_validate({**raw, "mode": raw.get("mode") or mode, "model": model})
        except Exception:
            logger.warning("Vision response was not valid JSON; falling back to summary text")
            parsed = VisionHintPayload(
                summary=content.strip()[:240] or "Jarvis analyzed the screen.",
                mode=mode,
                model=model,
                priority="passive",
                suggestions=[
                    VisionSuggestion(
                        title="Screen insight",
                        text=self._shorten(content.strip() or "Jarvis completed a screen scan."),
                        anchor="right",
                        kind="info",
                    )
                ],
            )

        self._normalize(parsed)

        if parsed.no_action:
            parsed.summary = "NO_ACTION"
            parsed.follow_up = ""
            parsed.suggestions = []
            parsed.highlights = []
            parsed.action_required = False
            parsed.priority = "passive"
            parsed.urgency = "low"
            return parsed

        if not parsed.suggestions and parsed.action_required:
            parsed.suggestions = [
                VisionSuggestion(
                    title="Screen insight",
                    text=self._shorten(parsed.summary),
                    anchor="right",
                    kind="info",
                )
            ]
        return parsed

    @staticmethod
    def _extract_json(content: str) -> dict[str, Any]:
        match = re.search(r"(\{.*\})", content, re.DOTALL)
        text = match.group(1) if match else content.strip().replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(text)
        except Exception:
            return {"summary": content.strip()}

    def _normalize(self, payload: VisionHintPayload) -> None:
        payload.summary = self._shorten(payload.summary)
        payload.follow_up = self._shorten(payload.follow_up, fallback="")
        payload.priority = (payload.priority or "passive").lower()  # type: ignore[assignment]

        if payload.summary.strip().upper() == "NO_ACTION":
            payload.no_action = True

        if payload.priority == "critical":
            payload.action_required = True
            payload.urgency = "high"
        elif payload.priority == "actionable" and payload.urgency == "low":
            payload.urgency = "medium"

        trimmed: list[VisionSuggestion] = []
        for suggestion in payload.suggestions[:2]:
            suggestion.title = self._shorten(suggestion.title, max_length=42, fallback="Action")
            suggestion.text = self._shorten(suggestion.text)
            trimmed.append(suggestion)
        payload.suggestions = trimmed

        for highlight in payload.highlights:
            if payload.priority in {"critical", "actionable"}:
                highlight.pulse = True

    @staticmethod
    def _shorten(text: str, *, max_length: int = 110, fallback: str = "Screen insight") -> str:
        clean = " ".join((text or "").split()).strip()
        if not clean:
            return fallback
        if len(clean) <= max_length:
            return clean
        return clean[: max_length - 1].rstrip() + "…"
