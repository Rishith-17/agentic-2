"""Morning briefing: weather, news, calendar, email."""

from __future__ import annotations

from typing import Any

from app.skills.base import SkillBase
from app.skills.calendar import CalendarSkill
from app.skills.gmail import GmailSkill
from app.skills.news import NewsSkill
from app.skills.weather import WeatherSkill


class BriefingSkill(SkillBase):
    name = "briefing"
    description = "Aggregated morning briefing."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["morning_briefing"]},
                "city": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        if action != "morning_briefing":
            return {"message": f"Unknown action {action}"}

        parts: list[str] = []

        async def _safe(label: str, coro) -> None:
            try:
                r = await coro
                parts.append(f"{label}: {r.get('message') or r.get('summary_text') or r}")
            except Exception as e:
                parts.append(f"{label}: (unavailable) {e}")

        await _safe("Weather", WeatherSkill().execute("current", {"city": parameters.get("city")}))
        await _safe("News", NewsSkill().execute("headlines", {}))
        await _safe("Calendar", CalendarSkill().execute("daily_agenda", {}))
        await _safe("Inbox", GmailSkill().execute("summarize_inbox", {}))

        msg = "\n\n".join(parts)
        return {"message": msg, "summary_text": msg}
