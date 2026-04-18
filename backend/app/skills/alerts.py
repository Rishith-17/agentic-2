"""Persisted alert rules and evaluation helpers."""

from __future__ import annotations

from typing import Any

import psutil

from app.dependencies import get_app_state
from app.skills.base import SkillBase


class AlertsSkill(SkillBase):
    name = "alerts"
    description = "Temperature and CPU alert rules stored in SQLite."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["set_temperature_alert", "set_cpu_alert", "list_alerts", "check_now"],
                },
                "threshold": {"type": "number"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        state = get_app_state()

        if action == "set_temperature_alert":
            t = float(parameters.get("threshold") or 35)
            await state.sqlite.add_alert_rule("temperature_c", t, {})
            return {"message": f"Will alert when temperature > {t}°C (check via /api/alerts/check)"}

        if action == "set_cpu_alert":
            t = float(parameters.get("threshold") or 90)
            await state.sqlite.add_alert_rule("cpu_percent", t, {})
            return {"message": f"Will alert when CPU > {t}%"}

        if action == "list_alerts":
            rules = await state.sqlite.list_active_alerts()
            return {"message": str(rules), "rules": rules}

        if action == "check_now":
            triggered = []
            cpu = psutil.cpu_percent(interval=0.3)
            for r in await state.sqlite.list_active_alerts():
                if r["rule_type"] == "cpu_percent" and r["threshold"] and cpu > r["threshold"]:
                    triggered.append(f"CPU {cpu:.1f}% > {r['threshold']}")
            return {"message": "; ".join(triggered) or "No CPU alerts", "cpu": cpu}

        return {"message": f"Unknown action {action}"}
