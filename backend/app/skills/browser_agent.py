"""Browser automation via Playwright (sync API in thread pool) + webbrowser for display.

Root cause of the original NotImplementedError:
  playwright.async_api uses asyncio.create_subprocess_exec internally, which is not
  supported on Windows with the ProactorEventLoop inside uvicorn.

Fix: use playwright.sync_api (blocking) and run it in a ThreadPoolExecutor so the
async event loop is never blocked and subprocess creation works correctly.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import urllib.parse
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.skills.base import SkillBase

logger = logging.getLogger(__name__)

# Single shared executor for all Playwright work — keeps browser instances serialised
_PW_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="playwright")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
)


def _open_url(url: str) -> bool:
    """Open *url* in the user's browser with Windows-friendly fallbacks."""
    try:
        opened = webbrowser.open(url)
        if opened:
            return True
    except Exception as exc:
        logger.warning("webbrowser.open failed for %s: %s", url, exc)

    if sys.platform.startswith("win"):
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        except Exception as exc:
            logger.warning("os.startfile failed for %s: %s", url, exc)
        try:
            subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)
            return True
        except Exception as exc:
            logger.warning("cmd start failed for %s: %s", url, exc)
    return False


# ── Sync Playwright helpers (run inside _PW_EXECUTOR) ─────────────────────────

def _pw_google_results(q: str) -> list[dict]:
    """Scrape top Google search results for *q* and return [{title, url, snippet}]."""
    from playwright.sync_api import sync_playwright  # type: ignore

    search_url = "https://www.google.com/search?q=" + urllib.parse.quote(q)
    results: list[dict] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx     = browser.new_context(user_agent=_UA)
            page    = ctx.new_page()
            page.goto(search_url, wait_until="domcontentloaded", timeout=15000)

            # Each organic result is inside a div with data-hveid or class g
            for item in page.query_selector_all("div.g, div[data-hveid]")[:8]:
                try:
                    title_el   = item.query_selector("h3")
                    link_el    = item.query_selector("a[href]")
                    snippet_el = item.query_selector("div[data-sncf], span.aCOpRe, div.VwiC3b")

                    title   = title_el.inner_text().strip()   if title_el   else ""
                    href    = link_el.get_attribute("href")   if link_el    else ""
                    snippet = snippet_el.inner_text().strip() if snippet_el else ""

                    if title and href and href.startswith("http") and "google." not in href:
                        results.append({"title": title, "url": href, "snippet": snippet[:150]})
                except Exception:
                    continue

            browser.close()
    except Exception as exc:
        logger.error("_pw_google_results failed: %s", exc)
    return results[:5]


def _pw_open_website(q: str) -> str | None:
    """Return the first organic Google result URL for query *q*, or None."""
    from playwright.sync_api import sync_playwright  # type: ignore

    search_url = "https://www.google.com/search?q=" + urllib.parse.quote(q)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx     = browser.new_context(user_agent=_UA)
            page    = ctx.new_page()
            page.goto(search_url, wait_until="domcontentloaded", timeout=15000)

            target_url: str | None = None

            # Strategy 1: h3 → walk up to parent <a>
            for h3 in page.query_selector_all("h3")[:10]:
                el = h3
                for _ in range(4):
                    if el is None:
                        break
                    tag = el.evaluate("e => e.tagName")
                    if tag == "A":
                        href = el.get_attribute("href") or ""
                        if href.startswith("http") and "google.com" not in href:
                            target_url = href
                            break
                    el = el.evaluate_handle("e => e.parentElement")
                if target_url:
                    break

            # Strategy 2: #search links
            if not target_url:
                for link in page.query_selector_all("#search a")[:20]:
                    href = link.get_attribute("href") or ""
                    if (href.startswith("http")
                            and "google." not in href
                            and not any(x in href for x in ["/search?", "/maps", "/imgres"])):
                        target_url = href
                        break

            browser.close()
            return target_url
    except Exception as exc:
        logger.error("open_website playwright failed: %s", exc)
        return None


def _pw_youtube_play(q: str) -> str | None:
    """Return the first YouTube watch URL for query *q*, or None."""
    from playwright.sync_api import sync_playwright  # type: ignore

    search_url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(q)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx     = browser.new_context(user_agent=_UA)
            page    = ctx.new_page()
            page.goto(search_url, wait_until="domcontentloaded", timeout=15000)

            link_href: str | None = None
            for sel in ["a#video-title", "ytd-video-renderer a#thumbnail"]:
                try:
                    el = page.wait_for_selector(sel, timeout=4000)
                    if el:
                        href = el.get_attribute("href") or ""
                        if "/watch" in href:
                            link_href = href
                            break
                except Exception:
                    continue

            browser.close()
            return link_href
    except Exception as exc:
        logger.error("youtube_play playwright failed: %s", exc)
        return None


