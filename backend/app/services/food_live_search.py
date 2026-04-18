from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

_SEARCH_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="food-live")
_PW_TIMEOUT_MS = 20000

DEFAULT_CITY = "Bengaluru"

_GROCERY_KEYWORDS = {
    "milk", "eggs", "bread", "butter", "rice", "dal", "flour", "sugar",
    "salt", "oil", "ghee", "cheese", "yogurt", "curd", "vegetables",
    "fruits", "onion", "tomato", "potato", "garlic", "ginger",
    "detergent", "soap", "shampoo", "toothpaste", "tissue", "water",
    "juice", "coke", "pepsi", "chips", "biscuit", "chocolate", "oats",
    "cereal", "atta", "paneer", "snacks", "grocery", "groceries",
}

_FOOD_KEYWORDS = {
    "biryani", "pizza", "burger", "pasta", "sushi", "dosa", "idli",
    "paratha", "noodles", "momos", "rolls", "sandwich", "thali",
    "curry", "tandoori", "kebab", "soup", "salad", "dessert",
    "cake", "ice cream", "shake", "restaurant", "meal", "dinner",
    "lunch", "breakfast", "food",
}

_NOISE_PATTERNS = [
    r"^\s*(please\s+)?(help\s+me\s+)?(buy|get|order)\s+",
    r"^\s*(please\s+)?(search\s+for|find)\s+",
    r"^\s*(i\s+want|i\s+need|show\s+me)\s+",
    r"^\s*(can\s+you\s+)?(get|order|buy)\s+me\s+",
]

_SEARCH_URLS = {
    "zomato": "https://www.zomato.com/{city_slug}/search?q={query}",
    "swiggy": "https://www.swiggy.com/search?query={query}",
    "blinkit": "https://blinkit.com/s/?q={query}",
    "zepto": "https://www.zeptonow.com/search?query={query}",
}


def normalize_food_query(raw: str) -> str:
    cleaned = (raw or "").strip()
    for pattern in _NOISE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(on|from)\s+(swiggy|zomato|blinkit|zepto)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,!?\t\r\n")
    return cleaned or (raw or "").strip()


def infer_food_intent(query: str) -> str:
    words = set((query or "").lower().split())
    if words & _GROCERY_KEYWORDS:
        return "grocery"
    if words & _FOOD_KEYWORDS:
        return "food"
    return "food"


def infer_food_platforms(query: str) -> list[str]:
    intent = infer_food_intent(query)
    if intent == "grocery":
        return ["blinkit", "swiggy"]
    return ["zomato", "swiggy"]


def build_food_platform_url(platform: str, query: str, city: str = DEFAULT_CITY, item_url: str = "") -> str:
    if item_url:
        return item_url
    city_slug = (city or DEFAULT_CITY).lower().replace(" ", "-")
    encoded_query = urllib.parse.quote(query or "")
    template = _SEARCH_URLS.get(platform, _SEARCH_URLS["swiggy"])
    return template.format(query=encoded_query, city_slug=city_slug)


def _safe_text(element: Any) -> str:
    try:
        return (element.inner_text() or "").strip()
    except Exception:
        return ""


def _safe_href(element: Any) -> str:
    if not element:
        return ""
    try:
        href = element.get_attribute("href") or ""
        if href.startswith("/"):
            return "https://www.swiggy.com" + href
        return href
    except Exception:
        return ""


def _parse_price(raw: str) -> float:
    tokens = raw.replace(",", " ").replace("₹", " ").split()
    for token in tokens:
        try:
            return float(token)
        except ValueError:
            continue
    return 0.0


def _parse_rating(raw: str) -> float | None:
    for token in raw.split():
        try:
            value = float(token)
            if 0 < value <= 5:
                return value
        except ValueError:
            continue
    return None


