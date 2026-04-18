"""User memory service — SQLite-backed preferences, order history, and learning loop.

Stores per-user food preferences, order history, platform success rates, and
dietary/budget constraints. Used by the intent engine and recommendation engine
to personalise every food/grocery interaction.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS food_preferences (
    user_id     TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS food_order_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    item            TEXT NOT NULL,
    platform        TEXT NOT NULL,
    price           REAL,
    category        TEXT,
    diet_type       TEXT,
    ordered_at      TEXT NOT NULL,
    success         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS platform_stats (
    user_id         TEXT NOT NULL,
    platform        TEXT NOT NULL,
    success_count   INTEGER NOT NULL DEFAULT 0,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    last_used       TEXT,
    PRIMARY KEY (user_id, platform)
);
"""

_DEFAULT_PREFERENCES: dict[str, Any] = {
    "food_platform":     "swiggy",
    "grocery_platform":  "blinkit",
    "favorite_items":    [],
    "diet":              "any",          # vegetarian | non-vegetarian | vegan | any
    "budget_range":      "medium",       # low | medium | high
    "preferred_cuisine": [],
    "disliked_items":    [],
    "default_address":   "",
}

DEFAULT_USER = "default"


class UserMemory:
    """
    Async SQLite-backed user memory for food & grocery personalisation.

    All methods accept a user_id (defaults to 'default') so the system
    can support multiple users in the future without schema changes.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        settings = get_settings()
        self._path = db_path or (settings.data_dir / "food_memory.db")

    # ── Initialisation ────────────────────────────────────────────────────────

    async def init(self) -> None:
        """Create tables if they don't exist."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        logger.info("UserMemory initialised at %s", self._path)

    # ── Preferences ───────────────────────────────────────────────────────────

    async def get_preferences(self, user_id: str = DEFAULT_USER) -> dict[str, Any]:
        """Return all preferences for *user_id*, merged with defaults."""
        prefs = dict(_DEFAULT_PREFERENCES)
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "SELECT key, value FROM food_preferences WHERE user_id = ?",
                (user_id,),
            )
            rows = await cur.fetchall()
        for key, raw_val in rows:
            try:
                prefs[key] = json.loads(raw_val)
            except (json.JSONDecodeError, TypeError):
                prefs[key] = raw_val
        return prefs

    async def set_preference(self, key: str, value: Any, user_id: str = DEFAULT_USER) -> None:
        """Upsert a single preference."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """INSERT INTO food_preferences(user_id, key, value, updated_at)
                   VALUES(?, ?, ?, ?)
                   ON CONFLICT(user_id, key)
                   DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (user_id, key, json.dumps(value), datetime.utcnow().isoformat()),
            )
            await db.commit()
        logger.debug("Preference set: user=%s %s=%s", user_id, key, value)

    async def update_preferences(self, updates: dict[str, Any], user_id: str = DEFAULT_USER) -> None:
        """Batch-update multiple preferences."""
        for key, value in updates.items():
            await self.set_preference(key, value, user_id)

    # ── Order history ─────────────────────────────────────────────────────────

    async def log_order(
        self,
        item: str,
        platform: str,
        *,
        price: float | None = None,
        category: str | None = None,
        diet_type: str | None = None,
        success: bool = True,
        user_id: str = DEFAULT_USER,
    ) -> None:
        """Record a completed (or failed) order for learning."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """INSERT INTO food_order_history
                   (user_id, item, platform, price, category, diet_type, ordered_at, success)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id, item, platform, price,
                    category, diet_type,
                    datetime.utcnow().isoformat(),
                    1 if success else 0,
                ),
            )
            await db.commit()

        # Update platform stats
        await self._update_platform_stats(platform, success=success, user_id=user_id)

        # Learning loop: update favorite_items if successful
        if success:
            await self._update_favorites(item, user_id)

    async def get_order_history(
        self,
        limit: int = 20,
        user_id: str = DEFAULT_USER,
    ) -> list[dict[str, Any]]:
        """Return recent order history, newest first."""
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                """SELECT item, platform, price, category, diet_type, ordered_at, success
                   FROM food_order_history
                   WHERE user_id = ?
                   ORDER BY ordered_at DESC
                   LIMIT ?""",
                (user_id, limit),
            )
            rows = await cur.fetchall()
        return [
            {
                "item":      r[0],
                "platform":  r[1],
                "price":     r[2],
                "category":  r[3],
                "diet_type": r[4],
                "ordered_at": r[5],
                "success":   bool(r[6]),
            }
            for r in rows
        ]

    async def get_top_items(
        self,
        limit: int = 10,
        user_id: str = DEFAULT_USER,
    ) -> list[dict[str, Any]]:
        """Return most-ordered items with frequency counts."""
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                """SELECT item, platform, COUNT(*) as freq
                   FROM food_order_history
                   WHERE user_id = ? AND success = 1
                   GROUP BY item, platform
                   ORDER BY freq DESC
                   LIMIT ?""",
                (user_id, limit),
            )
            rows = await cur.fetchall()
        return [{"item": r[0], "platform": r[1], "frequency": r[2]} for r in rows]

    # ── Platform stats ────────────────────────────────────────────────────────

    async def get_platform_stats(self, user_id: str = DEFAULT_USER) -> dict[str, dict[str, Any]]:
        """Return success/failure counts per platform."""
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "SELECT platform, success_count, failure_count, last_used "
                "FROM platform_stats WHERE user_id = ?",
                (user_id,),
            )
            rows = await cur.fetchall()
        return {
            r[0]: {
                "success_count": r[1],
                "failure_count": r[2],
                "last_used":     r[3],
                "success_rate":  r[1] / max(r[1] + r[2], 1),
            }
            for r in rows
        }

    async def best_platform_for_category(
        self,
        category: str,
        user_id: str = DEFAULT_USER,
    ) -> str | None:
        """
        Return the platform with the highest success rate for *category*
        (food or grocery), weighted by user preference.
        """
        prefs = await self.get_preferences(user_id)
        stats = await self.get_platform_stats(user_id)

        if category == "food":
            candidates = ["swiggy", "zomato"]
            preferred  = prefs.get("food_platform", "swiggy")
        else:
            candidates = ["blinkit", "zepto"]
            preferred  = prefs.get("grocery_platform", "blinkit")

        # Sort by success rate; preferred platform wins ties
        def score(p: str) -> float:
            s = stats.get(p, {})
            rate = s.get("success_rate", 0.5)
            bonus = 0.1 if p == preferred else 0.0
            return rate + bonus

        ranked = sorted(candidates, key=score, reverse=True)
        return ranked[0] if ranked else preferred

    # ── Context snapshot ──────────────────────────────────────────────────────

    async def get_context_snapshot(self, user_id: str = DEFAULT_USER) -> dict[str, Any]:
        """
        Return a compact snapshot of user context for the intent engine.
        Includes preferences, top items, and platform stats.
        """
        prefs   = await self.get_preferences(user_id)
        top     = await self.get_top_items(limit=5, user_id=user_id)
        history = await self.get_order_history(limit=5, user_id=user_id)
        stats   = await self.get_platform_stats(user_id)

        return {
            "user_id":     user_id,
            "preferences": prefs,
            "top_items":   top,
            "recent_orders": history,
            "platform_stats": stats,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _update_platform_stats(
        self,
        platform: str,
        success: bool,
        user_id: str,
    ) -> None:
        col = "success_count" if success else "failure_count"
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                f"""INSERT INTO platform_stats(user_id, platform, success_count, failure_count, last_used)
                    VALUES(?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, platform)
                    DO UPDATE SET {col} = {col} + 1, last_used = excluded.last_used""",
                (
                    user_id, platform,
                    1 if success else 0,
                    0 if success else 1,
                    datetime.utcnow().isoformat(),
                ),
            )
            await db.commit()

    async def _update_favorites(self, item: str, user_id: str) -> None:
        """Add *item* to favorite_items if it appears 3+ times."""
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM food_order_history WHERE user_id=? AND item=? AND success=1",
                (user_id, item),
            )
            row = await cur.fetchone()
            count = row[0] if row else 0

        if count >= 3:
            prefs = await self.get_preferences(user_id)
            favs  = prefs.get("favorite_items", [])
            if item not in favs:
                favs.append(item)
                await self.set_preference("favorite_items", favs, user_id)
                logger.info("Added '%s' to favorites for user '%s'", item, user_id)


# ── Module-level singleton ────────────────────────────────────────────────────

_memory: UserMemory | None = None


async def get_user_memory() -> UserMemory:
    """Return (and lazily initialise) the singleton UserMemory instance."""
    global _memory
    if _memory is None:
        _memory = UserMemory()
        await _memory.init()
    return _memory
