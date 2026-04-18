import asyncio
import logging
from typing import Any, List, Optional
from pydantic import BaseModel

from app.skills.base import SkillBase

# Initialize logger
logger = logging.getLogger(__name__)

class WebAgentSkill(SkillBase):
    """
    JARVIS Skill: Web Agent
    Uses browser-use with NVIDIA NIM (LLaMA-3-Vision) to automate browser tasks.
    """
    name = "web_agent"
    description = "Automate browser tasks using computer vision."
    priority = 10
    keywords = ["browser", "automate", "website", "login", "fill form", "search", "claw", "openclaw"]

    def __init__(self):
        # We lazy-load dependencies in execute to handle missing browser-use gracefully
        pass

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        Execute the web agent skill.
        
        Args:
            action (str): The action to perform (e.g., 'run', 'search').
            params (dict): Parameters for the action. 
                        Required: 'task' (the natural language task)
                        Optional: 'model', 'headless', 'max_steps'
        """
        task = params.get("task") or params.get("query")
        if not task:
            return {"success": False, "message": "Missing 'task' parameter for web agent."}

        model = params.get("model", "nvidia/llama-3.2-90b-vision-instruct")
        headless = params.get("headless", False)
        max_steps = int(params.get("max_steps", 15))
        timeout = int(params.get("timeout", 120))

        logger.info(f"WebAgent: task='{task}' model={model} headless={headless} max_steps={max_steps} timeout={timeout}s")

        try:
            # We wrap the call in a timeout to prevent hanging the whole system
            result = await asyncio.wait_for(
                _run_browser_agent(
                    task=task,
                    nim_api_key=os.getenv("NVIDIA_NIM_API_KEY"),
                    nim_base_url="https://integrate.api.nvidia.com/v1",
                    model=model,
                    headless=headless,
                    max_steps=max_steps,
                ),
                timeout=timeout
            )
            return {
                "success": True,
                "message": result.get("answer", "Task completed."),
                "data": result,
                "skill_type": "web_agent"
            }
        except asyncio.TimeoutError:
            return {
                "success": False,
                "message": "Web agent timed out. The task was too complex or the network was slow.",
                "skill_type": "web_agent"
            }
        except Exception as e:
            logger.error(f"WebAgent error: {str(e)}", exc_info=True)
            return {
                "success": False,
                "message": f"Browser agent encountered an error: {str(e)}",
                "skill_type": "web_agent"
            }

import os

# ── Dependency Helpers ───────────────────────────────────────────────────────

def require(module_name: str, install_cmd: str):
    try:
        import importlib
        importlib.import_module(module_name.replace("-", "_"))
    except ImportError:
        raise ImportError(f"Missing dependency: {module_name}. Install it with: {install_cmd}")

# ── Result Extraction ────────────────────────────────────────────────────────

def _extract_result(history: Any, task: str) -> dict[str, Any]:
    """
    Extract a human-readable result from the browser-use AgentHistory object.
    """
    try:
        # browser-use >= 0.1.x: history has .final_result() method
        if hasattr(history, "final_result"):
            ans = history.final_result()
            if ans:
                return {"answer": ans, "history": str(history)}
        
        # Fallback: check last step
        if history and hasattr(history, "steps") and history.steps:
            last_step = history.steps[-1]
            if hasattr(last_step, "result") and last_step.result:
                return {"answer": last_step.result, "history": str(history)}
    except Exception:
        pass
    
    return {"answer": "Task completed, but I couldn't summarize the specific result.", "history": str(history)}

# ── Core agent runner ─────────────────────────────────────────────────────────

async def _run_browser_agent(
    *,
    task: str,
    nim_api_key: str,
    nim_base_url: str,
    model: str,
    headless: bool,
    max_steps: int,
) -> dict[str, Any]:
    """
    Initialise browser-use Agent with NVIDIA NIM VLM and run the task.
    """
    try:
        from browser_use.llm import ChatOpenAI
        from browser_use import Agent, Browser
    except ImportError as exc:
        raise ImportError(
            f"browser-use or its dependencies not installed correctly: {exc}. "
            "Run: pip install browser-use"
        ) from exc

    # browser-use version 0.12.x requires the LLM to be wrapped in their own ChatOpenAI
    # which provides the 'provider' attribute.
    llm = ChatOpenAI(
        model=model,
        api_key=nim_api_key,
        base_url=nim_base_url.rstrip("/"),
        temperature=0.1,
        max_completion_tokens=4096,
    )

    # Browser initialization (BrowserSession in modern browser-use)
    browser = Browser(headless=headless)

    try:
        agent = Agent(
            task=task,
            llm=llm,
            browser=browser,
            use_vision=True,
            # max_actions_per_step was renamed in some versions or is handled in run()
        )

        logger.info(f"WebAgent: starting browser-use Agent (task='{task}')")
        history = await agent.run(max_steps=max_steps)
        final_result = _extract_result(history, task)
        return final_result
    finally:
        try:
            await browser.kill()
        except Exception:
            pass
