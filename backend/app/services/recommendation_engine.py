"""Smart food recommendation engine.

Generates personalised food/grocery suggestions based on:
  - Time of day (breakfast / lunch / snack / dinner)
  - User's order history and favourite items
  - Dietary preferences and budget
  - LLM-generated creative suggestions when history is sparse

Usage:
    engine = RecommendationEngine()
    recs = await engine.recommend(context_snapshot, meal_time="dinner")
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.services import llm as llm_service
from app.services.intent_engine import MEAL_CATEGORIES

logger = logging.getLogger(__name__)

# ── Meal-time defaults (fallback when history is empty) ───────────────────────

_MEAL_DEFAULTS: dict[str, dict[str, list[str]]] = {
    "breakfast": {
        "vegetarian":     ["Masala dosa", "Idli sambar", "Poha", "Upma", "Aloo paratha", "Bread omelette"],
        "vegan":          ["Poha", "Upma", "Fruit bowl", "Oats porridge"],
        "non-vegetarian": ["Egg paratha", "Chicken sandwich", "Egg bhurji roll"],
        "any":            ["Masala dosa", "Idli sambar", "Poha", "Egg paratha", "Bread toast"],
    },
    "lunch": {
        "vegetarian":     ["Paneer butter masala", "Dal makhani", "Veg biryani", "Rajma chawal", "Chole bhature"],
        "vegan":          ["Dal tadka", "Veg biryani", "Rajma chawal", "Mixed veg curry"],
        "non-vegetarian": ["Chicken biryani", "Butter chicken", "Mutton curry", "Fish curry"],
        "any":            ["Chicken biryani", "Paneer butter masala", "Dal makhani", "Veg thali"],
    },
    "snack": {
        "vegetarian":     ["Samosa", "Veg sandwich", "Paneer roll", "Masala chai", "Bhel puri"],
        "vegan":          ["Fruit salad", "Roasted makhana", "Veg sandwich"],
        "non-vegetarian": ["Chicken roll", "Egg sandwich", "Chicken nuggets"],
        "any":            ["Samosa", "Chicken roll", "Veg sandwich", "Masala chai"],
    },
    "dinner": {
        "vegetarian":     ["Paneer tikka", "Veg pizza", "Pasta arrabbiata", "Palak paneer", "Veg burger"],
        "vegan":          ["Veg pizza", "Pasta primavera", "Tofu stir fry"],
        "non-vegetarian": ["Chicken pizza", "Butter chicken", "Grilled fish", "Chicken burger"],
        "any":            ["Pizza", "Burger", "Biryani", "Pasta", "Paneer tikka"],
    },
}

_BUDGET_FILTERS: dict[str, tuple[float, float]] = {
    "low":    (0,    300),
    "medium": (300,  800),
    "high":   (800, 9999),
}


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class Recommendation:
    item:        str
    platform:    str
    reason:      str
    confidence:  float
    diet_type:   str | None = None
    price_range: str | None = None
    is_favorite: bool       = False
    metadata:    dict[str, Any] = field(default_factory=dict)


@dataclass
class RecommendationResult:
    suggestions:  list[Recommendation]
    meal_time:    str
    message:      str
    search_query: str   # ready-to-use query for food_grocery search action


# ── Engine ────────────────────────────────────────────────────────────────────

class RecommendationEngine:
    """
    Generates personalised food/grocery recommendations.

    Strategy (in priority order):
    1. Favourite items that match the current meal time
    2. Frequently ordered items
    3. LLM-generated suggestions based on preferences
    4. Static meal-time defaults
    """

    async def recommend(
        self,
        context: dict[str, Any],
        *,
        meal_time: str | None = None,
        diet_filter: str | None = None,
        budget: str | None = None,
        count: int = 5,
        surprise: bool = False,
    ) -> RecommendationResult:
        """
        Generate *count* recommendations for the user.

        Args:
            context:     UserMemory.get_context_snapshot() output
            meal_time:   Override meal time (breakfast/lunch/snack/dinner)
            diet_filter: Override diet (vegetarian/vegan/non-vegetarian/any)
            budget:      Override budget (low/medium/high)
            count:       Number of suggestions to return
            surprise:    If True, randomise suggestions (ignore history)
        """
        prefs     = context.get("preferences", {})
        top_items = context.get("top_items", [])
        history   = context.get("recent_orders", [])

        # Resolve meal time
        if not meal_time:
            meal_time = _current_meal_time()

        # Resolve diet and budget from context if not overridden
        diet   = diet_filter or prefs.get("diet", "any")
        budget = budget or prefs.get("budget_range", "medium")

        # Preferred platforms
        food_platform  = prefs.get("food_platform", "swiggy")
        groc_platform  = prefs.get("grocery_platform", "blinkit")

        suggestions: list[Recommendation] = []

        if surprise:
            suggestions = self._surprise_recommendations(
                meal_time, diet, food_platform, count
            )
        else:
            # 1. Favourites
            favs = prefs.get("favorite_items", [])
            for fav in favs[:3]:
                suggestions.append(Recommendation(
                    item=fav,
                    platform=food_platform,
                    reason="Your favourite",
                    confidence=0.95,
                    diet_type=diet,
                    is_favorite=True,
                ))

            # 2. Frequently ordered
            for entry in top_items[:3]:
                item = entry["item"]
                if item not in [s.item for s in suggestions]:
                    suggestions.append(Recommendation(
                        item=item,
                        platform=entry.get("platform", food_platform),
                        reason=f"You've ordered this {entry['frequency']} times",
                        confidence=0.85,
                    ))

            # 3. LLM suggestions if we have room
            if len(suggestions) < count:
                llm_recs = await self._llm_suggestions(
                    meal_time, diet, budget, prefs, history, count - len(suggestions)
                )
                suggestions.extend(llm_recs)

            # 4. Static defaults as final fallback
            if len(suggestions) < count:
                defaults = self._default_suggestions(meal_time, diet, food_platform)
                for d in defaults:
                    if d.item not in [s.item for s in suggestions]:
                        suggestions.append(d)
                        if len(suggestions) >= count:
                            break

        suggestions = suggestions[:count]

        # Build a natural message
        names   = [s.item for s in suggestions]
        message = self._build_message(names, meal_time, diet)

        # Best search query = top suggestion
        search_query = suggestions[0].item if suggestions else meal_time

        return RecommendationResult(
            suggestions=suggestions,
            meal_time=meal_time,
            message=message,
            search_query=search_query,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _llm_suggestions(
        self,
        meal_time: str,
        diet: str,
        budget: str,
        prefs: dict[str, Any],
        history: list[dict[str, Any]],
        count: int,
    ) -> list[Recommendation]:
        """Ask the LLM for creative suggestions."""
        recent = [h["item"] for h in history[:5]]
        cuisine = prefs.get("preferred_cuisine", [])
        dislikes = prefs.get("disliked_items", [])

        prompt = (
            f"Suggest {count} {meal_time} food items for a user with these preferences:\n"
            f"- Diet: {diet}\n"
            f"- Budget: {budget}\n"
            f"- Preferred cuisine: {cuisine or 'any'}\n"
            f"- Disliked items: {dislikes or 'none'}\n"
            f"- Recently ordered: {recent or 'nothing yet'}\n\n"
            f"Return ONLY a JSON array of strings, e.g. [\"Paneer sandwich\", \"Masala dosa\"]. "
            f"No markdown, no explanation."
        )

        try:
            raw = await llm_service.chat(
                [{"role": "user", "content": prompt}],
                settings=get_settings(),
            )
            # Extract JSON array
            import json, re
            match = re.search(r"\[.*?\]", raw, re.DOTALL)
            if match:
                items = json.loads(match.group())
                platform = prefs.get("food_platform", "swiggy")
                return [
                    Recommendation(
                        item=str(item),
                        platform=platform,
                        reason="Recommended for you",
                        confidence=0.75,
                        diet_type=diet,
                    )
                    for item in items[:count]
                    if isinstance(item, str)
                ]
        except Exception as exc:
            logger.warning("LLM recommendation failed: %s", exc)

        return []

    def _default_suggestions(
        self,
        meal_time: str,
        diet: str,
        platform: str,
    ) -> list[Recommendation]:
        """Return static defaults for the given meal time and diet."""
        pool = _MEAL_DEFAULTS.get(meal_time, _MEAL_DEFAULTS["dinner"])
        items = pool.get(diet, pool.get("any", []))
        return [
            Recommendation(
                item=item,
                platform=platform,
                reason=f"Popular {meal_time} choice",
                confidence=0.6,
                diet_type=diet,
            )
            for item in items
        ]

    def _surprise_recommendations(
        self,
        meal_time: str,
        diet: str,
        platform: str,
        count: int,
    ) -> list[Recommendation]:
        """Return random suggestions from all meal categories."""
        all_items: list[str] = []
        for items in _MEAL_DEFAULTS.get(meal_time, _MEAL_DEFAULTS["dinner"]).values():
            all_items.extend(items)
        random.shuffle(all_items)
        return [
            Recommendation(
                item=item,
                platform=platform,
                reason="Surprise pick!",
                confidence=0.7,
                diet_type=diet,
            )
            for item in all_items[:count]
        ]

    def _build_message(self, names: list[str], meal_time: str, diet: str) -> str:
        if not names:
            return f"I couldn't find any {meal_time} suggestions right now."
        diet_note = f" ({diet})" if diet and diet != "any" else ""
        items_str = ", ".join(names[:3])
        if len(names) > 3:
            items_str += f", and {len(names) - 3} more"
        return (
            f"For {meal_time}{diet_note}, I'd suggest: {items_str}. "
            "Want me to search for any of these?"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _current_meal_time() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 11:
        return "breakfast"
    if 11 <= hour < 15:
        return "lunch"
    if 15 <= hour < 18:
        return "snack"
    return "dinner"


# ── Singleton ─────────────────────────────────────────────────────────────────

_rec_engine: RecommendationEngine | None = None


def get_recommendation_engine() -> RecommendationEngine:
    global _rec_engine
    if _rec_engine is None:
        _rec_engine = RecommendationEngine()
    return _rec_engine
