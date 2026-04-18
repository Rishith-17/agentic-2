"""Voice/text pipeline: STT → State Machine → LLM → Router → Memory → TTS.

Food ordering flow (deterministic — LLM is bypassed for all steps after initial request):
  1. User: "buy biryani"        → LLM → food_grocery.smart_order → step=awaiting_selection
  2. User: "2" / "option 2"    → pipeline intercepts → add_to_cart → step=awaiting_confirmation
  3. User: "yes"               → pipeline intercepts → place_order  → step="" (done)
  4. User: "cancel"            → pipeline intercepts → clear state

Location flow:
  1. food_grocery detects no location → sets step=asking_location
  2. User types a city name          → pipeline stores it → retries smart_order
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from app.config import Settings
from app.dependencies import AppState
from app.services import llm
from app.services.stt_whisper import transcribe_upload_bytes
from app.services.tts_pyttsx3 import speak_to_bytes

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_ORDINALS: dict[str, int] = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
}

_CANCEL_WORDS = {"cancel", "no", "stop", "nevermind", "never mind", "abort", "quit", "exit"}
_CONFIRM_WORDS = {"yes", "confirm", "ok", "sure", "proceed", "place", "order it",
                  "go ahead", "do it", "yeah", "yep", "yup", "absolutely", "definitely"}


def _parse_index(text: str) -> int | None:
    """Parse a 1-based number/ordinal from *text*. Returns 0-based index or None."""
    t = text.lower().strip()
    for word, num in _ORDINALS.items():
        if word in t.split():
            return num - 1
    m = re.search(r"\b([1-5])\b", t)
    if m:
        return int(m.group(1)) - 1
    return None


def _is_cancel(text: str) -> bool:
    return any(w in text.lower() for w in _CANCEL_WORDS)


def _is_confirm(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in _CONFIRM_WORDS)


def _cancelled_response(tts_msg: str = "Order cancelled. Let me know if you need anything else.") -> dict:
    return {
        "reply": tts_msg,
        "plan": {}, "skill_result": None,
        "needs_confirmation": False, "tts_audio": None,
        "skill_type": "food_grocery",
        "_clear_food_state": True,
    }


# ─────────────────────────────────────────────────────────────────────────────
# State machine handlers
# ─────────────────────────────────────────────────────────────────────────────

async def _handle_awaiting_selection(
    state: AppState,
    user_text: str,
    food_state: dict[str, Any],
) -> dict | None:
    """
    Intercept when food_order_state.step == "awaiting_selection".
    Returns a response dict, or None if text is not a valid selection/cancel.
    """
    if _is_cancel(user_text):
        return _cancelled_response()

    idx = _parse_index(user_text)
    if idx is None:
        # Not a number or ordinal — fall through to LLM
        return None

    results = food_state.get("results", [])
    if not results:
        # Check 'search_results' (newer schema)
        results = food_state.get("search_results", [])
    
    if not results:
        return None

    if idx < 0 or idx >= len(results):
        names = "\n".join(f"{i+1}. {r['name']}" for i, r in enumerate(results))
        return {
            "reply": f"Please pick a number between 1 and {len(results)}:\n{names}",
            "plan": {}, "skill_result": None,
            "needs_confirmation": False, "tts_audio": None,
            "skill_type": "food_grocery",
        }

    chosen = results[idx]
    platform_key = _platform_key_from_display(chosen.get("platform", "swiggy"))
    price_str = f"Rs.{chosen['price']:,.0f}" if chosen.get("price") else ""
    rating_str = f"⭐ {chosen['rating']}" if chosen.get("rating") else ""

    # Route add_to_cart through skill router (no LLM involved)
    try:
        cart_result = await state.router.route(
            "food_grocery",
            "add_to_cart",
            {
                "platform": platform_key,
                "item_id":  chosen.get("id", ""),
                "item_name": chosen["name"],
                "item_url": chosen.get("url", ""),
                "quantity": 1,
                "url": chosen.get("url", ""),
            },
            user_confirmed=True,
            user_text=user_text,
        )
        cart_ok = cart_result.get("ok", False)
        cart_msg = (cart_result.get("result") or {}).get("message", "")
    except Exception as exc:
        logger.warning("add_to_cart via router failed: %s", exc)
        cart_ok = False
        cart_msg = str(exc)

    if cart_ok:
        msg = (
            f"Added **{chosen['name']}** {price_str} {rating_str} "
            f"from {chosen.get('platform', 'Swiggy')} to your cart.\n\n"
            f"Ready to place the order? Say **'yes'** to proceed or **'cancel'** to stop."
        )
    else:
        # Cart failed — still let user proceed manually
        msg = (
            f"I couldn't add **{chosen['name']}** automatically ({cart_msg or 'selector failed'}).\n"
            f"I'll open the page so you can add it manually.\n\n"
            f"Say **'yes'** to open checkout or **'cancel'** to stop."
        )

    # Return state update for persistence
    state_update = {
        "step": "awaiting_confirmation",
        "selected_item": chosen,
        "platform": platform_key,
        "query": food_state.get("query", ""),
    }

    return {
        "reply": msg,
        "plan": {}, "skill_result": None,
        "needs_confirmation": True,
        "tts_audio": None,
        "skill_type": "food_grocery",
        "food_state_update": state_update,
        "data": {
            "chosen_item": chosen,
            "platform": platform_key,
        },
    }


async def _handle_awaiting_confirmation(
    state: AppState,
    user_text: str,
    food_state: dict[str, Any],
) -> dict | None:
    """
    Intercept when food_order_state.step == "awaiting_confirmation".
    Returns response dict, or None if ambiguous.
    """
    if _is_cancel(user_text):
        return _cancelled_response()

    if not _is_confirm(user_text):
        # Ambiguous — return a reprompt, don't fall through to LLM
        chosen = food_state.get("selected_item", {})
        return {
            "reply": (
                f"Just checking — do you want to place the order for "
                f"**{chosen.get('name', 'your item')}**? Say **'yes'** or **'cancel'**."
            ),
            "plan": {}, "skill_result": None,
            "needs_confirmation": True, "tts_audio": None,
            "skill_type": "food_grocery",
        }

    # User confirmed — go to checkout
    chosen = food_state.get("selected_item", {})
    platform_key = food_state.get("platform", "swiggy")
    display = platform_key.title() # Simplistic fallback

    try:
        order_result = await state.router.route(
            "food_grocery",
            "place_order",
            {
                "platform": platform_key,
                "user_confirmed": True,
                "item_name": chosen.get("name", ""),
                "item_url": chosen.get("url", ""),
                "url": chosen.get("url", ""),
            },
            user_confirmed=True,
            user_text=user_text,
        )
        res_data = order_result.get("result") or {}
        checkout_url = res_data.get("checkout_url") or chosen.get("url", "https://www.google.com")
        reply_msg = res_data.get("message") or f"Great! I've placed your order on {display}."
    except Exception as exc:
        logger.warning("place_order via router failed: %s", exc)
        checkout_url = chosen.get("url", "https://www.google.com")
        reply_msg = f"I've initiated your order on {display}. Please complete payment in the browser window."

    # Open checkout in system browser as safety fallback
    try:
        import webbrowser
        webbrowser.open(checkout_url)
    except Exception:
        pass

    return {
        "reply": reply_msg,
        "plan": {}, 
        "skill_result": None,
        "needs_confirmation": False, 
        "tts_audio": None,
        "skill_type": "food_grocery",
        "_clear_food_state": True,
    }


async def _handle_asking_location(
    state: AppState,
    user_text: str,
) -> dict | None:
    """
    When step == 'asking_location', user is typing their city.
    Store it and retry the original smart_order search.
    """
    city = user_text.strip().strip(".,!?")
    if len(city) < 2:
        return {
            "reply": "Please enter a valid city name (e.g. 'Bangalore', 'Mumbai').",
            "plan": {}, "skill_result": None,
            "needs_confirmation": False, "tts_audio": None,
            "skill_type": "food_grocery",
        }

    state.user_location = {"city": city, "lat": None, "lng": None}
    original_query = state.food_order_state.get("query", "food")
    state.food_order_state = {}  # Clear asking_location step

    # Re-route the original smart_order with the new location
    try:
        exec_res = await state.router.route(
            "food_grocery",
            "smart_order",
            {
                "query": original_query,
                "city": city,
            },
            user_confirmed=False,
            user_text=user_text,
        )
        if exec_res.get("ok"):
            result_data = exec_res.get("result", {}).get("data", {})
            if result_data.get("search_results"):
                state.food_order_state = {
                    "step": "awaiting_selection",
                    "results": result_data["search_results"],
                    "query": original_query,
                }
            reply = exec_res.get("result", {}).get("message") or f"Here are results for '{original_query}'!"
        else:
            reply = exec_res.get("error") or f"Search failed for '{original_query}' in {city}."
    except Exception as exc:
        logger.error("Retry smart_order after location failed: %s", exc)
        reply = f"Searching for '{original_query}' in {city}. Please try again in a moment."

    tts = await speak_to_bytes(reply)
    return {
        "reply": reply,
        "plan": {}, "skill_result": exec_res if "exec_res" in dir() else None,
        "needs_confirmation": False, "tts_audio": tts,
        "skill_type": "food_grocery",
    }


def _platform_key_from_display(display: str) -> str:
    """Convert 'Swiggy' → 'swiggy', 'Zomato' → 'zomato', etc."""
    mapping = {
        "swiggy": "swiggy",
        "zomato": "zomato",
        "blinkit": "blinkit",
        "zepto": "zepto",
    }
    return mapping.get(display.lower(), "swiggy")


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

async def run_text_pipeline(
    state: AppState,
    user_text: str,
    *,
    context: str | None = None,
    user_confirmed: bool = False,
    skip_skill: bool = False,
    session_id: str = "default",
) -> dict[str, Any]:
    """Plan with LLM (or state machine), optionally execute skill, update memory."""
    await state.sqlite.log_command(user_text, None, None)

    # ── SESSION STATE: load from SQLite ────────────────────────────────────
    session = await state.sqlite.get_active_order_session(session_id)
    food_state = session.get("state", {}) if session else {}
    step = food_state.get("step", "")

    # ── STATE MACHINE: intercept BEFORE LLM ────────────────────────────────
    if step == "awaiting_selection":
        # Pass a context mock that includes results for the state machine logic
        context_data = {"session_id": session_id, "food_order_state": food_state}
        result = await _handle_awaiting_selection(state, user_text, food_state)
        if result is not None:
            if result.pop("_clear_food_state", False):
                await state.sqlite.clear_order_session(session_id)
            elif result.get("food_state_update"):
                # Update persistent state
                new_state = {**food_state, **result.pop("food_state_update")}
                await state.sqlite.save_order_session(session_id, None, None, new_state)
            
            if not result.get("tts_audio") and result.get("reply"):
                result["tts_audio"] = await speak_to_bytes(result["reply"])
            return result

    elif step == "awaiting_confirmation":
        result = await _handle_awaiting_confirmation(state, user_text, food_state)
        if result is not None:
            if result.pop("_clear_food_state", False):
                await state.sqlite.clear_order_session(session_id)
            if not result.get("tts_audio") and result.get("reply"):
                result["tts_audio"] = await speak_to_bytes(result["reply"])
            return result

    elif step == "asking_location":
        result = await _handle_asking_location(state, user_text)
        if result is not None:
            return result

    # ── LLM PLANNING ────────────────────────────────────────────────────────
    if skip_skill:
        plan = {
            "skill": "memory_skill",
            "action": "recall_context",
            "parameters": {"query": user_text},
            "reply_text": user_text,
            "needs_skill": False,
        }
    else:
        plan = await llm.plan_intent(user_text, context=context, settings=state.settings)
        logger.info("LLM Plan: %s", plan)

    reply = plan.get("reply_text") or ""
    skill_result: dict[str, Any] | None = None
    skill_type: str | None = None

    if plan.get("needs_skill", True) and plan.get("skill"):
        exec_res = await state.router.route(
            plan["skill"],
            plan.get("action") or "default",
            plan.get("parameters") or {},
            user_confirmed=user_confirmed,
            user_text=user_text,
            context={
                "session_id": session_id,
                "user_location": state.user_location,
            },
        )
        skill_result = exec_res
        logger.info("Skill result keys: %s", list(exec_res.keys()))

        if exec_res.get("needs_confirmation"):
            return {
                "reply": exec_res.get("message", "Confirmation required."),
                "plan": plan,
                "skill_result": skill_result,
                "needs_confirmation": True,
                "pending_skill": plan.get("skill"),
                "pending_action": plan.get("action"),
                "pending_parameters": plan.get("parameters") or {},
                "skill_type": "confirmation",
            }

        if exec_res.get("ok"):
            r = exec_res.get("result", {})
            if isinstance(r, dict):
                skill_reply = r.get("summary_text") or r.get("message")
                if skill_reply:
                    reply = str(skill_reply)
                skill_type = r.get("skill_type")

                # ── Food ordering: store results in state ─────────────────
                if (
                    plan.get("skill") == "food_grocery"
                    and plan.get("action") == "smart_order"
                ):
                    data = r.get("data", {})
                    search_results = data.get("search_results", [])
                    needs_location = data.get("needs_location", False)

                    if search_results:
                        state.food_order_state = {
                            "step": "awaiting_selection",
                            "results": search_results,
                            "query": data.get("query", ""),
                            "platform": data.get("platform", "swiggy"),
                        }
                        logger.info(
                            "Food state → awaiting_selection (%d results)",
                            len(search_results),
                        )
                    elif needs_location:
                        state.food_order_state = {
                            "step": "asking_location",
                            "query": plan.get("parameters", {}).get("query", "food"),
                        }
                        logger.info("Food state → asking_location")

            elif isinstance(r, str):
                reply = r
        else:
            err = exec_res.get("error") or "Unknown error"
            reply = f"I could not complete that: {err}"

    # Fallback skill_type from plan
    if not skill_type and plan.get("skill"):
        skill_type = plan.get("skill")

    # Vector memory: store interaction snippet
    try:
        snippet = f"User: {user_text}\nAssistant: {reply}"
        state.chroma.add_text(snippet, metadata={"type": "turn"})
    except Exception as e:
        logger.debug("Chroma add skipped: %s", e)

    await state.sqlite.log_command(user_text, plan.get("skill"), plan.get("action"))

    tts_audio = await speak_to_bytes(reply or "Done.")

    return {
        "reply": reply or "Done.",
        "plan": plan,
        "skill_result": skill_result,
        "needs_confirmation": False,
        "tts_audio": tts_audio,
        "skill_type": skill_type,
    }


async def run_voice_pipeline(
    state: AppState,
    audio_bytes: bytes,
    *,
    user_confirmed: bool = False,
) -> dict[str, Any]:
    settings: Settings = state.settings
    text = await transcribe_upload_bytes(audio_bytes, settings)
    # Voice pipeline uses a random session ID if not specified
    out = await run_text_pipeline(state, text, user_confirmed=user_confirmed, session_id="voice_" + str(uuid.uuid4())[:8])
    out["transcript"] = text
    if not out.get("tts_audio"):
        out["tts_audio"] = await speak_to_bytes(out["reply"])
    return out
