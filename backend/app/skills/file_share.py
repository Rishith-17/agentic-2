"""File sharing via dropkg.vercel.app."""

from __future__ import annotations

import logging
import platform
import subprocess
import webbrowser
from typing import Any

from app.skills.base import SkillBase

logger = logging.getLogger(__name__)


class FileShareSkill(SkillBase):
    name = "file_share"
    description = "Share files via dropkg.vercel.app."

    BASE_URL = "https://dropkg.vercel.app"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["share_file", "open_portal"],
                },
                "file_path": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        if action in ("share_file", "open_portal"):
            try:
                if platform.system() == "Windows":
                    subprocess.Popen(["explorer.exe", self.BASE_URL])
                else:
                    webbrowser.open(self.BASE_URL)
                
                msg = f"📤 Opening file sharing portal.\n🔗 URL: {self.BASE_URL}\nUpload your file and share the link."
                return {"message": msg, "summary_text": msg, "skill_type": "file_share"}
            except Exception as e:
                logger.error("File share launch failed: %s", e)
                return {"message": f"Failed to open file sharing: {e}", "summary_text": str(e)}

        return {"message": f"Unknown action: {action}", "summary_text": f"Unknown action: {action}"}
