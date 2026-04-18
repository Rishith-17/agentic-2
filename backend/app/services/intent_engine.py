"""LLM-powered food intent classification engine.

Classifies free-form user input into structured food/grocery intents,
enriched with user memory context for personalised decisions.

Example:
    engine = FoodIntentEngine()
    intent = await engine.classify("order something light for dinner")
    # IntentResult(intent='food_order', category='light_meal',
    #              platform='swiggy', query='light dinner', confidence=0.91)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.services import llm as llm_service
from app.services.llm import _extract_json

logger = logging.getLogger(__name__)

# ── Intent taxonomy ───────────────────────────────────────────────────────────

FOOD_INTENTS = {
    "food_order":       "User wants to order food from a restaurant",
    "grocery_order":    "User wants to order groceries / household items",
    "view_cart":        "User wants to see their current cart",
    "place_order":      "User wants to confirm and place a pending order",
    "track_order":      "User wants to track an existing order",
    "recommendation":   "User wants a suggestion on what to eat/order",
    "surprise_me":      "User wants a random/surprise recommendation",
    "budget_order":     "User wants the cheapest available option",
    "diet_filter":      "User is filtering by dietary preference (veg/vegan/etc.)",
    "clarification":    "Input is too vague — need more information",
    "not_food":         "Input is not related to food or grocery",
}

MEAL_CATEGORIES = {
    "breakfast":   ["idli", "dosa", "poha", "upma", "paratha", "omelette", "toast", "cereal"],
    "lunch":       ["rice", "dal", "roti", "biryani", "thali", "curry", "sabzi"],
    "dinner":      ["pizza", "burger", "pasta", "noodles", "paneer", "chicken", "fish"],
    "snack":       ["samosa", "sandwich", "roll", "chips", "biscuit", "chai", "coffee"],
    "light_meal":  ["salad", "soup", "sandwich", "fruit", "yogurt", "smoothie"],
    "heavy_meal":  ["biryani", "thali", "pizza", "burger", "pasta", "fried rice"],
    "sweet":       ["ice cream", "cake", "mithai", "halwa", "kheer", "brownie"],
    "grocery":     ["milk", "bread", "eggs", "vegetables", "fruits", "rice", "dal"],
}

# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class IntentResult:
    intent:             str                  # one of FOOD_INTENTS keys
    category:           str                  # meal category or "grocery"
    platform:           str | None           # inferred platform or None
    query:              str                  # cleaned search query
    confidence:         float                # 0.0 – 1.0
    diet_filter:        str | None = None    # vegetarian | vegan | non-vegetarian
    budget_constraint:  str | None = None    # low | medium | high
    quantity:           int        = 1
    needs_clarification: bool      = False
    clarification_prompt: str      = ""
    raw_input:          str        = ""
    metadata:           dict[str, Any] = field(default_factory=dict)

    def to_food_grocery_params(self) -> dict[str, Any]:
        """Convert to parameters dict for FoodGrocerySkill.execute()."""
        action = {
            "food_order":    "search",
            "grocery_order": "search",
            "view_cart":     "view_cart",
            "place_order":   "place_order",
            "track_order":   "track_order",
            "recommendation": "search",
            "surprise_me":   "search",
            "budget_order":  "search",
            "diet_filter":   "search",
        }.get(self.intent, "search")

        return {
            "action":   action,
            "platform": self.platform,
            "query":    self.query,
            "quantity": self.quantity,
        }


# ── Prompt ────────────────────────────────────────────────────────────────────

def _build_classification_prompt(
    user_input: str,
    context: dict[str, Any],
    current_hour: int,
) -> str:
    meal_time = (
        "breakfast" if 5 <= current_hour < 11
        else "lunch" if 11 <= current_hour < 15
        else "snack" if 15 <= current_hour < 18
        else "dinner"
    )

    prefs    = context.get("preferences", {})
    top_items = [t["item"] for t in context.get("top_items", [])[:3]]
    diet     = prefs.get("diet", "any")
    budget   = prefs.get("budget_range", "medium")
    fav_plat = prefs.get("food_platform", "swiggy")
    groc_plat = prefs.get("grocery_platform", "blinkit")

    return f"""You are a food intent classifier for an AI assistant called Jarvis.

