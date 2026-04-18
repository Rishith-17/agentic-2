"""Route LLM-structured actions to registered skills.

Scoring formula (used when the LLM names a skill that doesn't exist, or when
the caller explicitly requests re-scoring via resolve_skill()):

    score = (llm_match * 10) + (keyword_hits * 2) + skill.priority

The LLM match is binary (1 if the LLM named this skill, 0 otherwise).
Keyword hits count how many of the skill's keywords appear in the user text.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings
from app.core.safety import validate_execution_allowed
from app.core.skill_registry import SkillRegistry
from app.skills.base import SkillBase

logger = logging.getLogger(__name__)

# Minimum score a skill must reach to be considered a valid match.
# A skill named by the LLM always scores ≥10, so this only filters
# keyword-only matches that are too weak.
_MIN_SCORE = 2


def _score_skill(skill: SkillBase, llm_skill_name: str, user_text: str) -> int:
    """Return the intent-match score for *skill* given the LLM plan and user text."""
    text_lower = user_text.lower()

    llm_match   = 1 if skill.name == llm_skill_name else 0
    kw_hits     = sum(1 for kw in (skill.keywords or []) if kw.lower() in text_lower)
    priority    = getattr(skill, "priority", 0)

    # Boost browser_agent when search keywords are present
    search_boost = 0
    search_keywords = ["search", "google", "look up"]
    if skill.name == "browser_agent" and any(kw in text_lower for kw in search_keywords):
        search_boost = 5

    return (llm_match * 10) + (kw_hits * 2) + priority + search_boost


def resolve_skill(
    registry: SkillRegistry,
    llm_skill_name: str,
    user_text: str,
) -> SkillBase | None:
    """
    Return the best-matching skill for the given LLM plan + user text.

    1. If the LLM-named skill exists and scores above threshold, use it directly.
    2. Otherwise, score all skills and pick the highest scorer above _MIN_SCORE.
    3. If nothing scores high enough, return None.
    """
    # Fast path: LLM named a known skill
    direct = registry.get(llm_skill_name)
    if direct is not None:
        score = _score_skill(direct, llm_skill_name, user_text)
        if score >= _MIN_SCORE:
            logger.debug("Skill resolved (direct): %s score=%d", llm_skill_name, score)
            return direct

    # Full scoring pass
    best_skill: SkillBase | None = None
    best_score = _MIN_SCORE - 1

    for skill in registry._skills.values():
        s = _score_skill(skill, llm_skill_name, user_text)
        if s > best_score:
            best_score = s
            best_skill = skill

    if best_skill:
        logger.debug(
            "Skill resolved (scored): %s score=%d (LLM said '%s')",
            best_skill.name, best_score, llm_skill_name,
        )
    else:
        logger.warning(
            "No skill met minimum score for intent '%s' (user: %s)",
            llm_skill_name, user_text[:80],
        )

    return best_skill


class SkillRouter:
    def __init__(self, registry: SkillRegistry, settings: Settings) -> None:
        self._registry = registry
        self._settings = settings

    async def route(
        self,
        skill: str,
        action: str,
        parameters: dict[str, Any],
        *,
        user_confirmed: bool = False,
        user_text: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Resolve skill with intent scoring
        inst = resolve_skill(self._registry, skill, user_text or skill)
        if not inst:
            return {
                "ok": False,
                "error": (
                    f"I'm not sure how to handle that (skill '{skill}' not found "
                    "and no close match). Please rephrase your request."
                ),
            }

        allowed, msg = validate_execution_allowed(
            inst.name,
            action,
            parameters,
            user_confirmed=user_confirmed,
            require_confirmation=self._settings.require_confirmation_destructive,
        )
        if not allowed:
            return {"ok": False, "needs_confirmation": True, "message": msg}

        try:
            result = await inst.execute(action, parameters, context=context)
            if isinstance(result, dict):
                if result.get("error"):
                    return {"ok": False, "error": str(result.get("error")), "result": result}
                if result.get("success") is False:
                    return {
                        "ok": False,
                        "error": str(result.get("message") or "Skill reported failure"),
                        "result": result,
                        "needs_confirmation": bool(result.get("needs_confirmation", False)),
                        "message": result.get("message"),
                    }
            return {"ok": True, "result": result}
        except Exception as e:
            logger.exception("Skill execution failed: %s.%s", inst.name, action)
            return {"ok": False, "error": str(e)}
