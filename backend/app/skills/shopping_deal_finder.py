"""Shopping: find deals and discounts on Amazon.in and Flipkart."""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from typing import Any
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

# Shared with shopping_price_compare — same UA pool and session factory
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]


def _make_session(referer: str = "") -> "requests.Session":
    import requests
    ua = random.choice(_USER_AGENTS)
    s  = requests.Session()
    s.headers.update({
        "User-Agent":                ua,
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language":           "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding":           "gzip, deflate, br",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT":                       "1",
        "Cache-Control":             "max-age=0",
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "none" if not referer else "same-origin",
        "Sec-Fetch-User":            "?1",
    })
    if referer:
        s.headers["Referer"] = referer
    return s


def _get_with_retry(session: "requests.Session", url: str, *, max_retries: int = 3, timeout: int = 15) -> "requests.Response | None":
    import requests
    delay = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, timeout=timeout, allow_redirects=True)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (403, 429, 503):
                logger.debug("HTTP %s on attempt %d — backing off %.1fs", resp.status_code, attempt, delay)
            if attempt < max_retries:
                time.sleep(delay); delay *= 2
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            logger.debug("Request error attempt %d: %s", attempt, exc)
            if attempt < max_retries:
                time.sleep(delay); delay *= 2
        except Exception as exc:
            logger.debug("Unexpected error attempt %d: %s", attempt, exc)
            break
    return None


def _parse_price(raw: str) -> float | None:
    cleaned = re.sub(r"[^\d.]", "", raw.replace(",", ""))
    try:
        val = float(cleaned)
        return val if 1 <= val <= 10_000_000 else None
    except ValueError:
        return None


def _scrape_amazon_deals(category: str, max_price: float | None) -> list[dict[str, Any]]:
    """Scrape Amazon.in search results sorted by discount for a category."""
    deals: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        session = _make_session()
        _get_with_retry(session, "https://www.amazon.in", max_retries=1, timeout=8)

        price_filter = f"&rh=p_36%3A100-{int(max_price * 100)}" if max_price else ""
        url  = f"https://www.amazon.in/s?k={quote_plus(category)}&s=review-rank{price_filter}"
        session.headers["Referer"] = "https://www.amazon.in"
        resp = _get_with_retry(session, url, max_retries=3)
        if resp is None:
            return deals

        soup = BeautifulSoup(resp.text, "html.parser")
        PRICE_SELS = [".a-price-whole", ".a-price .a-offscreen", ".a-color-price"]

        for item in soup.select('[data-component-type="s-search-result"]')[:10]:
            title_el = item.select_one("h2 a span") or item.select_one(".a-size-medium")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)

            price: float | None = None
            for sel in PRICE_SELS:
                el = item.select_one(sel)
                if el:
                    price = _parse_price(el.get_text(strip=True))
                    if price:
                        break
            if price is None or (max_price and price > max_price):
                continue

            mrp_el   = item.select_one(".a-text-price .a-offscreen")
            mrp      = _parse_price(mrp_el.get_text(strip=True)) if mrp_el else None
            discount = round((mrp - price) / mrp * 100) if mrp and mrp > price else 0

            link_el  = item.select_one("h2 a")
            href     = (link_el.get("href") or "") if link_el else ""
            full_url = ("https://www.amazon.in" + href.split("?")[0]) if href.startswith("/") else href

            deals.append({"title": title[:80], "price": price, "mrp": mrp,
                          "discount": discount, "url": full_url, "store": "Amazon.in"})
            if len(deals) >= 5:
                break

    except Exception as exc:
        logger.warning("Amazon deals scrape failed: %s", exc)
    return deals


