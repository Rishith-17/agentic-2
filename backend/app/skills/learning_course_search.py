"""Learning: search for free courses on NPTEL, SWAYAM, Coursera, and YouTube."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Per-platform scrapers (all blocking — run in executor) ────────────────────

def _search_nptel(topic: str) -> list[dict[str, Any]]:
    results = []
    try:
        import requests
        from bs4 import BeautifulSoup

        url  = f"https://nptel.ac.in/courses?searchQuery={quote_plus(topic)}"
        resp = requests.get(url, headers=_HEADERS, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for card in soup.select(".course-card, .card, article")[:5]:
            title_el = card.select_one("h3, h4, .course-title, .title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            link_el = card.select_one("a")
            href    = link_el["href"] if link_el and link_el.get("href") else ""
            url_out = ("https://nptel.ac.in" + href) if href.startswith("/") else href
            results.append({
                "title":    title,
                "platform": "NPTEL",
                "url":      url_out or f"https://nptel.ac.in/courses?searchQuery={quote_plus(topic)}",
                "free":     True,
            })
    except Exception as exc:
        logger.warning("NPTEL search failed: %s", exc)
    return results


def _search_swayam(topic: str) -> list[dict[str, Any]]:
    results = []
    try:
        import requests
        from bs4 import BeautifulSoup

        url  = f"https://swayam.gov.in/explorer?search={quote_plus(topic)}"
        resp = requests.get(url, headers=_HEADERS, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for card in soup.select(".course-card, .card-body, .course-item")[:5]:
            title_el = card.select_one("h3, h4, .course-name, .title, strong")
            if not title_el:
                continue
            title   = title_el.get_text(strip=True)
            link_el = card.select_one("a")
            href    = link_el["href"] if link_el and link_el.get("href") else ""
            url_out = ("https://swayam.gov.in" + href) if href.startswith("/") else href
            results.append({
                "title":    title,
                "platform": "SWAYAM",
                "url":      url_out or f"https://swayam.gov.in/explorer?search={quote_plus(topic)}",
                "free":     True,
            })
    except Exception as exc:
        logger.warning("SWAYAM search failed: %s", exc)
    return results


def _search_coursera(topic: str) -> list[dict[str, Any]]:
    results = []
    try:
        import requests

        # Coursera public catalog API — no key required
        url  = "https://api.coursera.org/api/courses.v1"
        resp = requests.get(
            url,
            params={"q": "search", "query": topic, "limit": 5, "fields": "name,slug,description"},
            headers=_HEADERS,
            timeout=12,
        )
        resp.raise_for_status()
        data = resp.json()
        for course in data.get("elements", []):
            slug = course.get("slug", "")
            results.append({
                "title":    course.get("name", slug),
                "platform": "Coursera",
                "url":      f"https://www.coursera.org/learn/{slug}",
                "free":     False,  # audit available but not guaranteed free
            })
    except Exception as exc:
        logger.warning("Coursera search failed: %s", exc)
    return results


def _search_youtube(topic: str) -> list[dict[str, Any]]:
    results = []
    try:
        import yt_dlp  # type: ignore

        queries = [f"ytsearch3:NPTEL {topic} lecture", f"ytsearch3:{topic} full course tutorial"]
        seen: set[str] = set()
        for query in queries:
            ydl_opts = {
                "quiet":           True,
                "no_warnings":     True,
                "extract_flat":    True,
                "skip_download":   True,
                "playlistend":     3,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                for entry in (info.get("entries") or []):
                    vid_id = entry.get("id") or entry.get("url", "")
                    if vid_id in seen:
                        continue
                    seen.add(vid_id)
                    duration_s = entry.get("duration") or 0
                    duration   = f"{duration_s // 60}m" if duration_s else "?"
                    results.append({
                        "title":    entry.get("title", "YouTube Video"),
                        "platform": "YouTube",
                        "channel":  entry.get("uploader") or entry.get("channel", ""),
                        "url":      f"https://www.youtube.com/watch?v={vid_id}",
                        "duration": duration,
                        "free":     True,
                    })
            if len(results) >= 4:
                break
    except Exception as exc:
        logger.warning("YouTube search failed: %s", exc)
    return results


# ── Skill ─────────────────────────────────────────────────────────────────────

from app.skills.base import SkillBase  # noqa: E402
from app.services import llm as llm_service  # noqa: E402


class LearningCourseSearchSkill(SkillBase):
    """Find free courses on NPTEL, SWAYAM, Coursera, and YouTube."""

    name        = "learning_course_search"
    description = "Search for free courses on NPTEL, SWAYAM, Coursera, and YouTube."
    priority    = 6
    keywords    = [
        "course", "learn", "study", "class", "tutorial",
        "nptel", "swayam", "coursera", "youtube course",
        "free course", "online course",
    ]

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action":    {"type": "string", "enum": ["search"]},
                "topic":     {"type": "string"},
                "platforms": {
                    "type":  "array",
                    "items": {"type": "string", "enum": ["nptel", "swayam", "coursera", "youtube"]},
                },
            },
            "required": ["action", "topic"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        if action != "search":
            return {"message": f"Unknown action: {action}"}

        topic     = (parameters.get("topic") or "").strip()
        platforms = [p.lower() for p in (parameters.get("platforms") or [])]
        if not topic:
            return {"message": "Please provide a topic to search for courses."}

        # Soft dep check — missing packages reduce results but don't crash
        try:
            from app.utils.dep_check import require
            require("requests", "requests>=2.31.0")
        except ImportError as exc:
            msg = f"⚠️ {exc}"
            return {"message": msg, "summary_text": msg}

        all_platforms = {"nptel", "swayam", "coursera", "youtube"}
        active = set(platforms) & all_platforms if platforms else all_platforms

        loop = asyncio.get_event_loop()
        tasks = {}
        if "nptel"    in active: tasks["nptel"]    = loop.run_in_executor(None, _search_nptel,    topic)
        if "swayam"   in active: tasks["swayam"]   = loop.run_in_executor(None, _search_swayam,   topic)
        if "coursera" in active: tasks["coursera"] = loop.run_in_executor(None, _search_coursera, topic)
        if "youtube"  in active: tasks["youtube"]  = loop.run_in_executor(None, _search_youtube,  topic)

        gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
        all_results: list[dict[str, Any]] = []
        for res in gathered:
            if isinstance(res, list):
                all_results.extend(res)

        all_results = all_results[:10]

        if not all_results:
            msg = f"No courses found for '{topic}'. Try a different topic or check your internet connection."
            return {"message": msg, "summary_text": msg}

        # LLM summary of the best options
        resource_blob = "\n".join(
            f"- [{r['platform']}] {r['title']} — {r['url']}" for r in all_results
        )
        try:
            plan = await llm_service.plan_intent(
                f"Briefly summarise (2-3 sentences) the best free learning resources for '{topic}' "
                f"from this list:\n{resource_blob}\nJust give a natural summary, not JSON.",
            )
            summary = plan.get("reply_text") or f"Found {len(all_results)} courses for '{topic}'."
        except Exception:
            summary = f"Found {len(all_results)} courses for '{topic}'."

        lines = [f"• [{r['platform']}] {r['title']}\n  {r['url']}" for r in all_results]
        full_msg = summary + "\n\n" + "\n".join(lines)
        return {
            "message":      full_msg,
            "summary_text": summary,
            "skill_type":   "learning",
            "data":         {"courses": all_results},
        }
