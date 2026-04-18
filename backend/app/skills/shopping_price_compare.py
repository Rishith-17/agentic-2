"""Shopping: compare product prices across Amazon.in and Flipkart.

Uses built-in requests+BeautifulSoup scrapers with:
  - Rotating User-Agent pool (Chrome 120-122, Edge, Firefox)
  - Full browser-like headers including Sec-Fetch-* (Chrome/Edge)
  - requests.Session() with homepage warm-up for cookie acquisition
  - Exponential back-off retry (1s -> 2s -> 4s) on 4xx/5xx
  - Sponsored-result filtering on Amazon
  - Title relevance filter: every query word must appear in the result title
  - ASIN extraction -> clean /dp/{ASIN} URL (no tracking params)
  - Mobile UA fallback for Flipkart when desktop gets 403
  - Graceful degradation: one site failing never blocks the other
  - Fallback search links when both scrapers fail
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from typing import Any
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

# ── User-Agent pool ───────────────────────────────────────────────────────────
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]
_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _parse_price(raw: str) -> float | None:
    """Strip currency symbols/commas and return float, or None."""
    cleaned = re.sub(r"[^\d.]", "", raw.replace(",", ""))
    try:
        val = float(cleaned)
        return val if 1 <= val <= 10_000_000 else None
    except ValueError:
        return None


def _extract_asin(href: str) -> str | None:
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", href)
    return m.group(1) if m else None


def _clean_amazon_url(href: str) -> str:
    """Return https://www.amazon.in/dp/{ASIN} or strip tracking params."""
    asin = _extract_asin(href)
    if asin:
        return f"https://www.amazon.in/dp/{asin}"
    base = href.split("?")[0].split("%3F")[0]
    return ("https://www.amazon.in" + base) if base.startswith("/") else base


def _title_matches_query(title: str, query: str) -> bool:
    """
    Every significant word in query must appear in title (case-insensitive).
    Strips common filler words so 'iPhone 13 price' still matches 'Apple iPhone 13'.
    """
    STOP = {
        "price", "cheapest", "cost", "buy", "best", "of", "the", "a", "an",
        "in", "on", "for", "and", "or", "vs", "compare", "india", "tell",
        "me", "show", "what", "is", "are", "how", "much", "does",
    }
    title_lower = title.lower()
    words = [w for w in re.split(r"\W+", query.lower()) if w and w not in STOP]
    return all(w in title_lower for w in words) if words else True


def _make_session(referer: str = "", mobile: bool = False) -> "requests.Session":
    import requests
    ua = _MOBILE_UA if mobile else random.choice(_USER_AGENTS)
    is_firefox = "Firefox" in ua
    s = requests.Session()
    s.headers.update({
        "User-Agent":                ua,
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language":           "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding":           "gzip, deflate, br",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT":                       "1",
        "Cache-Control":             "max-age=0",
    })
    if not mobile and not is_firefox:
        s.headers.update({
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none" if not referer else "same-origin",
            "Sec-Fetch-User": "?1",
            "Sec-CH-UA":      '"Chromium";v="122", "Not(A:Brand";v="24"',
            "Sec-CH-UA-Mobile":   "?0",
            "Sec-CH-UA-Platform": '"Windows"',
        })
    if referer:
        s.headers["Referer"] = referer
    return s


def _get_with_retry(
    session: "requests.Session",
    url: str,
    *,
    max_retries: int = 3,
    timeout: int = 12,
) -> "requests.Response | None":
    import requests
    delay = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, timeout=timeout, allow_redirects=True)
            if resp.status_code == 200:
                return resp
            logger.debug("HTTP %s attempt %d: %s", resp.status_code, attempt, url[:80])
            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            logger.debug("Request error attempt %d: %s", attempt, exc)
            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2
        except Exception as exc:
            logger.debug("Unexpected error: %s", exc)
            break
    return None


# ── Amazon.in scraper ─────────────────────────────────────────────────────────

