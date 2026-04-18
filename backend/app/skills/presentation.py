"""Presentation generation via auto-slide-creator.vercel.app automation."""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from app.skills.base import SkillBase

logger = logging.getLogger(__name__)


class PresentationSkill(SkillBase):
    name = "presentation"
    description = "Generate PowerPoint presentations by automating auto-slide-creator.vercel.app."

    BASE_URL = "https://auto-slide-creator.vercel.app"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create_presentation", "create_and_send"],
                },
                "topic": {"type": "string"},
                "recipients": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        topic = parameters.get("topic") or ""
        if not topic:
            return {
                "message": "Please specify a topic for the presentation.",
                "summary_text": "Please specify a topic for the presentation.",
            }

        try:
            msg_initial = f"🚀 Starting PPT generation for '{topic}' on your website..."
            logger.info(msg_initial)
            
            async with async_playwright() as p:
                # Launch browser - headless=True for background work, but False could be helpful for debugging
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                
                # 1. Navigate to the website
                await page.goto(self.BASE_URL, wait_until="networkidle")
                
                # 2. Enter Topic
                # Try multiple selectors for robustness
                input_selector = "input.builder-input"
                await page.wait_for_selector(input_selector, timeout=10000)
                await page.fill(input_selector, topic)
                
                # 3. Trigger Generation (Enter)
                await page.keyboard.press("Enter")
                
                # 4. Wait for it to finish
                # The 'Export' button appears in the top right when done
                export_button_selector = "button:has-text('Export')"
                # Generations can take up to 90 seconds
                await page.wait_for_selector(export_button_selector, timeout=120000)
                
                # 5. Open Export Menu
                await page.click(export_button_selector)
                
                # 6. Click PowerPoint to start download
                # We need to expect a download object
                pptx_option_selector = "button:has-text('PowerPoint')"
                async with page.expect_download() as download_info:
                    await page.click(pptx_option_selector)
                
                download = await download_info.value
                
                # 7. Save the file
                output_dir = Path.home() / "Documents" / "Jarvis_Presentations"
                output_dir.mkdir(parents=True, exist_ok=True)
                
                filename = f"{topic.replace(' ', '_')[:30]}_{os.urandom(2).hex()}.pptx"
                save_path = output_dir / filename
                await download.save_as(str(save_path))
                
                await browser.close()

            # 8. Auto-open the file
            if platform.system() == "Windows":
                os.startfile(save_path)
            elif platform.system() == "Darwin":
                subprocess.run(["open", str(save_path)])
            else:
                subprocess.run(["xdg-open", str(save_path)])

            msg = f"✅ Done! I've generated your presentation on '{topic}' and opened it for you. You can find it in your Documents/Jarvis_Presentations folder."
            return {"message": msg, "summary_text": msg, "skill_type": "presentation"}

        except Exception as e:
            logger.exception("Website PPT Automation failed")
            return {
                "message": f"Darn! I ran into an issue while automating your website: {str(e)[:100]}...",
                "summary_text": str(e)
            }
