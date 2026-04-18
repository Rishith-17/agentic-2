"""User preferences and semantic recall."""

from __future__ import annotations

import logging
from typing import Any

from app.dependencies import get_app_state
from app.skills.base import SkillBase

logger = logging.getLogger(__name__)


class MemorySkill(SkillBase):
    name = "memory_skill"
    description = "Store preferences, query vector memory, recall history."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "remember",
                        "recall_saved_details",
                        "search_memories",
                        "forget_memories",
                        "recall_history",
                    ],
                },
                "key": {"type": "string"},
                "value": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        state = get_app_state()

        if action == "remember":
            key = parameters.get("key") or "info"
            val = parameters.get("value") or ""
            if not val:
                return {"message": "No value provided to remember.", "summary_text": "No value provided to remember."}
            
            await state.sqlite.set_preference(key, val)
            try:
                state.chroma.add_text(f"Memory: {key} is {val}", metadata={"type": "preference", "key": key})
            except Exception:
                pass
            
            msg = f"I have remembered that {key} is {val}."
            return {"message": msg, "summary_text": msg}

        if action == "recall_saved_details":
            key = parameters.get("key")
            if key:
                val = await state.sqlite.get_preference(key)
                if val:
                    msg = f"I remember that {key} is {val}."
                    return {"message": msg, "summary_text": msg}
                msg = f"I don't have anything saved for '{key}'."
                return {"message": msg, "summary_text": msg}
            
            prefs = await state.sqlite.get_all_preferences()
            if not prefs:
                msg = "I don't have any specific details saved yet."
                return {"message": msg, "summary_text": msg}
            msg = "Here are all the details I've saved:\n" + "\n".join([f"- {k}: {v}" for k, v in prefs.items()])
            return {"message": msg, "summary_text": msg}

        if action == "search_memories":
            q = parameters.get("query") or parameters.get("key") or ""
            if not q:
                msg = "No query provided for memory search."
                return {"message": msg, "summary_text": msg}
            
            hits = state.chroma.query(q, n=5)
            if not hits:
                msg = f"I couldn't find any memories related to '{q}'."
                return {"message": msg, "summary_text": msg, "skill_type": "memory"}
            
            lines = [h["text"] for h in hits]
            msg = f"Searching memories for '{q}':\n" + "\n---\n".join(lines)
            return {"message": msg, "summary_text": msg, "hits": hits, "skill_type": "memory"}

        if action == "forget_memories":
            key = parameters.get("key")
            if not key:
                msg = "Please specify what I should forget (the key)."
                return {"message": msg, "summary_text": msg, "skill_type": "memory"}
            
            success = await state.sqlite.delete_preference(key)
            msg = f"I have forgotten everything I knew about {key}." if success else f"I didn't have anything saved for {key}."
            return {"message": msg, "summary_text": msg, "skill_type": "memory"}

        if action == "recall_history":
            limit = int(parameters.get("limit") or 30)
            history = await state.sqlite.get_command_history(limit=limit)
            if not history:
                msg = "No past interactions found yet."
                return {"message": msg, "summary_text": msg, "skill_type": "memory"}
            
            lines = []
            for entry in history:
                ts = entry.get("created_at", "?")
                txt = entry.get("text", "")
                skill = entry.get("skill") or "chat"
                lines.append(f"[{ts}] ({skill}) {txt}")
            
            msg = f"Here are your last {len(lines)} interactions:\n" + "\n".join(lines)
            return {"message": msg, "summary_text": msg, "skill_type": "memory"}

        msg = f"Unknown action {action}"
        return {"message": msg, "summary_text": msg, "skill_type": "memory"}