def _parse_eta(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    match = re.search(r"(\d+\s*(?:min|mins|minutes))", raw, flags=re.IGNORECASE)
    return match.group(1) if match else raw[:30]


def _scrape_zomato(page: Any, query: str, city: str, max_results: int) -> list[dict[str, Any]]:
    page.goto(build_food_platform_url("zomato", query, city), wait_until="domcontentloaded")
    try:
        page.wait_for_selector('[data-testid="search-snippet-card"], [data-testid="search-snippet-cards"] > div, .sc-aXZVg', timeout=_PW_TIMEOUT_MS)
    except Exception:
        pass

    selectors = ['[data-testid="search-snippet-card"]', '[data-testid="search-snippet-cards"] > div', '.sc-aXZVg']
    cards: list[Any] = []
    for selector in selectors:
        cards = page.query_selector_all(selector)
        if cards:
            break

    items: list[dict[str, Any]] = []
    for card in cards[:max_results]:
        try:
            link_el = card.query_selector("a")
            name = _safe_text(card.query_selector("h4, h3, [class*='name']"))
            if not name:
                continue
            items.append({
                "id": name.lower().replace(" ", "-"),
                "name": name,
                "price": _parse_price(_safe_text(card.query_selector("[class*='price'], [class*='Price']"))),
                "rating": _parse_rating(_safe_text(card.query_selector("[class*='rating'], [class*='Rating']"))),
                "eta": _parse_eta(_safe_text(card.query_selector("[class*='delivery'], [class*='time']"))),
                "url": _safe_href(link_el) or build_food_platform_url("zomato", query, city),
                "platform": "Zomato",
            })
        except Exception:
            continue
    return items


def _scrape_swiggy(page: Any, query: str, city: str, max_results: int) -> list[dict[str, Any]]:
    page.goto(build_food_platform_url("swiggy", query, city), wait_until="domcontentloaded")
    try:
        page.wait_for_selector("[class*='DishResult'], [class*='dishCard'], [class*='RestaurantCard'], [class*='restaurantCard']", timeout=_PW_TIMEOUT_MS)
    except Exception:
        pass

    selectors = ["[class*='DishResult']", "[class*='dishCard']", "[class*='RestaurantCard']", "[class*='restaurantCard']"]
    cards: list[Any] = []
    for selector in selectors:
        cards = page.query_selector_all(selector)
        if cards:
            break

    items: list[dict[str, Any]] = []
    for card in cards[:max_results]:
        try:
            name = _safe_text(card.query_selector("h4, h3, p[class*='name'], [class*='Name']"))
            if not name:
                continue
            link_el = card.query_selector("a")
            items.append({
                "id": name.lower().replace(" ", "-"),
                "name": name,
                "price": _parse_price(_safe_text(card.query_selector("[class*='price'], [class*='Price'], [class*='rupee']"))),
                "rating": _parse_rating(_safe_text(card.query_selector("[class*='rating'], [class*='Rating']"))),
                "eta": _parse_eta(_safe_text(card.query_selector("[class*='time'], [class*='Time'], [class*='eta']"))),
                "url": _safe_href(link_el) or build_food_platform_url("swiggy", query, city),
                "platform": "Swiggy",
            })
        except Exception:
            continue
    return items


def _scrape_blinkit(page: Any, query: str, city: str, max_results: int) -> list[dict[str, Any]]:
    page.goto(build_food_platform_url("blinkit", query, city), wait_until="domcontentloaded")
    try:
        page.wait_for_selector("[class*='Product__Wrapper'], [data-testid='product-card'], [class*='plp-product'], [class*='product-card']", timeout=_PW_TIMEOUT_MS)
    except Exception:
        pass

    selectors = [
        "[class*='Product__Wrapper']",
        "[data-testid='product-card']",
        "[class*='plp-product']",
        "[class*='product-card']",
    ]
    cards: list[Any] = []
    for selector in selectors:
        cards = page.query_selector_all(selector)
        if cards:
            break

    items: list[dict[str, Any]] = []
    for card in cards[:max_results]:
        try:
            name = _safe_text(
                card.query_selector("[class*='Product__Title'], [class*='product-title'], h3, h4")
            )
            if not name:
                continue
            qty = _safe_text(card.query_selector("[class*='Product__Quantity'], [class*='weight'], [class*='quantity']"))
            full_name = f"{name} ({qty})" if qty else name
            link_el = card.query_selector("a")
            items.append({
                "id": full_name.lower().replace(" ", "-"),
                "name": full_name,
                "price": _parse_price(_safe_text(card.query_selector("[class*='Product__Price'], [class*='product-price'], [class*='price']"))),
                "rating": None,
                "eta": _parse_eta(_safe_text(card.query_selector("[class*='timer'], [class*='delivery'], [class*='eta']"))) or "10 min",
                "url": _safe_href(link_el) or build_food_platform_url("blinkit", query, city),
                "platform": "Blinkit",
            })
        except Exception:
            continue
    return items


_PLATFORM_SCRAPERS = {
    "zomato": _scrape_zomato,
    "swiggy": _scrape_swiggy,
    "blinkit": _scrape_blinkit,
}


def _run_platform_search(platform: str, query: str, city: str, max_results: int) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    scraper = _PLATFORM_SCRAPERS[platform]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        page = context.new_page()
        page.set_default_timeout(_PW_TIMEOUT_MS)
        try:
            items = scraper(page, query, city, max_results)
            return {"platform": platform, "success": True, "items": items, "error": ""}
        except Exception as exc:
            logger.warning("Live search failed on %s for %s: %s", platform, query, exc)
            return {"platform": platform, "success": False, "items": [], "error": f"{platform.title()}: {type(exc).__name__}: {exc}"}
        finally:
            browser.close()


class FoodLiveSearchService:
    async def search_platform(
        self,
        platform: str,
        query: str,
        city: str = DEFAULT_CITY,
        *,
        max_results: int = 5,
    ) -> dict[str, Any]:
        if platform not in _PLATFORM_SCRAPERS:
            return {"platform": platform, "success": False, "items": [], "error": f"{platform}: unsupported platform"}
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_SEARCH_EXECUTOR, _run_platform_search, platform, query, city, max_results)

    async def search_many(
        self,
        query: str,
        city: str = DEFAULT_CITY,
        *,
        platforms: list[str] | None = None,
        max_results: int = 5,
    ) -> dict[str, Any]:
        cleaned_query = normalize_food_query(query)
        chosen_platforms = platforms or infer_food_platforms(cleaned_query)
        results = await asyncio.gather(
            *(self.search_platform(platform, cleaned_query, city, max_results=max_results) for platform in chosen_platforms),
            return_exceptions=True,
        )

        items: list[dict[str, Any]] = []
        errors: list[str] = []
        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
                continue
            items.extend(result.get("items", []))
            if result.get("error"):
                errors.append(result["error"])

        items.sort(key=lambda item: (-float(item.get("rating") or 0), float(item.get("price") or 999999)))
        return {
            "query": cleaned_query,
            "intent": infer_food_intent(cleaned_query),
            "platforms": chosen_platforms,
            "items": items,
            "errors": errors,
        }


_food_live_search: FoodLiveSearchService | None = None


def get_food_live_search() -> FoodLiveSearchService:
    global _food_live_search
    if _food_live_search is None:
        _food_live_search = FoodLiveSearchService()
    return _food_live_search