USER INPUT: "{user_input}"

CONTEXT:
- Current meal time: {meal_time}
- User diet preference: {diet}
- User budget: {budget}
- Preferred food platform: {fav_plat}
- Preferred grocery platform: {groc_plat}
- User's top ordered items: {top_items or ['unknown']}

VALID INTENTS: {list(FOOD_INTENTS.keys())}
VALID CATEGORIES: {list(MEAL_CATEGORIES.keys())}
VALID PLATFORMS: swiggy, zomato, blinkit, zepto

OUTPUT: ONE JSON object only, no markdown.
{{
  "intent": "<intent>",
  "category": "<category>",
  "platform": "<platform or null>",
  "query": "<cleaned search query, e.g. 'paneer pizza' or 'milk 1L'>",
  "confidence": <0.0-1.0>,
  "diet_filter": "<vegetarian|vegan|non-vegetarian|null>",
  "budget_constraint": "<low|medium|high|null>",
  "quantity": <integer, default 1>,
  "needs_clarification": <true|false>,
  "clarification_prompt": "<question to ask user if needs_clarification is true, else empty string>"
}}

RULES:
1. If input mentions "pizza", "burger", "biryani", "restaurant" → food_order, platform=swiggy or zomato
2. If input mentions "milk", "bread", "eggs", "vegetables", "grocery" → grocery_order, platform=blinkit or zepto
3. If input is vague like "order something" or "I'm hungry" → recommendation intent
4. If input says "surprise me" or "random" → surprise_me intent
5. If input mentions "cheap" or "budget" → budget_order intent
6. If input mentions "veg" or "vegetarian" → set diet_filter=vegetarian
7. Use user's preferred platform unless a specific one is mentioned
8. Set confidence based on how clear the intent is (vague=0.5, clear=0.9+)
9. If truly unclear, set needs_clarification=true and write a helpful clarification_prompt
"""


# ── Engine ────────────────────────────────────────────────────────────────────

class FoodIntentEngine:
    """
    LLM-powered intent classifier for food and grocery commands.

    Falls back to rule-based classification if the LLM is unavailable.
    """

    async def classify(
        self,
        user_input: str,
        context: dict[str, Any] | None = None,
    ) -> IntentResult:
        """
        Classify *user_input* into a structured IntentResult.

        Args:
            user_input: Raw user text
            context:    User memory snapshot from UserMemory.get_context_snapshot()

        Returns:
            IntentResult with all fields populated
        """
        context = context or {}
        now     = datetime.now()
        prompt  = _build_classification_prompt(user_input, context, now.hour)

        # Try LLM classification
        try:
            raw = await llm_service.chat(
                [{"role": "user", "content": prompt}],
                settings=get_settings(),
            )
            data = _extract_json(raw)
            result = self._parse_llm_result(data, user_input, context)
            logger.info(
                "Intent classified: '%s' -> %s (%.2f confidence)",
                user_input[:60], result.intent, result.confidence,
            )
            return result
        except Exception as exc:
            logger.warning("LLM classification failed (%s), using rule-based fallback", exc)
            return self._rule_based_classify(user_input, context)

    def _parse_llm_result(
        self,
        data: dict[str, Any],
        user_input: str,
        context: dict[str, Any],
    ) -> IntentResult:
        """Parse and validate the LLM JSON output into an IntentResult."""
        intent   = data.get("intent", "clarification")
        category = data.get("category", "")
        platform = data.get("platform") or None
        query    = (data.get("query") or user_input).strip()
        conf     = float(data.get("confidence", 0.5))

        # Validate intent
        if intent not in FOOD_INTENTS:
            intent = "clarification"
            conf   = 0.3

        # Validate platform
        valid_platforms = {"swiggy", "zomato", "blinkit", "zepto"}
        if platform and platform.lower() not in valid_platforms:
            platform = None

        # Apply user preference if platform not specified
        if platform is None and intent in ("food_order", "recommendation", "surprise_me", "budget_order"):
            prefs    = context.get("preferences", {})
            category_type = "grocery" if intent == "grocery_order" else "food"
            platform = prefs.get(
                "grocery_platform" if category_type == "grocery" else "food_platform",
                "swiggy",
            )

        return IntentResult(
            intent=intent,
            category=category,
            platform=platform,
            query=query,
            confidence=conf,
            diet_filter=data.get("diet_filter") or None,
            budget_constraint=data.get("budget_constraint") or None,
            quantity=int(data.get("quantity") or 1),
            needs_clarification=bool(data.get("needs_clarification", False)),
            clarification_prompt=data.get("clarification_prompt", ""),
            raw_input=user_input,
        )

    def _rule_based_classify(
        self,
        user_input: str,
        context: dict[str, Any],
    ) -> IntentResult:
        """
        Fast rule-based fallback when LLM is unavailable.
        Less accurate but always works offline.
        """
        text  = user_input.lower()
        prefs = context.get("preferences", {})

        # Detect intent
        if any(w in text for w in ["surprise", "random", "anything", "whatever"]):
            intent = "surprise_me"
        elif any(w in text for w in ["what should", "suggest", "recommend", "hungry", "what to eat"]):
            intent = "recommendation"
        elif any(w in text for w in ["cart", "basket"]):
            intent = "view_cart"
        elif any(w in text for w in ["place order", "confirm order", "checkout"]):
            intent = "place_order"
        elif any(w in text for w in ["track", "where is my order", "delivery status"]):
            intent = "track_order"
        elif any(w in text for w in ["cheap", "budget", "affordable", "low cost"]):
            intent = "budget_order"
        elif any(w in text for w in ["milk", "bread", "eggs", "vegetables", "grocery", "groceries", "rice", "dal", "atta"]):
            intent = "grocery_order"
        elif any(w in text for w in ["pizza", "burger", "biryani", "food", "eat", "order", "restaurant", "meal"]):
            intent = "food_order"
        else:
            intent = "clarification"

        # Detect category
        category = ""
        for cat, keywords in MEAL_CATEGORIES.items():
            if any(kw in text for kw in keywords):
                category = cat
                break

        # Detect platform
        platform = None
        for p in ["swiggy", "zomato", "blinkit", "zepto"]:
            if p in text:
                platform = p
                break
        if platform is None:
            platform = prefs.get(
                "grocery_platform" if intent == "grocery_order" else "food_platform",
                "swiggy",
            )

        # Diet filter
        diet_filter = None
        if any(w in text for w in ["veg", "vegetarian", "no meat", "no chicken"]):
            diet_filter = "vegetarian"
        elif any(w in text for w in ["vegan", "no dairy", "plant based"]):
            diet_filter = "vegan"
        elif any(w in text for w in ["non veg", "chicken", "mutton", "fish", "egg"]):
            diet_filter = "non-vegetarian"

        # Budget
        budget = None
        if any(w in text for w in ["cheap", "budget", "affordable", "low cost", "inexpensive"]):
            budget = "low"
        elif any(w in text for w in ["premium", "expensive", "best", "top"]):
            budget = "high"

        # Build query
        stop = {"order", "get", "me", "some", "a", "an", "the", "please", "jarvis", "from", "on"}
        words = [w for w in re.split(r"\W+", text) if w and w not in stop]
        query = " ".join(words[:5]) or user_input

        needs_clarification = intent == "clarification"
        clarification_prompt = (
            "What would you like to order? You can say something like 'pizza from Swiggy' or 'milk from Blinkit'."
            if needs_clarification else ""
        )

        return IntentResult(
            intent=intent,
            category=category,
            platform=platform,
            query=query,
            confidence=0.6,
            diet_filter=diet_filter,
            budget_constraint=budget,
            needs_clarification=needs_clarification,
            clarification_prompt=clarification_prompt,
            raw_input=user_input,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: FoodIntentEngine | None = None


def get_intent_engine() -> FoodIntentEngine:
    global _engine
    if _engine is None:
        _engine = FoodIntentEngine()
    return _engine