# ── Skill ─────────────────────────────────────────────────────────────────────

class BrowserAgentSkill(SkillBase):
    name        = "browser_agent"
    description = "Open browser, search Google/YouTube, manage tabs."
    priority    = 5
    keywords    = ["open browser", "google", "search", "youtube", "play video",
                   "website", "browse", "tab", "play song", "watch", "look up", 
                   "find information", "search for"]

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["open_browser", "google_search", "youtube_play",
                             "tab_action", "open_website"],
                },
                "url":         {"type": "string"},
                "query":       {"type": "string"},
                "tab_command": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        loop = asyncio.get_event_loop()

        # ── Simple webbrowser actions (no Playwright needed) ──────────────────
        if action == "open_browser":
            url = parameters.get("url") or "https://www.google.com"
            if not _open_url(url):
                return {"message": f"I couldn't open the browser.", "success": False}
            return {"message": f"Opening your browser", "summary_text": "Opening browser"}

        if action == "google_search":
            q   = parameters.get("query") or ""
            url = "https://www.google.com/search?q=" + urllib.parse.quote(q)

            # Open browser for the user to see
            _open_url(url)

            # Also fetch top results to display in Jarvis chat
            try:
                results = await loop.run_in_executor(_PW_EXECUTOR, _pw_google_results, q)
                if results:
                    lines = [f"Here's what I found for {q}:\n"]
                    for i, r in enumerate(results[:5], 1):
                        lines.append(f"{i}. [{r['title']}]({r['url']})")
                        if r.get("snippet"):
                            lines.append(f"   {r['snippet']}")
                    msg = "\n".join(lines)
                    tts_msg = f"I've opened Google search results for {q}. Here are the top results."
                    return {
                        "message":      msg,
                        "summary_text": tts_msg,
                        "skill_type":   "browser_agent",
                        "data":         {"results": results, "query": q, "search_url": url},
                    }
            except Exception as exc:
                logger.warning("google_results fetch failed: %s", exc)

            return {"message": f"I've opened Google search for {q}", "summary_text": f"Searching for {q}"}

        if action == "tab_action":
            return {"message": "Closing native browser tabs is not supported."}

        # ── open_website — find first organic result then open it ─────────────
        if action == "open_website":
            q = parameters.get("query") or ""
            if not q:
                return {"message": "Please provide a website name to search for."}

            search_url = "https://www.google.com/search?q=" + urllib.parse.quote(q)
            try:
                target_url = await loop.run_in_executor(_PW_EXECUTOR, _pw_open_website, q)
                if target_url:
                    if not _open_url(target_url):
                        return {"message": f"I found the website for {q} but couldn't open it.", "success": False}
                    return {"message": f"Opening {q} for you", "summary_text": f"Opening {q}"}
            except Exception as exc:
                logger.error("open_website failed: %s", exc)

            # Fallback
            if not _open_url(search_url):
                return {"message": f"I couldn't open the search for {q}.", "success": False}
            return {"message": f"I've opened a search for {q}", "summary_text": f"Searching for {q}"}

        # ── youtube_play — find first video then open with autoplay ───────────
        if action == "youtube_play":
            q = parameters.get("query") or ""
            search_url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(q)
            try:
                link_href = await loop.run_in_executor(_PW_EXECUTOR, _pw_youtube_play, q)
                if link_href:
                    full_url = "https://www.youtube.com" + link_href
                    full_url += ("&autoplay=1" if "?" in full_url else "?autoplay=1")
                    if not _open_url(full_url):
                        return {"message": f"I found {q} on YouTube but couldn't play it.", "success": False}
                    return {"message": f"Now playing {q}", "summary_text": f"Playing {q} on YouTube"}
            except Exception as exc:
                logger.error("youtube_play failed: %s", exc)

            # Fallback
            if not _open_url(search_url):
                return {"message": f"I couldn't open YouTube for {q}.", "success": False}
            return {"message": f"I've opened YouTube search for {q}", "summary_text": f"Searching YouTube for {q}"}

        return {"message": f"Unknown action: {action}"}