def _scrape_flipkart_deals(category: str, max_price: float | None) -> list[dict[str, Any]]:
    """Scrape Flipkart search results for a category."""
    deals: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        session = _make_session(referer="https://www.flipkart.com")
        _get_with_retry(session, "https://www.flipkart.com", max_retries=1, timeout=8)

        url  = f"https://www.flipkart.com/search?q={quote_plus(category)}&sort=discount_desc"
        session.headers["Referer"] = "https://www.flipkart.com"
        resp = _get_with_retry(session, url, max_retries=3)
        if resp is None:
            return deals

        soup = BeautifulSoup(resp.text, "html.parser")

        LAYOUTS = [
            ("div._1AtVbE", ["div._4rR01T", "div.s1Q9rs"], ["div._30jeq3", "div.Nx9bqj"], "div._3Ay6Sb"),
            ("div.KzDlHZ",  ["div._2WkVRV"],               ["div.Nx9bqj", "div._30jeq3"], None),
        ]

        for card_sel, title_sels, price_sels, disc_sel in LAYOUTS:
            for card in soup.select(card_sel)[:10]:
                title: str = ""
                for sel in title_sels:
                    el = card.select_one(sel)
                    if el:
                        title = el.get_text(strip=True)
                        if title:
                            break
                if not title:
                    continue

                price: float | None = None
                for sel in price_sels:
                    el = card.select_one(sel)
                    if el:
                        price = _parse_price(el.get_text(strip=True))
                        if price:
                            break
                if price is None or (max_price and price > max_price):
                    continue

                disc_el      = card.select_one(disc_sel) if disc_sel else None
                discount_raw = disc_el.get_text(strip=True) if disc_el else "0"
                disc_num     = re.search(r"\d+", discount_raw)
                discount     = int(disc_num.group()) if disc_num else 0

                link_el  = card.select_one("a")
                href     = (link_el.get("href") or "") if link_el else ""
                full_url = ("https://www.flipkart.com" + href) if href.startswith("/") else href

                deals.append({"title": title[:80], "price": price, "mrp": None,
                              "discount": discount, "url": full_url, "store": "Flipkart"})
                if len(deals) >= 5:
                    break
            if deals:
                break

    except Exception as exc:
        logger.warning("Flipkart deals scrape failed: %s", exc)
    return deals


# ── Skill ─────────────────────────────────────────────────────────────────────

from app.skills.base import SkillBase  # noqa: E402


class ShoppingDealFinderSkill(SkillBase):
    """Find discounted deals for a product category on Amazon.in and Flipkart."""

    name        = "shopping_deal_finder"
    description = "Find deals, discounts, and offers for a product category."
    priority    = 5
    keywords    = ["deal", "offer", "discount", "coupon", "sale", "best price", "offers", "cheap"]

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action":    {"type": "string", "enum": ["find_deals"]},
                "category":  {"type": "string"},
                "max_price": {"type": "number"},
            },
            "required": ["action", "category"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        if action != "find_deals":
            return {"message": f"Unknown action: {action}"}

        category  = (parameters.get("category") or "").strip()
        max_price = parameters.get("max_price")
        if not category:
            return {"message": "Please provide a product category (e.g. 'laptops', 'headphones')."}

        try:
            from app.utils.dep_check import require
            require("bs4",      "beautifulsoup4>=4.12.3")
            require("requests", "requests>=2.31.0")
        except ImportError as exc:
            msg = f"⚠️ {exc}"
            return {"message": msg, "summary_text": msg}

        loop = asyncio.get_event_loop()
        amazon_deals, flipkart_deals = await asyncio.gather(
            loop.run_in_executor(None, _scrape_amazon_deals,   category, max_price),
            loop.run_in_executor(None, _scrape_flipkart_deals, category, max_price),
        )

        all_deals = amazon_deals + flipkart_deals
        if not all_deals:
            msg = f"No deals found for '{category}' right now. Try a broader category."
            return {"message": msg, "summary_text": msg}

        # Sort by discount % descending, take top 5
        all_deals.sort(key=lambda d: d["discount"], reverse=True)
        top = all_deals[:5]

        lines = []
        for d in top:
            disc_str = f" ({d['discount']}% off)" if d["discount"] else ""
            lines.append(
                f"• [{d['store']}] {d['title']}\n"
                f"  ₹{d['price']:,.0f}{disc_str}\n"
                f"  {d['url']}"
            )

        price_note = f" under ₹{max_price:,.0f}" if max_price else ""
        summary = f"Top deals for '{category}'{price_note}:"
        full_msg = summary + "\n\n" + "\n\n".join(lines)
        return {
            "message":      full_msg,
            "summary_text": summary + f" Found {len(top)} deals.",
            "skill_type":   "shopping",
            "data":         {"deals": top},
        }