def _scrape_amazon(product: str) -> dict[str, Any] | None:
    """Return best-matching, cheapest Amazon.in result for *product*."""
    try:
        from bs4 import BeautifulSoup

        session = _make_session()
        # Homepage warm-up to acquire session cookies
        _get_with_retry(session, "https://www.amazon.in", max_retries=1, timeout=8)
        session.headers["Referer"] = "https://www.amazon.in"

        url  = f"https://www.amazon.in/s?k={quote_plus(product)}&ref=nb_sb_noss"
        resp = _get_with_retry(session, url, max_retries=3)
        if not resp:
            logger.warning("Amazon: all retries exhausted for '%s'", product)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        PRICE_SELS = [
            ".a-price-whole",
            ".a-price .a-offscreen",
            "[data-a-size='xl'] .a-price-whole",
            "[data-a-size='l'] .a-price-whole",
            ".a-price[data-a-color='base'] .a-offscreen",
            ".a-color-price",
        ]

        candidates: list[dict[str, Any]] = []

        for item in soup.select('[data-component-type="s-search-result"]')[:20]:
            # Skip sponsored slots
            if item.select_one('[data-component-type="sp-sponsored-result"]'):
                continue

            title_el = (
                item.select_one("h2 a span")
                or item.select_one(".a-size-medium.a-color-base.a-text-normal")
                or item.select_one(".a-size-base-plus")
            )
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title or not _title_matches_query(title, product):
                continue

            price: float | None = None
            for sel in PRICE_SELS:
                el = item.select_one(sel)
                if el:
                    price = _parse_price(el.get_text(strip=True))
                    if price:
                        break
            if not price:
                continue

            link_el  = item.select_one("h2 a") or item.select_one("a.a-link-normal")
            raw_href = (link_el.get("href") or "") if link_el else ""
            candidates.append({
                "title": title,
                "price": price,
                "url":   _clean_amazon_url(raw_href),
                "store": "Amazon.in",
            })

        if not candidates:
            logger.warning("Amazon: no matching results for '%s'", product)
            return None

        best = min(candidates, key=lambda c: c["price"])
        logger.info("Amazon: %s @ Rs.%s", best["title"][:50], best["price"])
        return best

    except Exception as exc:
        logger.warning("Amazon scrape failed: %s", exc)
    return None


# ── Flipkart scraper ──────────────────────────────────────────────────────────

def _scrape_flipkart(product: str) -> dict[str, Any] | None:
    """Return best-matching, cheapest Flipkart result for *product*."""
    try:
        from bs4 import BeautifulSoup

        base       = "https://www.flipkart.com"
        search_url = f"{base}/search?q={quote_plus(product)}&otracker=search"

        LAYOUTS = [
            {
                "card":  "div._1AtVbE",
                "title": ["div._4rR01T", "div.s1Q9rs", "a.s1Q9rs", "div._2WkVRV"],
                "price": ["div._30jeq3", "div.Nx9bqj", "div._1_WHN1"],
            },
            {
                "card":  "div.KzDlHZ",
                "title": ["div._2WkVRV", "a"],
                "price": ["div.Nx9bqj", "div._30jeq3"],
            },
            {
                "card":  "div._13oc-S",
                "title": ["div._4rR01T", "a.IRpwTa"],
                "price": ["div._30jeq3"],
            },
        ]

        for mobile in (False, True):
            session = _make_session(referer=base, mobile=mobile)
            if not mobile:
                _get_with_retry(session, base, max_retries=1, timeout=8)
            resp = _get_with_retry(session, search_url, max_retries=2)
            if not resp:
                continue

            soup       = BeautifulSoup(resp.text, "html.parser")
            candidates: list[dict[str, Any]] = []

            for layout in LAYOUTS:
                for card in soup.select(layout["card"])[:15]:
                    title = next(
                        (el.get_text(strip=True)
                         for sel in layout["title"]
                         if (el := card.select_one(sel)) and el.get_text(strip=True)),
                        "",
                    )
                    if not title or not _title_matches_query(title, product):
                        continue

                    price = next(
                        (p
                         for sel in layout["price"]
                         if (el := card.select_one(sel))
                         and (p := _parse_price(el.get_text(strip=True)))),
                        None,
                    )
                    if not price:
                        continue

                    link_el  = card.select_one("a")
                    href     = (link_el.get("href") or "") if link_el else ""
                    full_url = (base + href) if href.startswith("/") else href
                    candidates.append({
                        "title": title,
                        "price": price,
                        "url":   full_url,
                        "store": "Flipkart",
                    })

                if candidates:
                    break

            if candidates:
                best = min(candidates, key=lambda c: c["price"])
                logger.info("Flipkart: %s @ Rs.%s", best["title"][:50], best["price"])
                return best

        logger.warning("Flipkart: no matching results for '%s'", product)

    except Exception as exc:
        logger.warning("Flipkart scrape failed: %s", exc)
    return None


