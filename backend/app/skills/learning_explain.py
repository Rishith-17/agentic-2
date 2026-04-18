"""Learning: explain a concept using Wikipedia and the local LLM."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "JarvisAssistant/1.0 (https://github.com/jarvis-assistant; "
        "educational use) python-requests/2.x"
    )
}

# ── Wikipedia helper ──────────────────────────────────────────────────────────

def _fetch_wikipedia(concept: str) -> dict[str, Any] | None:
    """
    Call the Wikipedia REST summary API.
    Returns {'title', 'summary', 'url'} or None on failure.
    """
    try:
        import requests

        # Try exact title first, then a search fallback
        slug = quote(concept.replace(" ", "_"))
        url  = f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}"
        resp = requests.get(url, headers=_HEADERS, timeout=10)

        if resp.status_code == 404:
            # Search for the closest article
            search_url = "https://en.wikipedia.org/w/api.php"
            s_resp = requests.get(
                search_url,
                params={
                    "action": "query",
                    "list":   "search",
                    "srsearch": concept,
                    "format": "json",
                    "srlimit": 1,
                },
                headers=_HEADERS,
                timeout=10,
            )
            s_resp.raise_for_status()
            hits = s_resp.json().get("query", {}).get("search", [])
            if not hits:
                return None
            best_title = hits[0]["title"]
            slug       = quote(best_title.replace(" ", "_"))
            resp       = requests.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}",
                headers=_HEADERS,
                timeout=10,
            )

        resp.raise_for_status()
        data    = resp.json()
        summary = data.get("extract") or data.get("description") or ""
        if not summary:
            return None
        return {
            "title":   data.get("title", concept),
            "summary": summary,
            "url":     data.get("content_urls", {}).get("desktop", {}).get("page", ""),
        }
    except Exception as exc:
        logger.warning("Wikipedia fetch failed for '%s': %s", concept, exc)
        return None


# ── Skill ─────────────────────────────────────────────────────────────────────

from app.skills.base import SkillBase   # noqa: E402
from app.services import llm as llm_service  # noqa: E402


class LearningExplainSkill(SkillBase):
    """Explain a concept using Wikipedia and the local LLM."""

    name        = "learning_explain"
    description = "Explain any concept simply using Wikipedia and the local LLM."
    priority    = 5
    keywords    = [
        "explain", "what is", "define", "definition", "concept",
        "meaning", "describe", "tell me about", "how does",
    ]

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action":  {"type": "string", "enum": ["explain"]},
                "concept": {"type": "string"},
            },
            "required": ["action", "concept"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        if action != "explain":
            return {"message": f"Unknown action: {action}"}

        concept = (parameters.get("concept") or "").strip()
        if not concept:
            return {"message": "Please provide a concept to explain."}

        # 1. Try Wikipedia (non-blocking)
        loop    = asyncio.get_event_loop()
        wiki    = await loop.run_in_executor(None, _fetch_wikipedia, concept)

        if wiki:
            summary = wiki["summary"]
            # If the Wikipedia extract is very long or jargon-heavy, simplify with LLM
            if len(summary) > 600 or _is_too_technical(summary):
                simplified = await _llm_simplify(concept, summary)
                explanation = simplified or summary[:600]
            else:
                explanation = summary

            source_note = f"\n\n📖 Source: {wiki['url']}" if wiki.get("url") else ""
            msg = f"**{wiki['title']}**\n\n{explanation}{source_note}"
            return {
                "message":      msg,
                "summary_text": explanation[:300],
                "skill_type":   "learning",
                "data":         {"source": "wikipedia", "url": wiki.get("url", "")},
            }

        # 2. Fallback: pure LLM explanation
        llm_explanation = await _llm_simplify(concept, "")
        if llm_explanation:
            msg = f"**{concept}**\n\n{llm_explanation}"
            return {
                "message":      msg,
                "summary_text": llm_explanation[:300],
                "skill_type":   "learning",
                "data":         {"source": "llm"},
            }

        return {
            "message": (
                f"I couldn't find a clear explanation for '{concept}'. "
                "Try rephrasing or check Wikipedia directly."
            )
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_too_technical(text: str) -> bool:
    """Heuristic: flag text with many parenthetical citations or long sentences."""
    return text.count("(") > 4 or max((len(s) for s in text.split(". ")), default=0) > 200


async def _llm_simplify(concept: str, context: str) -> str:
    """Ask the LLM for a 2-3 sentence plain-English explanation."""
    try:
        ctx_part = f" Here is some background:\n{context[:1500]}" if context else ""
        prompt   = (
            f"Explain '{concept}' in 2-3 simple sentences that a high-school student "
            f"would understand.{ctx_part} Do not use jargon. Just give the explanation, no JSON."
        )
        plan = await llm_service.plan_intent(prompt)
        return (plan.get("reply_text") or "").strip()
    except Exception as exc:
        logger.warning("LLM simplify failed: %s", exc)
        return ""
