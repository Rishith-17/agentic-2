"""Basic math evaluation skill."""

from __future__ import annotations

import re
from typing import Any

from app.skills.base import SkillBase


class CalculatorSkill(SkillBase):
    name = "calculator"
    description = "Perform arithmetic calculations directly and optionally open the system calculator."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["calculate"]},
                "expression": {"type": "string", "description": "The math expression (e.g. 20+30+40)"},
                "open_app": {"type": "boolean", "description": "Whether to also open the Windows Calculator app"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        if action != "calculate":
            return {"message": f"Unknown action {action}"}

        expr = parameters.get("expression") or ""
        # Basic character filter for safety
        clean_expr = re.sub(r"[^0-9\+\-\*\/\(\)\. ]", "", expr)
        
        try:
            # If no math but open_app is requested, just open it and return
            if not clean_expr.strip():
                if parameters.get("open_app", True):
                    self._open_system_calc()
                    return {"message": "System Calculator launched.", "open_app_requested": True}
                return {"message": "Please provide a math expression or ask to open the calculator."}

            # pylint: disable=eval-used
            result = eval(clean_expr, {"__builtins__": None}, {})
            
            summary = f"Calculation result: {result}"
            
            if parameters.get("open_app", False):
                self._open_system_calc()

            return {
                "message": summary,
                "result": result,
                "summary_text": f"The answer is {result}.",
                "open_app_requested": parameters.get("open_app", False)
            }
        except Exception as e:
            return {"message": f"Error calculating '{expr}': {e}"}

    def _open_system_calc(self):
        import os
        import platform
        import subprocess
        if platform.system() == "Windows":
            try:
                os.startfile("calc")
            except Exception:
                subprocess.Popen(["cmd", "/c", "start", "", "calc"], shell=True)
