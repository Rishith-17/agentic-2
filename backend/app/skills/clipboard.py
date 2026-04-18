"""Clipboard read, summarize, translate, forward to code assistant."""

from __future__ import annotations

from typing import Any

import pyperclip

from app.config import get_settings
from app.services import llm
from app.skills.base import SkillBase


class ClipboardSkill(SkillBase):
    name = "clipboard"
    description = "Read clipboard, summarize, translate, send to code assistant."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "summarize", "translate", "send_to_code_assistant"],
                },
                "target_lang": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        text = pyperclip.paste() or ""

        if action == "read":
            return {"message": "Clipboard", "content": text[:100000]}

        if action == "summarize":
            settings = get_settings()
            plan = await llm.plan_intent(
                f"Summarize briefly:\n\n{text[:8000]}",
                context=None,
                settings=settings,
            )
            reply = plan.get("reply_text") or str(plan)
            return {"summary_text": reply, "message": reply}

        if action == "translate":
            lang = parameters.get("target_lang") or "English"
            settings = get_settings()
            plan = await llm.plan_intent(
                f"Translate to {lang}:\n\n{text[:8000]}",
                settings=settings,
            )
            reply = plan.get("reply_text") or str(plan)
            return {"summary_text": reply, "message": reply}

        if action == "send_to_code_assistant":
            from app.skills.code_assistant import CodeAssistantSkill

            skill = CodeAssistantSkill()
            return await skill.execute("explain_clipboard", {"code": text})

        return {"message": f"Unknown action {action}"}
