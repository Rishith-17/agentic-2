"""LLM planner/chat service with deterministic routing guardrails."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from urllib.parse import quote
from typing import Any

from pydantic import BaseModel, Field

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class Plan(BaseModel):
    skill: str = Field(default="")
    action: str = Field(default="default")
    parameters: dict[str, Any] = Field(default_factory=dict)
    reply_text: str = Field(default="")
    needs_skill: bool = Field(default=True)


SYSTEM_PLANNER = """You are Jarvis, an AI automation orchestrator.

Your job is NOT to chat. Your job is to EXECUTE tasks accurately using the correct tool.

---
🎯 OBJECTIVE
For every user command:
1. Understand the intent
2. Select the correct tool/module
3. Execute the action

---
🧠 AVAILABLE TOOLS
You must strictly choose ONE of these tools:
- GMAIL → read/send/search emails, summarize inbox
- GOOGLE_DOCS → create/read/update documents
- GOOGLE_DRIVE → upload/download/search files
- GOOGLE_SHEETS → create/update sheets
- GOOGLE_CALENDAR → schedule/manage events
- GOOGLE_MAPS → location, directions, places
- WEATHER → fetch current weather and forecasts (use action="current" or "forecast")
- NEWS → fetch latest news (use action="headlines")
- WHATSAPP → send message
- FILE_SYSTEM → create/delete/read files
- SYSTEM_CONTROL → open apps (param: app_name), volume (param: level), brightness (param: level), wifi (param: sub_action='on'/'off')
- WEB_AGENT → search, browse, scrape websites
- PRESENTATION → generate PPT
- FILE_SHARE → upload and generate share link

---
⚙️ EXECUTION RULE (VERY STRICT)
You MUST respond ONLY in this JSON format:
{
"tool": "TOOL_NAME",
"action": "action_name",
"input": {
  "param1": "value1",
  "level": 50
}
}

---
🧠 TOOL SELECTION RULES
- If user says "email", "gmail", "mail", "inbox", "summarize mails" → GMAIL
- If user says "create document" → GOOGLE_DOCS
- If user says "send message", "whatsapp" → WHATSAPP
- If user says "find location" → GOOGLE_MAPS
- If user says "latest news" → NEWS
- If user says "weather" or asks for forecast → WEATHER
- If user says "open app" or "volume" or "brightness" → SYSTEM_CONTROL
- If user says "search online" → WEB_AGENT
- If user says "create ppt" → PRESENTATION
- If user says "upload/share file" → FILE_SHARE
- If user says "calendar", "schedule", "appointment" → GOOGLE_CALENDAR

---
❌ DO NOT
- Do NOT explain
- Do NOT give text answers
- Do NOT mix multiple tools
- Do NOT guess unclear input

