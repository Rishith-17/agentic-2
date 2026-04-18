"""Speech-to-Command processor for J.A.R.V.I.S.

Converts raw transcribed speech into clean, structured JSON commands
for automation. Strips filler words, normalizes intent, and outputs
machine-executable directives.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)

# ── Filler words / noise to strip ────────────────────────────────────────────
_FILLER_WORDS = {
    "uh", "um", "hmm", "like", "you know", "basically", "actually",
    "hey", "hi", "hello", "please", "jarvis", "hey jarvis",
    "could you", "can you", "would you", "will you",
    "i want you to", "i need you to", "i'd like you to",
    "go ahead and", "just", "kindly",
}

# ── Intent keywords mapping ──────────────────────────────────────────────────
_INTENT_MAP: list[tuple[list[str], str]] = [
    (["open", "launch", "start", "run"], "open_app"),
    (["close", "quit", "exit", "kill", "stop"], "close_app"),
    (["play", "listen", "watch"], "play_media"),
    (["search", "google", "find", "look up"], "web_search"),
    (["volume", "sound"], "set_volume"),
    (["brightness", "screen"], "set_brightness"),
    (["wifi", "bluetooth", "network"], "toggle_connectivity"),
    (["email", "mail", "inbox", "gmail"], "email_action"),
    (["whatsapp", "message", "text", "send message"], "send_message"),
    (["weather", "forecast", "temperature"], "get_weather"),
    (["news", "headlines"], "get_news"),
    (["calendar", "schedule", "meeting", "appointment"], "calendar_action"),
    (["file", "folder", "document", "create file"], "file_action"),
    (["screenshot", "capture", "screen"], "capture_screen"),
    (["shutdown", "restart", "sleep", "lock"], "system_power"),
    (["timer", "alarm", "reminder"], "set_timer"),
    (["mute", "unmute"], "toggle_mute"),
    (["copy", "paste", "clipboard"], "clipboard_action"),
    (["navigate", "directions", "map", "route"], "navigation"),
    (["order", "food", "grocery", "swiggy", "zomato"], "food_order"),
]


SPEECH_COMMAND_SYSTEM_PROMPT = """You are the speech-to-command processor for J.A.R.V.I.S.

Your job is to convert spoken input into clean, structured commands for automation.

---

OBJECTIVE

- Remove filler words (uh, um, hey, please, Jarvis)
- Convert speech into direct commands
- Keep it short, clear, and executable

---

PROCESSING

1. Clean input:
   - "hey jarvis can you open chrome please" → "open chrome"

2. Normalize:
   - "turn the volume up to max" → "set volume 100"

3. Detect intent and entities

---

OUTPUT FORMAT (STRICT JSON)

{
  "command": "clean command",
  "intent": "action_type",
  "entities": {
    "target": "",
    "value": "",
    "extra": ""
  }
}

---

EXAMPLES

Input: "Jarvis open WhatsApp"
Output: {"command": "open whatsapp", "intent": "open_app", "entities": {"target": "whatsapp"}}

Input: "can you play some music"
Output: {"command": "play music", "intent": "play_media", "entities": {}}

Input: "turn the volume up to max"
Output: {"command": "set volume 100", "intent": "set_volume", "entities": {"target": "volume", "value": "100"}}

Input: "send hello to 917349340870 on whatsapp"
Output: {"command": "send whatsapp message", "intent": "send_message", "entities": {"target": "917349340870", "value": "hello"}}

Input: "what's the weather in Hyderabad"
Output: {"command": "get weather hyderabad", "intent": "get_weather", "entities": {"target": "hyderabad"}}

---

RULES

- ONLY return JSON
- No explanation
- No raw speech
- Keep commands minimal

---

GOAL