# ── Skill ─────────────────────────────────────────────────────────────────────

from app.skills.base import SkillBase  # noqa: E402


class ShoppingPriceCompareSkill(SkillBase):
    """Compare product prices on Amazon.in and Flipkart; return the cheapest."""

    name        = "shopping_price_compare"
    description = "Compare product prices on Amazon.in and Flipkart and return the cheapest option with a clickable link."
    priority    = 6
    keywords    = [
        "price", "cheapest", "compare", "buy", "shopping",
        "amazon", "flipkart", "cost", "how much", "rate",
    ]

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action":  {"type": "string", "enum": ["compare"]},
                "product": {"type": "string"},
            },
            "required": ["action", "product"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        if action != "compare":
            return {"message": f"Unknown action: {action}"}

        product = (parameters.get("product") or "").strip()
        if not product:
            return {"message": "Please provide a product name to compare prices."}

        # Dependency guard
        try:
            from app.utils.dep_check import require
            require("bs4",      "beautifulsoup4>=4.12.3")
            require("requests", "requests>=2.31.0")
        except ImportError as exc:
            msg = f"Missing dependency: {exc}"
            return {"message": msg, "summary_text": msg}

        # Run both scrapers concurrently
        loop = asyncio.get_event_loop()
        amazon_res, flipkart_res = await asyncio.gather(
            loop.run_in_executor(None, _scrape_amazon,   product),
            loop.run_in_executor(None, _scrape_flipkart, product),
        )
        results = [r for r in [amazon_res, flipkart_res] if r is not None]

        if not results:
            amazon_link   = f"https://www.amazon.in/s?k={quote_plus(product)}"
            flipkart_link = f"https://www.flipkart.com/search?q={quote_plus(product)}"
            msg = (
                f"Could not automatically fetch prices for '{product}' right now.\n\n"
                f"Check manually:\n"
                f"Amazon.in: {amazon_link}\n"
                f"Flipkart:  {flipkart_link}"
            )
            return {
                "message":      msg,
                "summary_text": msg,
                "skill_type":   "shopping",
                "data": {
                    "links": [
                        {"label": "Amazon.in search",  "url": amazon_link},
                        {"label": "Flipkart search",   "url": flipkart_link},
                    ],
                },
            }

        cheapest = min(results, key=lambda r: r["price"])
        lines = []
        for r in results:
            marker = " [CHEAPEST]" if r is cheapest else ""
            lines.append(
                f"* {r['store']}: Rs.{r['price']:,.0f} -- {r['title'][:60]}{marker}\n"
                f"  {r['url']}"
            )

        summary = (
            f"The cheapest '{product}' is Rs.{cheapest['price']:,.0f} on {cheapest['store']}.\n"
            f"Link: {cheapest['url']}"
        )
        return {
            "message":      summary + "\n\n" + "\n".join(lines),
            "summary_text": summary,
            "skill_type":   "shopping",
            "data": {
                "cheapest": cheapest,
                "all":      results,
                # Structured links for the frontend to render as clickable buttons
                "links": [
                    {"label": f"{r['store']} -- Rs.{r['price']:,.0f}", "url": r["url"]}
                    for r in results
                ],
            },
        }