---
⚠️ IF COMMAND IS UNCLEAR
Return:
{
"tool": "NONE",
"action": "clarify",
"input": {
"message": "Please provide more details"
}
}
"""


_VALID_SKILLS = {
    "alerts",
    "briefing",
    "browser_agent",
    "calculator",
    "calendar",
    "clipboard",
    "code_assistant",
    "docs",
    "drive",
    "file_manager",
    "file_share",
    "food_grocery",
    "gesture_control",
    "gmail",
    "learning_course_search",
    "learning_explain",
    "learning_progress",
    "learning_study_plan",
    "maps",
    "memory_skill",
    "news",
    "places",
    "presentation",
    "shopping_deal_finder",
    "shopping_price_alert",
    "shopping_price_compare",
    "sheets",
    "system_control",
    "weather",
    "web_agent",
    "whatsapp",
}


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    try:
        cleaned = text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception:
        return {"reply_text": text}


def _heuristic_plan(text: str) -> Plan | None:
    lower = text.lower().strip()
    if not lower:
        return Plan(needs_skill=False, reply_text="How can I help?")

    # WhatsApp message sending - check FIRST if there's a phone number
    # This prevents misclassification when long messages contain words like "food"
    contact_match = re.search(r'\b(\d{10,15})\b', text)
    whatsapp_terms = {"whatsapp", "wa message", "send message to", "text to", "message", "send"}
    if contact_match and any(term in lower for term in whatsapp_terms):
        # Try to extract contact and message
        # Patterns: "send hello to 917349340870", "whatsapp 917349340870 hello", "message 917349340870 saying hello"
        contact = contact_match.group(1)
        contact_pos = contact_match.start()
        contact_end = contact_match.end()
        
        # Extract message - everything after the contact number
        # First, try to find message after the contact number
        after_contact = text[contact_end:].strip()
        
        # If there's content after the contact, use that as the message
        if after_contact:
            message = after_contact
        else:
            # Otherwise, try to find message before the contact
            # Look for patterns like "send [message] to [number]"
            before_contact = text[:contact_pos].strip()
            
            # Try to find "to" before the number and extract everything before it
            to_match = re.search(r'\bto\s*$', before_contact, re.IGNORECASE)
            if to_match:
                # Extract message before "to"
                message = before_contact[:to_match.start()].strip()
                # Remove command prefix like "send", "whatsapp", etc.
                message = re.sub(r'^(send|whatsapp|message|text)\s+', '', message, flags=re.IGNORECASE).strip()
            else:
                # No "to" found, just remove command prefix
                message = re.sub(r'^(send|whatsapp|message|text)\s+(message\s+)?(to\s+)?', '', before_contact, flags=re.IGNORECASE).strip()
        
        if message and contact:
            return Plan(
                skill="whatsapp",
                action="send_message",
                parameters={"contact": contact, "message": message},
                reply_text="",
                needs_skill=True,
            )

    # Gmail/Email operations - check before food to avoid misclassification
    gmail_terms = {"email", "gmail", "mail", "inbox", "summarize mail", "summarise mail", "read mail", "send email", "unread"}
    if any(term in lower for term in gmail_terms):
        # Determine the action based on keywords
        if "summarize" in lower or "summarise" in lower:
            return Plan(
                skill="gmail",
                action="summarize_inbox",
                parameters={},
                reply_text="",
                needs_skill=True,
            )
        elif "unread" in lower or "read" in lower:
            return Plan(
                skill="gmail",
                action="read_unread",
                parameters={},
                reply_text="",
                needs_skill=True,
            )
        elif "send" in lower:
            return Plan(
                skill="gmail",
                action="send_email",
                parameters={},
                reply_text="",
                needs_skill=True,
            )
        else:
            # Default to list messages
            return Plan(
                skill="gmail",
                action="list_messages",
                parameters={},
                reply_text="",
                needs_skill=True,
            )

    food_terms = {"order", "food", "grocery", "swiggy", "zomato", "blinkit", "zepto", "biryani", "pizza", "milk"}
    if any(word in lower for word in food_terms):
        return Plan(
            skill="food_grocery",
            action="smart_order",
            parameters={"query": text},
            reply_text="",
            needs_skill=True,
        )

    if "openclaw" in lower or "open claw" in lower:
        return Plan(
            skill="web_agent",
            action="run",
            parameters={"task": text},
            reply_text="",
            needs_skill=True,
        )

    browser_terms = {"automate", "browser", "book", "login", "fill form", "website"}
    if any(word in lower for word in browser_terms):
        return Plan(skill="web_agent", action="run", parameters={"task": text}, needs_skill=True)

    media_terms = {"play song", "play video", "play music", "youtube", "listen to", "watch"}
    if any(term in lower for term in media_terms) or lower.startswith("play "):
        return Plan(skill="browser_agent", action="youtube_play", parameters={"query": text}, needs_skill=True)
    
    gesture_terms = {"gesture control", "hand tracking", "gesture tracking", "start gesture", "activate gesture"}
    if any(term in lower for term in gesture_terms):
        return Plan(skill="gesture_control", action="start", parameters={"show_window": True}, needs_skill=True)
    if "stop gesture" in lower or "disable gesture" in lower:
        return Plan(skill="gesture_control", action="stop", parameters={}, needs_skill=True)

    if lower.startswith("open google"):
        return Plan(skill="browser_agent", action="open_browser", parameters={"url": "https://www.google.com"}, needs_skill=True)

    if lower.startswith("open youtube"):
        return Plan(skill="browser_agent", action="open_browser", parameters={"url": "https://www.youtube.com"}, needs_skill=True)

    if lower.startswith("open ") and any(name in lower for name in {"gmail", "youtube", "facebook", "instagram", "github"}):
        return Plan(skill="system_control", action="open_app", parameters={"app_name": text.replace("open", "", 1).strip()}, needs_skill=True)

    app_builder_terms = {
        "build app",
        "create app",
        "generate app",
        "next.js",
        "nextjs",
        "vercel",
        "app router",
        "tailwind",
        "full-stack application",
    }
    if any(term in lower for term in app_builder_terms):
        return Plan(
            skill="code_assistant",
            action="app_builder",
            parameters={"prompt": text},
            needs_skill=True,
        )

    # Keep maps routing strict so "app router" does not get misclassified.
    if "map" in lower or "directions" in lower:
        return Plan(skill="maps", action="get_directions", parameters={}, needs_skill=True)
    if "route" in lower and "app router" not in lower and "router" not in lower:
        return Plan(skill="maps", action="get_directions", parameters={}, needs_skill=True)

    return None


def _sanitize_plan(data: dict[str, Any], user_text: str) -> dict[str, Any]:
    # Remap new schema to old internally
    if "tool" in data and "skill" not in data:
        data["skill"] = str(data.pop("tool")).lower()
    if "input" in data and "parameters" not in data:
        raw_input = data.pop("input")
        if isinstance(raw_input, dict):
            if "details" in raw_input and len(raw_input) == 1:
                val = str(raw_input["details"]).lower()
                if "system_control" in str(data.get("skill", "")):
                    import re
                    if "volume" in str(data.get("action", "")) or "brightness" in str(data.get("action", "")):
                        nums = re.findall(r"\d+", val)
                        if nums:
                            raw_input["level"] = int(nums[0])
                    elif "wifi" in str(data.get("action", "")):
                        if "off" in val or "disable" in val:
                            raw_input["sub_action"] = "off"
                        elif "on" in val or "enable" in val:
                            raw_input["sub_action"] = "on"
            # If the tool gives {"details": "something"}, we can pass it as parameters
            data["parameters"] = raw_input
        else:
            data["parameters"] = {}

    # Handle clarification/none
    if data.get("skill") == "none":
        data["skill"] = "memory_skill"
        data["action"] = "recall_context"
        data["needs_skill"] = False
        msg = data.get("parameters", {}).get("message")
        if msg:
            data["reply_text"] = msg

    plan = Plan(**data)
    skill = (plan.skill or "").strip()
    lower = user_text.lower().strip()

    # Normalize WhatsApp parameter names: phone_number → contact
    if skill == "whatsapp" and "phone_number" in plan.parameters:
        plan.parameters["contact"] = plan.parameters.pop("phone_number")

    # Normalize new prompt tool names to actual skill module names
    alias_map = {
        "google_docs": "docs",
        "google_drive": "drive",
        "google_sheets": "sheets",
        "google_calendar": "calendar",
        "google_maps": "maps",
        "file_system": "file_manager",
        "news": "news",
        "weather": "weather",
        "whatsapp": "whatsapp",
        "system_control": "system_control",
        "web_agent": "web_agent",
        "presentation": "presentation",
        "file_share": "file_share",
        # legacy map fallbacks
        "web_search": "browser_agent",
        "play_media": "browser_agent",
        "music": "browser_agent",
        "home_automation": "system_control",
    }
    skill = alias_map.get(skill, skill)
    plan.skill = skill

    actionable_media = lower.startswith("play ") or "play song" in lower or "play video" in lower or "youtube" in lower
    actionable_open = lower.startswith("open ") or lower.startswith("search ")

    if not plan.needs_skill and (actionable_media or actionable_open):
        if actionable_media:
            return Plan(
                skill="browser_agent",
                action="youtube_play",
                parameters={"query": user_text},
                reply_text="",
                needs_skill=True,
            ).model_dump()
        if lower.startswith("open google"):
            return Plan(
                skill="browser_agent",
                action="open_browser",
                parameters={"url": "https://www.google.com"},
                reply_text="",
                needs_skill=True,
            ).model_dump()
        return Plan(
            skill="browser_agent",
            action="google_search",
            parameters={"query": user_text},
            reply_text="",
            needs_skill=True,
        ).model_dump()

    if not plan.needs_skill:
        return plan.model_dump()

    if skill not in _VALID_SKILLS:
        logger.warning("Planner returned unknown skill '%s'; falling back to memory_skill", skill)
        return Plan(
            skill="memory_skill",
            action="recall_context",
            parameters={"query": user_text},
            reply_text="",
            needs_skill=True,
        ).model_dump()

    # Ensure actionable parameters for critical skills.
    if skill == "food_grocery":
        if plan.action not in {"smart_order", "search", "add_to_cart", "view_cart", "place_order", "track_order", "recommend", "surprise_me", "set_preference", "login", "enter_otp"}:
            plan.action = "smart_order"
        if "query" not in plan.parameters:
            plan.parameters["query"] = user_text

    if skill == "web_agent":
        plan.action = "run"
        if "task" not in plan.parameters:
            plan.parameters["task"] = user_text

    if skill == "browser_agent":
        if plan.action not in {"open_browser", "google_search", "youtube_play", "tab_action", "open_website"}:
            plan.action = "google_search"
        if plan.action == "youtube_play" and "query" not in plan.parameters:
            plan.parameters["query"] = user_text
        if plan.action == "google_search" and "query" not in plan.parameters:
            plan.parameters["query"] = user_text

    if skill == "code_assistant":
        if plan.action not in {"generate", "explain_clipboard", "write_file", "app_builder"}:
            plan.action = "generate"
        if plan.action in {"generate", "app_builder"} and "prompt" not in plan.parameters:
            plan.parameters["prompt"] = user_text

    return plan.model_dump()


async def chat(messages: list[dict[str, str]], settings: Settings, temperature: float = 0.5, force_smart: bool = False) -> str:
    if settings.nim_api_key:
        return await _nim_chat(messages, settings, temperature, force_smart)
    return await _ollama_chat(messages, settings, temperature)


async def plan_intent(text: str, context: str | None = None, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()

    # Fast-path search intent detection (bypasses FoodIntentEngine)
    # Only trigger on explicit search commands, not just presence of "google"
    lower = text.lower().strip()
    
    # Check for explicit search patterns
    explicit_search_patterns = [
        r'\bsearch\s+',           # "search virat kohli"
        r'\bsearch\s+for\s+',     # "search for pizza"
        r'\bgoogle\s+',           # "google python tutorial" (but not "open google")
        r'\blook\s+up\s+',        # "look up weather"
        r'\bfind\s+information\s+about\s+',  # "find information about..."
    ]
    
    # Don't trigger on "open google" or "open youtube" - these should use open_browser
    if not lower.startswith("open "):
        for pattern in explicit_search_patterns:
            if re.search(pattern, lower):
                # Extract query by removing the search keyword
                query = text
                for kw in ["search", "search for", "google", "look up", "find information about"]:
                    if kw in lower:
                        query = re.sub(rf'\b{re.escape(kw)}\b', '', text, flags=re.IGNORECASE).strip()
                        break
                if not query:
                    query = text
                return Plan(
                    skill="browser_agent",
                    action="google_search",
                    parameters={"query": query},
                    reply_text="",
                    needs_skill=True,
                ).model_dump()

    heuristic = _heuristic_plan(text)
    if heuristic is not None:
        return heuristic.model_dump()

    prompt = f"{SYSTEM_PLANNER}\nUSER: {text}\nCONTEXT: {context or ''}\nPLAN:"
    smart_keywords = ["order", "food", "buy", "browse", "swiggy", "zomato", "search", "automate", "checkout"]
    use_smart = any(kw in text.lower() for kw in smart_keywords) or len(text) > 50

    try:
        raw = await chat([{"role": "user", "content": prompt}], settings, force_smart=use_smart)
        data = _extract_json(raw)
        return _sanitize_plan(data, text)
    except Exception as exc:
        logger.error("Planning failed: %s", exc)
        return Plan(
            skill="memory_skill",
            action="recall_context",
            parameters={"query": text},
            reply_text="",
            needs_skill=True,
        ).model_dump()


async def _nim_chat(messages: list[dict[str, str]], settings: Settings, temperature: float = 0.5, force_smart: bool = False) -> str:
    from app.dependencies import get_app_state

    try:
        client = get_app_state().client
    except Exception:
        import httpx

        client = httpx.AsyncClient(timeout=120.0)

    model = settings.nim_smart_model if force_smart else settings.nim_fast_model
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": 0.7,
        "max_tokens": 1024,
    }
    headers = {"Authorization": f"Bearer {settings.nim_api_key}", "Content-Type": "application/json"}
    response = await client.post(f"{settings.nim_base_url}/chat/completions", headers=headers, json=payload)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


async def _ollama_chat(messages: list[dict[str, str]], settings: Settings, temperature: float = 0.5) -> str:
    from app.dependencies import get_app_state

    try:
        client = get_app_state().client
    except Exception:
        import httpx

        client = httpx.AsyncClient(timeout=120.0)

    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    response = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
    response.raise_for_status()
    return response.json()["message"]["content"]


async def bedrock_chat(
    messages: list[dict[str, str]],
    settings: Settings,
    *,
    temperature: float = 0.1,
    max_tokens: int = 4000,
    model_id: str | None = None,
) -> str:
    """
    Call AWS Bedrock Claude via Messages API.
    Used by code_assistant app_builder when BEDROCK_ENABLED=true.
    """
    if not settings.bedrock_enabled:
        raise RuntimeError("Bedrock is disabled. Set BEDROCK_ENABLED=true to use it.")

    use_model = model_id or settings.bedrock_claude_model_id
    if not use_model:
        raise RuntimeError("Missing Bedrock model ID in BEDROCK_CLAUDE_MODEL_ID")

    # Bearer token path (new Bedrock API key style)
    if settings.aws_bearer_token_bedrock:
        return await _bedrock_bearer_chat(
            messages,
            settings,
            model_id=use_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _invoke() -> str:
        import boto3

        client = boto3.client("bedrock-runtime", region_name=settings.aws_region)

        system_chunks: list[str] = []
        bedrock_messages: list[dict[str, Any]] = []
        for m in messages:
            role = (m.get("role") or "user").strip().lower()
            content = str(m.get("content") or "")
            if role == "system":
                system_chunks.append(content)
                continue
            bedrock_role = "assistant" if role == "assistant" else "user"
            bedrock_messages.append(
                {
                    "role": bedrock_role,
                    "content": [{"type": "text", "text": content}],
                }
            )

        payload: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": bedrock_messages,
        }
        if system_chunks:
            payload["system"] = "\n\n".join(system_chunks)

        response = client.invoke_model(
            modelId=use_model,
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json",
        )
        raw = json.loads(response["body"].read().decode("utf-8"))
        chunks = raw.get("content") or []
        text = "".join(c.get("text", "") for c in chunks if c.get("type") == "text")
        if not text:
            raise RuntimeError(f"Bedrock returned empty content: {raw}")
        return text

    return await asyncio.to_thread(_invoke)


async def _bedrock_bearer_chat(
    messages: list[dict[str, str]],
    settings: Settings,
    *,
    model_id: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """Call Bedrock runtime using AWS_BEARER_TOKEN_BEDROCK over HTTPS."""
    import httpx

    system_chunks: list[str] = []
    bedrock_messages: list[dict[str, Any]] = []
    for m in messages:
        role = (m.get("role") or "user").strip().lower()
        content = str(m.get("content") or "")
        if role == "system":
            system_chunks.append(content)
            continue
        bedrock_role = "assistant" if role == "assistant" else "user"
        bedrock_messages.append(
            {
                "role": bedrock_role,
                "content": [{"text": content}],
            }
        )

    payload: dict[str, Any] = {
        "messages": bedrock_messages,
        "inferenceConfig": {
            "temperature": temperature,
            "maxTokens": max_tokens,
        },
    }
    if system_chunks:
        payload["system"] = [{"text": "\n\n".join(system_chunks)}]

    encoded_model = quote(model_id, safe="")
    url = f"https://bedrock-runtime.{settings.aws_region}.amazonaws.com/model/{encoded_model}/converse"
    headers = {
        "Authorization": f"Bearer {settings.aws_bearer_token_bedrock}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        raw = response.json()

    output = raw.get("output", {})
    message = output.get("message", {})
    chunks = message.get("content") or []
    text = "".join(c.get("text", "") for c in chunks if isinstance(c, dict))
    if not text:
        raise RuntimeError(f"Bedrock bearer call returned empty content: {raw}")
    return text
