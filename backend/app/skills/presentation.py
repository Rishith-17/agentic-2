"""Presentation and Document generation using deep-links to lovelace / API."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

import httpx

from app.skills.base import SkillBase

logger = logging.getLogger(__name__)

# Fallback API Key for reports
DEFAULT_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtmYWN1c2FweXl2cmpzZXdzaWF6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjYxNDQyNDQsImV4cCI6MjA4MTcyMDI0NH0.QrvXBvj6eDCjoN1mrVohZkripy4G57R1W394rpcXPy8"

class PresentationSkill(SkillBase):
    name = "presentation"
    description = "Generate PowerPoint presentations and academic reports."
    priority = 5
    keywords = ["ppt", "presentation", "slide", "slides", "academic report", "project report", "documentation"]

    API_URL = "https://kfacusapyyvrjsewsiaz.supabase.co/functions/v1/jarvis-api"
    WEB_APP_URL = "https://glide-presentations.lovable.app"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["generate_ppt", "generate_report"],
                },
                "topic": {"type": "string", "description": "Subject for PPT"},
                "mode": {"type": "string", "description": "Generation mode (agentic or fast)"},
                "audience": {"type": "string", "description": "Target audience (for PPT)"},
                "tone": {"type": "string", "description": "Tone of voice (for PPT)"},
                "projectTitle": {"type": "string", "description": "Title for report"},
                "projectDescription": {"type": "string", "description": "Description for report"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        if action == "generate_ppt":
            return await self._build_ppt(parameters)
        elif action == "generate_report":
            return await self._build_report(parameters)
        return {"message": f"Unknown action: {action}"}

    async def _build_ppt(self, params: dict[str, Any]) -> dict[str, Any]:
        topic = params.get("topic") or "General presentation"
        mode = params.get("mode", "agentic")
        audience = params.get("audience")
        tone = params.get("tone")

        logger.info("Opening Auto Slider via deep-link for topic: %s", topic)
        
        query_params = {
            "topic": topic,
            "autogenerate": "1",
            "autodownload": "pptx",
            "mode": mode,
        }
        if tone:
            query_params["tone"] = tone
        if audience:
            query_params["audience"] = audience

        url = f"{self.WEB_APP_URL}/?{urllib.parse.urlencode(query_params)}"
        self._auto_open_url(url)
        
        msg = f"Opening Auto Slider for '{topic}' — your presentation will auto-generate and download in 1–3 minutes. Watch the browser. 🪄"
        
        return {"message": msg, "skill_type": "presentation"}

    async def _build_report(self, params: dict[str, Any]) -> dict[str, Any]:
        title = params.get("projectTitle") or "Academic Report"
        desc = params.get("projectDescription") or ""

        logger.info("Generating Report via API for title: %s", title)
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEFAULT_API_KEY}"
        }
        payload = {
            "action": "generate_report",
            "projectTitle": title,
            "projectDescription": desc
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(self.API_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                if not data.get("success"):
                    raise Exception(data.get("error", "Unknown API error"))
                
                self._auto_open_url(self.WEB_APP_URL)

                chapters = data.get("content", {}).get("chapters", [])
                title_returned = data.get("projectTitle", title)

                msg = (
                    f"Done! I've successfully generated the academic report on '{title_returned}'. "
                    f"It contains {len(chapters)} chapters. I have opened {self.WEB_APP_URL} in your browser so you can view it."
                )

                return {"message": msg, "skill_type": "presentation"}

        except Exception as e:
            logger.exception("Failed to generate Report via Auto Slider API")
            return {"message": f"Sorry, I failed to create the report: {str(e)}"}

    def _auto_open_url(self, url: str):
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.warning("Failed to open browser for %s: %s", url, e)
