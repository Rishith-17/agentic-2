"""Shopping: set and check price-drop alerts stored in SQLite alert_rules."""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]


def _make_session(referer: str = "") -> "requests.Session":
    import requests
    s = requests.Session()
    s.headers.update({
        "User-Agent":                random.choice(_USER_AGENTS),
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language":           "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding":           "gzip, deflate, br",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT":                       "1",
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
            logger.debug("HTTP %s on attempt %d for %s", resp.status_code, attempt, url)
            if attempt < max_retries:
                time.sleep(delay); delay *= 2
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            logger.debug("Request error attempt %d: %s", attempt, exc)
            if attempt < max_retries:
                time.sleep(delay); delay *= 2
        except Exception as exc:
            logger.debug("Unexpected error: %s", exc); break
    return None


def _parse_price(raw: str) -> float | None:
    cleaned = re.sub(r"[^\d.]", "", raw.replace(",", ""))
    try:
        val = float(cleaned)
        return val if 1 <= val <= 10_000_000 else None
    except ValueError:
        return None


def _fetch_price_from_url(url: str) -> float | None:
    """Fetch the current price from an Amazon.in or Flipkart product URL."""
    try:
        from bs4 import BeautifulSoup

        host    = urlparse(url).netloc.lower()
        session = _make_session(referer=url)
        resp    = _get_with_retry(session, url, max_retries=3)
        if resp is None:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        if "amazon" in host:
            for sel in [
                "#priceblock_ourprice", "#priceblock_dealprice",
                ".a-price .a-offscreen", "#price_inside_buybox",
                ".a-price[data-a-color='price'] .a-offscreen",
                "#corePrice_feature_div .a-offscreen",
            ]:
                el = soup.select_one(sel)
                if el:
                    p = _parse_price(el.get_text(strip=True))
                    if p:
                        return p

        elif "flipkart" in host:
            for sel in ["._30jeq3._16Jk6d", "._30jeq3", ".Nx9bqj", "._1_WHN1"]:
                el = soup.select_one(sel)
                if el:
                    p = _parse_price(el.get_text(strip=True))
                    if p:
                        return p

    except Exception as exc:
        logger.warning("Price fetch failed for %s: %s", url, exc)
    return None


# ── Skill ─────────────────────────────────────────────────────────────────────

from app.skills.base import SkillBase  # noqa: E402


class ShoppingPriceAlertSkill(SkillBase):
    """Set price-drop alerts for Amazon.in / Flipkart product URLs."""

    name        = "shopping_price_alert"
    description = "Set a price alert for a product URL; get notified when price drops below target."
    priority    = 5
    keywords    = ["alert", "track", "notify", "price drop", "watch", "price alert", "monitor price"]

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["set_alert", "list_alerts", "check_alerts", "delete_alert"],
                },
                "url":          {"type": "string"},
                "target_price": {"type": "number"},
                "product_name": {"type": "string"},
                "alert_id":     {"type": "integer"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        from app.dependencies import get_app_state
        state = get_app_state()

        # ── Set alert ────────────────────────────────────────────────────────
        if action == "set_alert":
            url          = (parameters.get("url") or "").strip()
            target_price = parameters.get("target_price")
            product_name = (parameters.get("product_name") or url[:60]).strip()

            if not url:
                return {"message": "Please provide a product URL to track."}
            if target_price is None:
                return {"message": "Please provide a target price for the alert."}

            rule_id = await state.sqlite.add_alert_rule(
                rule_type="price",
                threshold=float(target_price),
                meta={"url": url, "product_name": product_name},
            )
            msg = (
                f"✅ Alert set (ID: {rule_id}). "
                f"I'll notify you when '{product_name}' drops below ₹{target_price:,.0f}."
            )
            return {"message": msg, "summary_text": msg, "skill_type": "shopping", "alert_id": rule_id}

        # ── List alerts ──────────────────────────────────────────────────────
        if action == "list_alerts":
            rules = await state.sqlite.list_active_alerts()
            price_rules = [r for r in rules if r["rule_type"] == "price"]
            if not price_rules:
                return {"message": "No active price alerts.", "summary_text": "No active price alerts."}
            lines = []
            for r in price_rules:
                meta = r.get("meta", {})
                lines.append(
                    f"• ID {r['id']}: {meta.get('product_name', 'Unknown')} "
                    f"— target ₹{r['threshold']:,.0f}\n  {meta.get('url', '')}"
                )
            msg = "Active price alerts:\n" + "\n".join(lines)
            return {"message": msg, "summary_text": msg, "skill_type": "shopping"}

        # ── Check alerts (called by the alert checker loop) ──────────────────
        if action == "check_alerts":
            rules = await state.sqlite.list_active_alerts()
            price_rules = [r for r in rules if r["rule_type"] == "price"]
            triggered = []
            loop = asyncio.get_event_loop()

            for rule in price_rules:
                meta   = rule.get("meta", {})
                url    = meta.get("url", "")
                target = rule.get("threshold")
                if not url or target is None:
                    continue
                current = await loop.run_in_executor(None, _fetch_price_from_url, url)
                if current is not None and current <= target:
                    triggered.append({
                        "alert_id":     rule["id"],
                        "product_name": meta.get("product_name", url),
                        "current_price": current,
                        "target_price":  target,
                        "url":           url,
                    })

            if not triggered:
                return {"message": "No price alerts triggered.", "triggered": []}

            lines = []
            for t in triggered:
                lines.append(
                    f"🔔 '{t['product_name']}' is now ₹{t['current_price']:,.0f} "
                    f"(target ₹{t['target_price']:,.0f})\n  {t['url']}"
                )
            msg = "Price drop alerts triggered:\n" + "\n".join(lines)
            return {"message": msg, "summary_text": msg, "triggered": triggered, "skill_type": "shopping"}

        # ── Delete alert ─────────────────────────────────────────────────────
        if action == "delete_alert":
            alert_id = parameters.get("alert_id")
            if not alert_id:
                return {"message": "Please provide the alert_id to delete."}
            async with __import__("aiosqlite").connect(state.sqlite._path) as db:
                await db.execute(
                    "UPDATE alert_rules SET active=0 WHERE id=? AND rule_type='price'",
                    (int(alert_id),),
                )
                await db.commit()
            msg = f"Alert {alert_id} deleted."
            return {"message": msg, "summary_text": msg}

        return {"message": f"Unknown action: {action}"}
