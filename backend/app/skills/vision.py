"""Vision Skill for on-demand screen analysis."""

from __future__ import annotations

import logging
from typing import Any

from app.skills.base import SkillBase
from app.dependencies import get_app_state

logger = logging.getLogger(__name__)

class VisionSkill(SkillBase):
    name = "vision"
    description = "Take a snapshot of the user's screen and analyze it."
    keywords = ["look", "screen", "analyze", "vision", "screenshot", "what is this", "snapshot", "what am i looking at"]
    priority = 5

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["analyze_screen"]},
                "query": {"type": "string", "description": "Specific question about the screen. Can be empty."}
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        state = get_app_state()
        vision_ctrl = getattr(state, "vision", None)
        
        if not vision_ctrl:
            return {"error": "Vision controller not available."}
        
        query = parameters.get("query", "")
        if action == "analyze_screen":
            try:
                # Trigger a forced analysis. This activates the vision mode and pushes it to attention.
                await vision_ctrl.analyze_once(user_query=query, mode="active")
                latest = vision_ctrl._state.latest
                if not latest or not latest.summary:
                    return {"result": "Looked at your screen, but an error occurred during analysis."}

                return {
                    "result": "Analyzed your screen successfully.",
                    "skill_type": "vision",
                    "data": latest.model_dump()
                }
            except Exception as e:
                logger.exception("Failed to analyze screen via skill")
                return {"error": f"Vision analysis failed: {e}"}
            
        return {"error": f"Unknown vision action: {action}"}