Convert human speech into machine-executable commands."""


def _clean_filler(text: str) -> str:
    """Remove filler words and noise from raw transcription."""
    cleaned = text.lower().strip()

    # Sort fillers longest-first so multi-word fillers match before single words
    for filler in sorted(_FILLER_WORDS, key=len, reverse=True):
        # Use word boundary matching
        cleaned = re.sub(rf'\b{re.escape(filler)}\b', '', cleaned, flags=re.IGNORECASE)

    # Collapse whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def _detect_intent(cleaned: str) -> str:
    """Fast heuristic intent detection from cleaned text."""
    lower = cleaned.lower()
    for keywords, intent in _INTENT_MAP:
        if any(kw in lower for kw in keywords):
            return intent
    return "general"


def _extract_entities(cleaned: str, intent: str) -> dict[str, str]:
    """Extract target/value entities from the cleaned command."""
    entities: dict[str, str] = {}
    lower = cleaned.lower()

    if intent == "open_app":
        # Everything after "open/launch/start/run"
        for verb in ["open", "launch", "start", "run"]:
            if verb in lower:
                target = lower.split(verb, 1)[1].strip()
                if target:
                    entities["target"] = target
                break

    elif intent == "set_volume":
        nums = re.findall(r'\d+', cleaned)
        if nums:
            entities["value"] = nums[0]
        entities["target"] = "volume"

    elif intent == "set_brightness":
        nums = re.findall(r'\d+', cleaned)
        if nums:
            entities["value"] = nums[0]
        entities["target"] = "brightness"

    elif intent == "send_message":
        phone = re.search(r'\b(\d{10,15})\b', cleaned)
        if phone:
            entities["target"] = phone.group(1)

    elif intent == "get_weather":
        # City is usually the last word(s)
        for prefix in ["weather in", "weather for", "forecast for", "forecast in", "weather"]:
            if prefix in lower:
                city = lower.split(prefix, 1)[1].strip()
                if city:
                    entities["target"] = city
                break

    elif intent == "play_media":
        for verb in ["play", "listen to", "watch"]:
            if verb in lower:
                target = lower.split(verb, 1)[1].strip()
                if target:
                    entities["target"] = target
                break

    return entities


def process_speech_local(raw_text: str) -> dict[str, Any]:
    """
    Fast LOCAL processing — no LLM call.
    Clean filler → detect intent → extract entities → return JSON.
    """
    cleaned = _clean_filler(raw_text)
    if not cleaned:
        return {
            "command": "",
            "intent": "empty",
            "entities": {},
        }

    intent = _detect_intent(cleaned)
    entities = _extract_entities(cleaned, intent)

    return {
        "command": cleaned,
        "intent": intent,
        "entities": entities,
    }


async def process_speech_llm(
    raw_text: str,
    settings: Settings,
) -> dict[str, Any]:
    """
    LLM-powered processing using Nemotron — sends the raw transcription
    through the speech-to-command system prompt for structured output.

    Falls back to local processing if LLM fails.
    """
    from app.services.llm import chat

    try:
        messages = [
            {"role": "system", "content": SPEECH_COMMAND_SYSTEM_PROMPT},
            {"role": "user", "content": raw_text},
        ]

        raw_response = await chat(messages, settings, temperature=0.1)

        # Parse the JSON from the response
        # Try to extract JSON from the response
        match = re.search(r'(\{.*\})', raw_response, re.DOTALL)
        if match:
            result = json.loads(match.group(1))
            # Validate required keys
            if "command" in result and "intent" in result:
                if "entities" not in result:
                    result["entities"] = {}
                logger.info("Speech→Command (LLM): %s → %s", raw_text, result)
                return result

        # If JSON parsing fails, fall through to local
        logger.warning("LLM returned non-JSON for speech command: %s", raw_response)

    except Exception as exc:
        logger.warning("Speech command LLM failed, using local: %s", exc)

    # Fallback to local processing
    result = process_speech_local(raw_text)
    logger.info("Speech→Command (local): %s → %s", raw_text, result)
    return result
