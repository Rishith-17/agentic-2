"""Food & Grocery ordering skill — AI-enhanced with full conversational ordering.

Full ordering flow:
  1. User: "buy me biryani"
  2. Jarvis searches Swiggy + Zomato simultaneously
  3. Ranks by rating desc, price asc
  4. Shows top 5 options, asks user to pick
  5. User: "option 2" or "the second one"
  6. Jarvis adds to cart, shows order summary
  7. User: "confirm" / "yes"
  8. Jarvis navigates to checkout, returns summary
  9. User confirms payment manually

Actions: smart_order | search | add_to_cart | view_cart | place_order
         | track_order | recommend | surprise_me | set_preference
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from pathlib import Path
from typing import Any

import httpx

from app.services.food_live_search import build_food_platform_url, get_food_live_search
from app.services.mcp_client import MCPClient, MCPError, MCPServerError, MCPTimeoutError
from app.dependencies import get_sqlite_store
from app.skills.base import SkillBase
from app.skills.browser_agent import _open_url


# ── Location detection ────────────────────────────────────────────────────────

async def _detect_location(state_location: dict | None = None) -> dict | None:
    """
    Detect user location in priority order:
    1. Persistent active address from SqliteStore
    2. Stored in state_location (the current session)
    3. IP-based detection
    """
    store = get_sqlite_store()
    
    # 1. Check persistent store
    active_addr = await store.get_active_address()
    if active_addr:
        logger.info("Location from SqliteStore: %s (%s)", active_addr.get("label"), active_addr.get("city"))
        return {
            "city": active_addr.get("city"),
            "lat":  active_addr.get("lat"),
            "lng":  active_addr.get("lng"),
            "label": active_addr.get("label"),
        }

    # 2. Use stored location in current session state
    if state_location and state_location.get("city"):
        return state_location

    # 3. IP-based detection
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("https://ipapi.co/json/")
            if resp.status_code == 200:
                data = resp.json()
                city = data.get("city") or data.get("region") or ""
                lat  = float(data.get("latitude") or 0)
                lng  = float(data.get("longitude") or 0)
                if city and lat and lng:
                    loc = {"city": city, "lat": lat, "lng": lng}
                    logger.info("Location from IP: %s (%.4f, %.4f)", city, lat, lng)
                    return loc
    except Exception as exc:
        logger.warning("IP-based location detection failed: %s", exc)
    return None

logger = logging.getLogger(__name__)

# ── Platform configuration ────────────────────────────────────────────────────

PLATFORM_CONFIG: dict[str, dict[str, Any]] = {
    "swiggy": {
        "command": [sys.executable, str(Path(__file__).parent.parent.parent / "mcp_servers" / "swiggy_server.py")],
        "supported_actions": ["search", "add_to_cart", "view_cart", "place_order"],
        "category": "food",
        "display_name": "Swiggy",
        "automation_ready": True,
    },
    "zomato": {
        "command": [sys.executable, str(Path(__file__).parent.parent.parent / "mcp_servers" / "zomato_server.py")],
        "supported_actions": ["search", "add_to_cart", "view_cart", "place_order"],
        "category": "food",
        "display_name": "Zomato",
        "tool_mapping": {
            "search": "search_restaurants",
            "view_cart": "get_cart",
        },
    },
    "blinkit": {
        "command": [sys.executable, str(Path(__file__).parent.parent.parent / "mcp_servers" / "blinkit_server.py")],
        "supported_actions": ["search", "add_to_cart", "view_cart", "place_order"],
        "category": "grocery",
        "display_name": "Blinkit",
        "automation_ready": False,
        "tool_mapping": {
            "view_cart": "get_cart",
            "place_order": "checkout",
        },
    },
    "zepto": {
        "command": [sys.executable, str(Path(__file__).parent.parent.parent / "mcp_servers" / "zepto_server.py")],
        "supported_actions": ["search", "add_to_cart", "view_cart", "place_order"],
        "category": "grocery",
        "display_name": "Zepto",
        "automation_ready": True,
    },
}

# Keywords that suggest food vs grocery intent
_FOOD_KEYWORDS    = {"pizza", "burger", "biryani", "restaurant", "food", "meal", "dinner", "lunch", "breakfast", "sushi", "pasta", "noodles", "sandwich", "roll", "dosa", "idli"}
_GROCERY_KEYWORDS = {"milk", "bread", "eggs", "vegetables", "fruits", "grocery", "groceries", "rice", "dal", "oil", "sugar", "salt", "flour", "atta", "paneer", "butter", "curd"}

_QUERY_PREFIX_PATTERNS = [
    r"^\s*(please\s+)?(help\s+me\s+)?(buy|get|order)\s+",
    r"^\s*(please\s+)?(search\s+for|find)\s+",
    r"^\s*(i\s+want|i\s+need|show\s+me)\s+",
]


def _clean_order_query(query: str) -> str:
    cleaned = (query or "").strip()
    for pattern in _QUERY_PREFIX_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(on|from)\s+(swiggy|zomato|blinkit|zepto)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,!?\t\r\n")
    return cleaned or (query or "").strip()


# ── Input validation ──────────────────────────────────────────────────────────

class ValidationError(ValueError):
    """Raised when skill parameters fail validation."""


def _validate_action(action: str) -> None:
    valid = {
        "search", "add_to_cart", "view_cart", "place_order", "track_order",
        "recommend", "surprise_me", "set_preference", "smart_order",
        "login", "enter_otp",
    }
    if action not in valid:
        raise ValidationError(f"Unknown action '{action}'. Valid: {', '.join(sorted(valid))}")


def _validate_platform(platform: str) -> None:
    if platform not in PLATFORM_CONFIG:
        raise ValidationError(
            f"Unknown platform '{platform}'. "
            f"Supported: {', '.join(PLATFORM_CONFIG)}"
        )


def _validate_action_supported(platform: str, action: str) -> None:
    cfg = PLATFORM_CONFIG[platform]
    if action not in cfg["supported_actions"]:
        raise ValidationError(
            f"Platform '{platform}' does not support action '{action}'. "
            f"Supported: {', '.join(cfg['supported_actions'])}"
        )


# ── Platform inference ────────────────────────────────────────────────────────

def _infer_platforms(query: str, prefs: dict[str, Any] | None = None) -> list[str]:
    """
    Infer the best platforms for a query.
    Uses user preferences when available, falls back to keyword matching.
    """
    q     = query.lower()
    words = set(q.split())
    prefs = prefs or {}

    is_food    = bool(words & _FOOD_KEYWORDS)
    is_grocery = bool(words & _GROCERY_KEYWORDS)

    if is_food and not is_grocery:
        return ["swiggy", "zomato"]
    if is_grocery and not is_food:
        return ["blinkit", "zepto"]
    # Ambiguous — try both
    return ["swiggy", "zomato", "blinkit", "zepto"]


# ── Response normalisation ────────────────────────────────────────────────────

def _normalise_search_results(raw: dict[str, Any] | str, platform: str) -> list[dict[str, Any]]:
    """
    Normalise platform-specific search results into a common schema:
    [{"id", "name", "price", "rating", "eta", "url", "platform"}]
    """
    items: list[dict[str, Any]] = []
    display = PLATFORM_CONFIG[platform]["display_name"]

    candidates: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        candidates = (
            raw.get("results")
            or raw.get("items")
            or raw.get("restaurants")
            or raw.get("products")
            or []
        )
    elif isinstance(raw, str):
        for line in raw.splitlines():
            match = re.search(r"\[(\d+)\]\s+ID:\s*([^|]+)\|\s*(.+?)\s*-\s*([^\n]+)$", line.strip())
            if not match:
                continue
            price_match = re.search(r"(\d+(?:\.\d+)?)", match.group(4))
            candidates.append(
                {
                    "id": match.group(2).strip(),
                    "name": match.group(3).strip(),
                    "price": float(price_match.group(1)) if price_match else 0,
                    "rating": None,
                    "eta": None,
                    "url": "",
                }
            )

    for item in candidates:
        if not isinstance(item, dict):
            continue
        normalised = {
            "id":       item.get("id") or item.get("item_id") or item.get("restaurant_id") or "",
            "name":     item.get("name") or item.get("title") or item.get("restaurant_name") or "",
            "price":    item.get("price") or item.get("effective_price") or item.get("cost_for_two") or 0,
            "rating":   item.get("rating") or item.get("avg_rating") or None,
            "eta":      item.get("eta") or item.get("delivery_time") or None,
            "url":      item.get("url") or item.get("deep_link") or "",
            "platform": display,
            "_raw":     item,  # preserve original for debugging
        }
        if normalised["name"]:
            items.append(normalised)

    return items


def _normalise_cart(raw: dict[str, Any], platform: str) -> dict[str, Any]:
    """Normalise cart response into a common schema."""
    display = PLATFORM_CONFIG[platform]["display_name"]
    items = []
    for item in (raw.get("items") or raw.get("cart_items") or []):
        if isinstance(item, dict):
            items.append({
                "id":       item.get("id") or item.get("item_id") or "",
                "name":     item.get("name") or item.get("title") or "",
                "quantity": item.get("quantity") or 1,
                "price":    item.get("price") or item.get("effective_price") or 0,
            })
    return {
        "platform":    display,
        "items":       items,
        "total":       raw.get("total") or raw.get("bill_total") or raw.get("cart_total") or 0,
        "item_count":  len(items),
    }


def _format_search_message(results: list[dict[str, Any]], query: str, platform: str) -> str:
    if not results:
        return f"No results found for '{query}' on {PLATFORM_CONFIG[platform]['display_name']}."
    display = PLATFORM_CONFIG[platform]["display_name"]
    lines = [f"Found {len(results)} results for '{query}' on {display}:\n"]
    for i, r in enumerate(results[:5], 1):
        price_str = f"Rs.{r['price']}" if r["price"] else ""
        rating    = f" | {r['rating']} stars" if r["rating"] else ""
        eta       = f" | {r['eta']}" if r["eta"] else ""
        lines.append(f"{i}. {r['name']} {price_str}{rating}{eta}")
    return "\n".join(lines)


def _format_cart_message(cart: dict[str, Any]) -> str:
    if not cart["items"]:
        return f"Your {cart['platform']} cart is empty."
    lines = [f"Your {cart['platform']} cart ({cart['item_count']} items):\n"]
    for item in cart["items"]:
        lines.append(f"  - {item['name']} x{item['quantity']} — Rs.{item['price']}")
    lines.append(f"\nTotal: Rs.{cart['total']}")
    return "\n".join(lines)


# ── Skill ─────────────────────────────────────────────────────────────────────

class FoodGrocerySkill(SkillBase):
    """Order food and groceries from Swiggy, Zomato, Blinkit, and Zepto."""

    name        = "food_grocery"
    description = (
        "Order food and groceries from Swiggy, Zomato, Blinkit, and Zepto. "
        "Supports search, add to cart, view cart, and place order."
    )
    priority = 15
    keywords = [
        "order", "food", "grocery", "swiggy", "zomato", "blinkit", "zepto",
        "instamart", "buy", "pizza", "milk", "restaurant", "delivery",
        "burger", "biryani", "vegetables", "fruits", "groceries", "search",
    ]

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "smart_order",
                        "search", "add_to_cart", "view_cart",
                        "place_order", "track_order",
                        "recommend", "surprise_me", "set_preference",
                        "login", "enter_otp",
                    ],
                },
                "platform": {
                    "type": "string",
                    "enum": list(PLATFORM_CONFIG.keys()),
                    "description": "Target platform. Inferred from query if omitted.",
                },
                "query":       {"type": "string",  "description": "Search query or natural language command"},
                "item_id":     {"type": "string",  "description": "Item/product ID for cart operations"},
                "item_name":   {"type": "string",  "description": "Item name to add to cart"},
                "item_url":    {"type": "string",  "description": "Item URL from search results"},
                "choice":      {"type": "string",  "description": "User's choice from search results (e.g. '1', '2', 'first')"},
                "quantity":    {"type": "integer", "description": "Quantity to add (default 1)"},
                "order_id":    {"type": "string",  "description": "Order ID for tracking"},
                "pref_key":    {"type": "string",  "description": "Preference key to set"},
                "pref_val":    {"description":     "Preference value to set"},
                "phone_number": {"type": "string", "description": "Phone number for login (e.g. 9876543210)"},
                "otp":          {"type": "string", "description": "OTP code received on phone"},
            },
            "required": ["action"],
        }

    # ── Public entrypoint ─────────────────────────────────────────────────────

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Orchestrate food/grocery order flow."""
        incoming_context = context or {}
        # Lazy-init intelligence services
        from app.services.user_memory import get_user_memory
        from app.services.recommendation_engine import get_recommendation_engine

        memory = await get_user_memory()
        memory_context = await memory.get_context_snapshot()
        context = {**memory_context, **incoming_context}

        try:
            _validate_action(action)
        except ValidationError as exc:
            return {"message": str(exc), "success": False}

        platform = (parameters.get("platform") or "").strip().lower() or None
        query    = (parameters.get("query") or "").strip()
        item_id  = (parameters.get("item_id") or "").strip()
        quantity = int(parameters.get("quantity") or 1)
        order_id = (parameters.get("order_id") or "").strip()

        # ── Smart intent enrichment for search ────────────────────────────────
        # If we already have a clear query (e.g. from the new Lite Planner), 
        # bypass the redundant secondary LLM classification to save speed.
        if action == "search" and query and not platform:
            inferred = _infer_platforms(query, context.get("preferences"))
            if inferred:
                platform = inferred[0]
        # ── Route to handler ──────────────────────────────────────────────────
        if action == "smart_order":
            return await self._handle_smart_order(parameters, context)

        if action == "recommend":
            rec_engine = get_recommendation_engine()
            result = await rec_engine.recommend(
                context,
                diet_filter=parameters.get("diet_filter"),
                budget=parameters.get("budget"),
            )
            names = [s.item for s in result.suggestions]
            return {
                "message":    result.message,
                "summary_text": result.message,
                "success":    True,
                "skill_type": "food_grocery",
                "data": {
                    "suggestions": [
                        {"item": s.item, "platform": s.platform, "reason": s.reason}
                        for s in result.suggestions
                    ],
                    "meal_time":    result.meal_time,
                    "search_query": result.search_query,
                },
            }

        if action == "surprise_me":
            rec_engine = get_recommendation_engine()
            result = await rec_engine.recommend(context, surprise=True)
            return {
                "message":    result.message,
                "summary_text": result.message,
                "success":    True,
                "skill_type": "food_grocery",
                "data":       {"search_query": result.search_query},
            }

        if action == "set_preference":
            pref_key = (parameters.get("pref_key") or "").strip()
            pref_val = parameters.get("pref_val")
            if not pref_key or pref_val is None:
                return {"message": "Provide pref_key and pref_val to update preferences.", "success": False}
            await memory.set_preference(pref_key, pref_val)
            msg = f"Preference updated: {pref_key} = {pref_val}"
            return {"message": msg, "summary_text": msg, "success": True, "skill_type": "food_grocery"}

        if action == "search":
            result = await self._handle_search(platform, query, context)
            return result

        if action == "add_to_cart":
            return await self._handle_add_to_cart(
                platform,
                item_id,
                quantity,
                query,
                item_name=(parameters.get("item_name") or "").strip(),
                item_url=(parameters.get("item_url") or parameters.get("url") or "").strip(),
            )

        if action == "view_cart":
            return await self._handle_view_cart(platform)

        if action == "place_order":
            result = await self._handle_place_order(platform, parameters)
            # Learning loop: log successful order
            if result.get("success") and result.get("data", {}).get("order_id"):
                await memory.log_order(
                    item=query or "order",
                    platform=platform or "unknown",
                    success=True,
                )
            return result

        if action == "track_order":
            return await self._handle_track_order(platform, order_id)

        if action == "login":
            return await self._handle_login(platform, parameters.get("phone_number"))

        if action == "enter_otp":
            return await self._handle_enter_otp(platform, parameters.get("otp"))

        return {"message": f"Unhandled action: {action}", "success": False}

    # ── Smart order (full conversational flow) ────────────────────────────────

    async def _handle_smart_order(
        self,
        parameters: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Step 1: Detect location, search Swiggy + Zomato, rank, return top 5.
        The pipeline state machine handles steps 2 (selection) and 3 (confirmation).
        """
        query = (parameters.get("query") or "").strip()
        cleaned_query = _clean_order_query(query)
        if not query:
            return {
                "message": "What would you like to order? (e.g. 'biryani', 'pizza')",
                "success": False,
                "skill_type": "food_grocery",
                "needs_clarification": True,
            }

        # ── Detect location ───────────────────────────────────────────────────
        # Try to get stored state location (passed via context) or detect from IP
        stored_location = context.get("user_location")
        city_override   = (parameters.get("city") or "").strip()
        if city_override:
            stored_location = {"city": city_override, "lat": None, "lng": None}

        location = await _detect_location(stored_location)

        # Use an ID based on connection if available, else a static 'default'
        session_id = context.get("session_id", "default")

        if location is None:
            # Cannot detect location — ask the user
            logger.info("Location not detected — requesting from user")
            return {
                "message": (
                    "I need your location to find nearby restaurants. "
                    "Please tell me your city (e.g. 'Bangalore', 'Mumbai')."
                ),
                "summary_text": "What's your city? I need it to find nearby restaurants.",
                "success": True,
                "skill_type": "food_grocery",
                "data": {
                    "needs_location": True,
                    "query": query,
                    "step": "asking_location",
                },
            }

        lat = location.get("lat")
        lng = location.get("lng")
        city = location.get("city", "")
        logger.info("Smart order location: %s (lat=%s, lng=%s)", city, lat, lng)

        # ── Search Swiggy + Zomato concurrently ───────────────────────────────
        search_platforms = _infer_platforms(cleaned_query, context.get("preferences"))
        logger.info("Smart order: searching %s for '%s' near %s", search_platforms, cleaned_query, city)
        search_bundle = await get_food_live_search().search_many(
            cleaned_query,
            city=city or "Bengaluru",
            platforms=[p for p in search_platforms if p in {"zomato", "swiggy", "blinkit"}],
            max_results=5,
        )
        all_results: list[dict[str, Any]] = search_bundle.get("items", [])
        platform_errors: list[str] = search_bundle.get("errors", [])

        if not all_results:
            extra = f" Details: {'; '.join(platform_errors)}" if platform_errors else ""
            return {
                "message": (
                    f"Automation search could not find live results for '{cleaned_query}' near {city}. "
                    "Please verify login/session and delivery address, then retry."
                    + extra
                ),
                "summary_text": f"Automation search failed for '{cleaned_query}'.",
                "success": False,
                "skill_type": "food_grocery",
                "data": {
                    "query": cleaned_query,
                    "original_query": query,
                    "city": city,
                    "platforms_tried": search_platforms,
                    "errors": platform_errors,
                },
            }

        # Rank: rating desc, then price asc
        all_results.sort(
            key=lambda r: (-float(r.get("rating") or 0), float(r.get("price") or 9999))
        )
        top5 = all_results[:5]

        # Format the options list
        lines = [f"Here are the best '{cleaned_query}' options near {city}:\n"]
        for i, r in enumerate(top5, 1):
            rating_str = f"⭐ {r['rating']}" if r.get("rating") else ""
            price_str  = f"Rs.{r['price']:,.0f}" if r.get("price") else ""
            eta_str    = r.get("eta", "")
            platform   = r.get("platform", "")
            parts = [p for p in [price_str, rating_str, eta_str, platform] if p]
            lines.append(f"{i}. {r['name']}  ({' | '.join(parts)})")

        lines.append(
            "\nWhich one would you like? Say the number (e.g. '1', '2') "
            "or click SELECT on the card above."
        )
        msg = "\n".join(lines)

        # ── Save results to session state (SQLite) ───────────────────────────
        store = get_sqlite_store()
        session_state = {
            "search_results": top5,
            "query":          cleaned_query,
            "original_query": query,
            "city":           city,
            "step":           "awaiting_selection",
        }
        await store.save_order_session(session_id, None, query, session_state)

        return {
            "message":      msg,
            "summary_text": msg,
            "success":      True,
            "skill_type":   "food_grocery",
            "data":         session_state,
        }

    async def _safe_mcp_search(
        self,
        platform: str,
        query: str,
        loc_args: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Search a platform with optional location override; always return a structured result."""
        if not PLATFORM_CONFIG.get(platform, {}).get("automation_ready", True):
            logger.info("Skipping MCP search for %s because automation is not configured", platform)
            return {"results": [], "error": f"{PLATFORM_CONFIG[platform]['display_name']}: automation not configured"}
        try:
            args: dict[str, Any] = {"query": query}
            if loc_args and platform in {"swiggy", "zomato"}:
                args.update(loc_args)  # passes lat/lng to MCP server
            raw = await self._mcp_call(platform, "search", args)
            results = _normalise_search_results(raw, platform)
            logger.info("Smart order: %s returned %d results", platform, len(results))
            return {"results": results, "error": ""}
        except Exception as exc:
            logger.warning("Smart order: %s search failed: %s", platform, exc)
            return {"results": [], "error": f"{PLATFORM_CONFIG[platform]['display_name']}: {exc}"}

    async def _handle_choice_and_cart(
        self,
        choice: str,
        search_results: list[dict[str, Any]],
        quantity: int,
    ) -> dict[str, Any]:
        """Parse user's choice, add to cart, return order summary."""
        # Parse choice: "1", "option 2", "first", "second", "the third one"
        ordinals = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
                    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5}
        idx = None
        for word, num in ordinals.items():
            if word in choice:
                idx = num - 1
                break
        if idx is None:
            import re
            m = re.search(r"\d+", choice)
            if m:
                idx = int(m.group()) - 1

        if idx is None or idx < 0:
            # Try to fetch search results from session if not provided in parameters
            if not search_results:
                store = get_sqlite_store()
                session = await store.get_active_order_session("default")
                if session and session.get("state"):
                    search_results = session["state"].get("search_results", [])
            
            if not search_results or idx is None or idx >= len(search_results):
                msg = "I didn't catch which one. Please say a number"
                if search_results:
                    names = [f"{i+1}. {r['name']}" for i, r in enumerate(search_results)]
                    msg += ":\n" + "\n".join(names)
                else:
                    msg += " or click SELECT on a card."
                
                return {
                    "message":    msg,
                    "success":    False,
                    "skill_type": "food_grocery",
                }

        chosen = search_results[idx]
        platform_key = next(
            (k for k, v in PLATFORM_CONFIG.items()
             if v["display_name"].lower() == chosen.get("platform", "").lower()),
            "swiggy",
        )

        # Add to cart
        try:
            cart_result = await self._mcp_call(
                platform_key,
                "add_to_cart",
                {
                    "url":       chosen.get("url", ""),
                    "item_name": chosen["name"],
                    "quantity":  quantity,
                },
            )
        except MCPError as exc:
            return {
                "message": f"Could not add to cart: {exc}",
                "success": False,
                "skill_type": "food_grocery",
            }

        display = PLATFORM_CONFIG[platform_key]["display_name"]
        price_str = f"Rs.{chosen['price']:,.0f}" if chosen.get("price") else ""
        msg = (
            f"Added '{chosen['name']}' ({price_str}) from {display} to your cart.\n\n"
            f"Ready to place the order? Say 'confirm' or 'yes' to proceed, "
            f"or 'cancel' to stop."
        )
        return {
            "message":      msg,
            "summary_text": msg,
            "success":      True,
            "skill_type":   "food_grocery",
            "needs_confirmation": True,
            "data": {
                "chosen_item": chosen,
                "platform":    platform_key,
                "cart_result": cart_result,
                "next_action": "smart_order",
                "next_params": {
                    "action":         "smart_order",
                    "platform":       platform_key,
                    "query":          chosen["name"],
                    "user_confirmed": True,
                },
            },
        }

    # ── Action handlers ───────────────────────────────────────────────────────

    async def _handle_search(
        self,
        platform: str | None,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Search for items/restaurants. Adds conversational context from memory."""
        if not query:
            return {"message": "Please provide a search query.", "success": False}
        query = _clean_order_query(query)

        context = context or {}
        prefs   = context.get("preferences", {})
        top_items = [t["item"] for t in context.get("top_items", [])[:3]]

        # Conversational: check if this matches a favourite
        usual_match = next(
            (t for t in top_items if t.lower() in query.lower() or query.lower() in t.lower()),
            None,
        )
        if usual_match and platform:
            display = PLATFORM_CONFIG.get(platform, {}).get("display_name", platform)
            logger.info("Matched usual order: '%s' on %s", usual_match, display)

        platforms = [platform] if platform else [p for p in _infer_platforms(query) if p in {"zomato", "swiggy", "blinkit"}]
        city = (context.get("user_location") or {}).get("city") or "Bengaluru"
        search_bundle = await get_food_live_search().search_many(
            query,
            city=city,
            platforms=platforms,
            max_results=6,
        )
        all_results: list[dict[str, Any]] = search_bundle.get("items", [])
        errors: list[str] = search_bundle.get("errors", [])

        if not all_results:
            msg = (
                f"Could not fetch automated results for '{query}'. "
                + (f"Errors: {'; '.join(errors)}" if errors else "Check login/session and retry.")
            )
            return {
                "message": msg,
                "summary_text": msg,
                "success": False,
                "skill_type": "food_grocery",
                "data": {"query": query, "platforms_tried": platforms, "errors": errors},
            }

        used_platform = all_results[0]["platform"].lower() if all_results else (platform or platforms[0])
        # Map display name back to key
        used_key = next(
            (k for k, v in PLATFORM_CONFIG.items() if v["display_name"].lower() == used_platform.lower()),
            platform or platforms[0],
        )
        msg = _format_search_message(all_results, query, used_key)
        return {
            "message":    msg,
            "summary_text": msg,
            "success":    True,
            "skill_type": "food_grocery",
            "data": {
                "results":  all_results,
                "query":    query,
                "platform": used_key,
            },
        }

    async def _handle_add_to_cart(
        self,
        platform: str | None,
        item_id: str,
        quantity: int,
        query: str,
        item_name: str = "",
        item_url: str = "",
    ) -> dict[str, Any]:
        """Add an item to the cart on the specified platform."""
        if not item_id and not item_name:
            return {
                "message": "Please provide an item_id or item_name to add to cart.",
                "success": False,
            }
        if not platform:
            return {
                "message": "Please specify a platform (swiggy, zomato, blinkit, zepto) "
                           "when adding to cart.",
                "success": False,
            }

        try:
            _validate_platform(platform)
            _validate_action_supported(platform, "add_to_cart")
        except ValidationError as exc:
            return {"message": str(exc), "success": False}

        display = PLATFORM_CONFIG[platform]["display_name"]
        target_name = item_name or item_id or query or "that item"
        target_url = build_food_platform_url(platform, target_name, item_url=item_url)
        return {
            "message": (
                f"{display} is ready for manual cart handoff. "
                f"Say yes and I'll open {display} for {target_name}."
            ),
            "summary_text": f"{display} handoff ready for {target_name}.",
            "success": False,
            "skill_type": "food_grocery",
            "data": {
                "platform": platform,
                "item_name": target_name,
                "quantity": quantity,
                "checkout_url": target_url,
                "manual_handoff": True,
            },
        }

    async def _handle_view_cart(self, platform: str | None) -> dict[str, Any]:
        """View the current cart on the specified platform."""
        if not platform:
            return {
                "message": "Please specify a platform to view your cart.",
                "success": False,
            }

        try:
            _validate_platform(platform)
            _validate_action_supported(platform, "view_cart")
        except ValidationError as exc:
            return {"message": str(exc), "success": False}

        try:
            raw  = await self._mcp_call(platform, "view_cart", {})
            cart = _normalise_cart(raw, platform)
            msg  = _format_cart_message(cart)
            return {
                "message":    msg,
                "summary_text": msg,
                "success":    True,
                "skill_type": "food_grocery",
                "data":       cart,
            }
        except MCPError as exc:
            logger.error("view_cart failed on %s: %s", platform, exc)
            return {
                "message": f"Could not fetch cart: {exc}",
                "success": False,
            }

    async def _handle_place_order(
        self,
        platform: str | None,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Place an order — two-phase flow:
          Phase 1 (user_confirmed=False): return confirmation request with cart summary.
          Phase 2 (user_confirmed=True):  execute the order.
        """
        if not platform:
            return {
                "message": "Please specify a platform to place an order.",
                "success": False,
            }

        try:
            _validate_platform(platform)
            _validate_action_supported(platform, "place_order")
        except ValidationError as exc:
            return {"message": str(exc), "success": False}

        user_confirmed = bool(parameters.get("user_confirmed") or parameters.get("confirmed"))

        # Phase 1: show cart and ask for confirmation
        if not user_confirmed:
            try:
                raw  = await self._mcp_call(platform, "view_cart", {})
                cart = _normalise_cart(raw, platform)
                cart_summary = _format_cart_message(cart)
            except MCPError:
                cart_summary = "(Could not fetch cart details)"

            display = PLATFORM_CONFIG[platform]["display_name"]
            msg = (
                f"Ready to place your {display} order.\n\n"
                f"{cart_summary}\n\n"
                "Send the same request with `user_confirmed: true` to confirm."
            )
            return {
                "message":          msg,
                "summary_text":     msg,
                "needs_confirmation": True,
                "skill_type":       "food_grocery",
                "success":          False,
            }

        # Phase 2: open the platform page for reliable manual checkout.
        display = PLATFORM_CONFIG[platform]["display_name"]
        item_name = (
            (parameters.get("item_name") or "").strip()
            or (parameters.get("query") or "").strip()
            or "your item"
        )
        item_url = (parameters.get("item_url") or parameters.get("url") or "").strip()
        city = (parameters.get("city") or "").strip() or "Bengaluru"
        checkout_url = build_food_platform_url(platform, item_name, city=city, item_url=item_url)
        opened = _open_url(checkout_url)
        msg = (
            f"Opened {display} for {item_name}. Complete cart review and payment in the browser."
            if opened else
            f"I prepared the {display} link for {item_name}. Open this in your browser: {checkout_url}"
        )
        return {
            "message": msg,
            "summary_text": msg,
            "success": True,
            "skill_type": "food_grocery",
            "data": {
                "platform": display,
                "checkout_url": checkout_url,
                "manual_handoff": True,
            },
        }

    async def _handle_login(self, platform: str | None, phone_number: str | None) -> dict[str, Any]:
        if not platform or not phone_number:
            return {"message": "Platform and phone_number required for login.", "success": False}
        try:
            raw = await self._mcp_call(platform, "login", {"phone_number": phone_number})
            return {"message": f"Login initiated on {platform}: {raw}", "success": True, "data": raw}
        except Exception as exc:
            return {"message": f"Login failed: {exc}", "success": False}

    async def _handle_enter_otp(self, platform: str | None, otp: str | None) -> dict[str, Any]:
        if not platform or not otp:
            return {"message": "Platform and otp required.", "success": False}
        try:
            raw = await self._mcp_call(platform, "enter_otp", {"otp": otp})
            return {"message": f"OTP verification on {platform}: {raw}", "success": True, "data": raw}
        except Exception as exc:
            return {"message": f"OTP failed: {exc}", "success": False}

    async def _handle_track_order(
        self,
        platform: str | None,
        order_id: str,
    ) -> dict[str, Any]:
        """Track an existing order (stub — real tracking requires auth tokens)."""
        if not platform or not order_id:
            return {
                "message": "Please provide both platform and order_id to track an order.",
                "success": False,
            }

        display = PLATFORM_CONFIG.get(platform, {}).get("display_name", platform)
        # Tracking requires authenticated sessions which MCP servers handle differently.
        # Return a deep-link to the platform's order tracking page as a practical fallback.
        tracking_urls = {
            "swiggy":  f"https://www.swiggy.com/order-tracking/{order_id}",
            "zomato":  f"https://www.zomato.com/order/{order_id}",
            "blinkit": f"https://blinkit.com/order/{order_id}",
            "zepto":   f"https://www.zeptonow.com/order/{order_id}",
        }
        url = tracking_urls.get(platform, "")
        msg = (
            f"Track your {display} order ({order_id}) here:\n{url}"
            if url else
            f"Order tracking for {display} is not yet available."
        )
        return {
            "message":    msg,
            "summary_text": msg,
            "success":    True,
            "skill_type": "food_grocery",
            "data":       {"order_id": order_id, "tracking_url": url},
        }

    # ── MCP call helper ───────────────────────────────────────────────────────

    async def _mcp_call(
        self,
        platform: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Spawn the platform's MCP server, call the tool, and return the result.
        Uses a longer timeout for food platforms since Playwright needs to launch
        Chromium and navigate the site.
        """
        cfg     = PLATFORM_CONFIG[platform]
        command = cfg["command"]

        # Food platforms need more time — Playwright + page load
        timeout = 90

        logger.info("MCP call: platform=%s tool=%s args=%s", platform, tool_name, arguments)

        try:
            # Apply platform-specific tool name mapping if defined
            actual_tool_name = cfg.get("tool_mapping", {}).get(tool_name, tool_name)
            
            async with MCPClient(command, timeout=timeout, max_retries=1) as client:
                return await client.call_tool(actual_tool_name, arguments, timeout=timeout)
        except MCPTimeoutError as exc:
            logger.warning("MCP timeout: platform=%s tool=%s", platform, tool_name)
            raise
        except MCPServerError as exc:
            if exc.code == 401 or "authorization" in str(exc).lower():
                # Detect Zomato Auth URL
                auth_data = exc.data or {}
                url = auth_data.get("url")
                if url:
                    return {
                        "message": (
                            "Zomato requires one-time authorization to search. "
                            "Please visit this link to log in: " + url
                        ),
                        "summary_text": "Zomato login required.",
                        "success": False,
                        "skill_type": "food_grocery",
                        "data": {"auth_url": url, "platform": "zomato"},
                        "needs_action": True,
                    }
            
            logger.error("MCP server error: platform=%s tool=%s code=%s msg=%s",
                         platform, tool_name, exc.code, exc)
            raise
        except MCPError as exc:
            # Check for common login messages in generic error text
            if "login" in str(exc).lower() or "authorize" in str(exc).lower():
                return {
                    "message": f"Login required for {platform.capitalize()}. Please check the automation window or log in manually.",
                    "success": False,
                    "skill_type": "food_grocery",
                    "needs_action": True,
                }
            logger.error("MCP error: platform=%s tool=%s error=%s", platform, tool_name, exc)
            raise





