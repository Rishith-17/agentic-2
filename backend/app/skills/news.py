"""NewsAPI headlines and topic filters with optional LLM summary."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings
from app.services import llm
from app.skills.base import SkillBase


class NewsSkill(SkillBase):
    name = "news"
    description = "Latest headlines, topic filters, AI summarization."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["headlines", "topic_headlines", "summarize"]},
                "topic": {"type": "string", "description": "Used only for topic_headlines (e.g. technology, business)"},
                "country": {"type": "string", "description": "2-letter ISO country code. Recommend 'us' for general news."},
                "articles_text": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        s = get_settings()
        key = s.newsapi_key
        if not key and action != "summarize":
            return {"message": "Set NEWSAPI_KEY for live headlines"}

        base = "https://newsapi.org/v2"
        async with httpx.AsyncClient(timeout=30.0) as client:
            if action in ("headlines", "fetch", "get_news", "news"):
                country = parameters.get("country") or "us"
                r = await client.get(
                    f"{base}/top-headlines",
                    params={"country": country, "apiKey": key},
                )
                r.raise_for_status()
                d = r.json()
                arts = d.get("articles", [])[:8]
                
                # Fallback to 'us' if the suggested country returns 0 results
                if not arts and country != "us":
                    r = await client.get(
                        f"{base}/top-headlines",
                        params={"country": "us", "apiKey": key},
                    )
                    r.raise_for_status()
                    d = r.json()
                    arts = d.get("articles", [])[:8]
                    
                headlines = []
                for i, a in enumerate(arts, 1):
                    title = a.get("title", "").split(" - ")[0]
                    source = a.get("source", {}).get("name", "")
                    if title and "[Removed]" not in title:
                        headlines.append(f"{i}. {title}" + (f"  — {source}" if source else ""))
                if headlines:
                    msg = "Here's what's making headlines right now:\n\n" + "\n".join(headlines)
                else:
                    msg = "Couldn't find any headlines at the moment. Try again in a bit."
                return {"message": msg, "summary_text": msg, "articles": arts, "skill_type": "news"}

            if action == "topic_headlines":
                topic = (parameters.get("topic") or "technology").lower()
                q = {"technology": "technology OR AI", "ai": "artificial intelligence", "business": "business",
                     "sports": "sports", "science": "science", "health": "health",
                     "politics": "politics", "entertainment": "entertainment"}.get(topic, topic)
                r = await client.get(
                    f"{base}/everything",
                    params={"q": q, "sortBy": "publishedAt", "pageSize": 8, "language": "en", "apiKey": key},
                )
                r.raise_for_status()
                d = r.json()
                arts = d.get("articles", [])[:8]
                headlines = []
                for i, a in enumerate(arts, 1):
                    title = a.get("title", "").split(" - ")[0]
                    source = a.get("source", {}).get("name", "")
                    if title and "[Removed]" not in title:
                        headlines.append(f"{i}. {title}" + (f"  — {source}" if source else ""))
                if headlines:
                    msg = f"Here are the top {topic.title()} stories right now:\n\n" + "\n".join(headlines)
                else:
                    msg = f"No {topic} news found right now. Try again shortly."
                return {"message": msg, "summary_text": msg, "skill_type": "news"}

            if action == "summarize":
                blob = parameters.get("articles_text") or ""
                settings = get_settings()
                plan = await llm.plan_intent(
                    f"Summarize these news lines in 3 bullets:\n\n{blob[:8000]}",
                    settings=settings,
                )
                reply = plan.get("reply_text") or ""
                return {"summary_text": reply, "message": reply, "skill_type": "news"}

        return {"message": f"Unknown action {action}"}
