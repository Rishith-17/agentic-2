"""Model selection logic for Jarvis Vision Mode."""

from __future__ import annotations

from app.vision.schemas import VisionMode


class VisionModelRouter:
    """Route quick scans to the fast VLM and harder reasoning to the deep VLM."""

    def __init__(self, fast_model: str, smart_model: str) -> None:
        self.fast_model = fast_model
        self.smart_model = smart_model

    def pick_model(
        self,
        *,
        mode: VisionMode,
        user_query: str = "",
        last_summary: str = "",
        attention: bool = False,
        force_smart: bool = False,
    ) -> str:
        if force_smart or attention:
            return self.smart_model

        text = f"{user_query} {last_summary}".lower()
        complex_terms = {
            "error",
            "traceback",
            "exception",
            "stack",
            "code",
            "debug",
            "why",
            "explain",
            "failed",
            "form",
            "review",
            "warning",
            "blocked",
            "can't",
            "cannot",
        }
        if user_query and any(term in text for term in complex_terms):
            return self.smart_model
        if mode == "active" and user_query:
            return self.smart_model
        return self.fast_model
