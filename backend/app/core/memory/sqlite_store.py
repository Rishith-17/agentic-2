"""Structured preferences and alert rules in SQLite."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import aiosqlite

from app.config import Settings

logger = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alert_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT NOT NULL,
    threshold REAL,
    meta TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS command_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    skill TEXT,
    action TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS whatsapp_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    text TEXT NOT NULL,
    is_ai INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    weeks INTEGER NOT NULL,
    hours_per_week INTEGER NOT NULL,
    plan_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    week INTEGER NOT NULL,
    topic TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT,
    FOREIGN KEY(plan_id) REFERENCES user_plans(id)
);
CREATE TABLE IF NOT EXISTS order_sessions (
    session_id TEXT PRIMARY KEY,
    platform TEXT,
    query TEXT,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT UNIQUE NOT NULL, -- e.g. "Home", "Work"
    house_number TEXT,
    street_name TEXT,
    city TEXT,
    zipcode TEXT,
    landmark TEXT,
    lat REAL,
    lng REAL,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


class SqliteStore:
    def __init__(self, settings: Settings) -> None:
        self._path = settings.sqlite_path

    async def init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._path) as db:
            # 1. Create tables if they don't exist
            await db.executescript(SCHEMA)
            
            # 2. Migration: Add missing columns if table exists
            cur = await db.execute("PRAGMA table_info(addresses)")
            columns = [row[1] for row in await cur.fetchall()]
            
            missing = [
                ("house_number", "TEXT"),
                ("street_name", "TEXT"),
                ("zipcode", "TEXT"),
                ("landmark", "TEXT")
            ]
            
            for col_name, col_type in missing:
                if col_name not in columns:
                    logger.info("Migrating database: Adding column '%s' to 'addresses'", col_name)
                    await db.execute(f"ALTER TABLE addresses ADD COLUMN {col_name} {col_type}")
            
            await db.commit()

    async def set_preference(self, key: str, value: Any) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO preferences(key, value, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(value), datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def get_preference(self, key: str, default: Any = None) -> Any:
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute("SELECT value FROM preferences WHERE key=?", (key,))
            row = await cur.fetchone()
            if not row:
                return default
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return row[0]

    async def get_all_preferences(self) -> dict[str, Any]:
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute("SELECT key, value, updated_at FROM preferences ORDER BY updated_at DESC")
            rows = await cur.fetchall()
            out = {}
            for r in rows:
                try:
                    out[r[0]] = json.loads(r[1])
                except json.JSONDecodeError:
                    out[r[0]] = r[1]
            return out

    async def delete_preference(self, key: str) -> bool:
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute("DELETE FROM preferences WHERE key=?", (key,))
            await db.commit()
            return cur.rowcount > 0

    async def get_command_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve past command history from the database."""
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "SELECT text, skill, action, created_at FROM command_history "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cur.fetchall()
        return [
            {"text": r[0], "skill": r[1], "action": r[2], "created_at": r[3]}
            for r in rows
        ]

    async def add_alert_rule(self, rule_type: str, threshold: float | None, meta: dict[str, Any]) -> int:
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "INSERT INTO alert_rules(rule_type, threshold, meta, active, created_at) VALUES(?,?,?,?,?)",
                (
                    rule_type,
                    threshold,
                    json.dumps(meta),
                    1,
                    datetime.utcnow().isoformat(),
                ),
            )
            await db.commit()
            return int(cur.lastrowid)

    async def list_active_alerts(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "SELECT id, rule_type, threshold, meta FROM alert_rules WHERE active=1"
            )
            rows = await cur.fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r[0],
                    "rule_type": r[1],
                    "threshold": r[2],
                    "meta": json.loads(r[3] or "{}"),
                }
            )
        return out

    async def log_command(self, text: str, skill: str | None, action: str | None) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO command_history(text, skill, action, created_at) VALUES(?,?,?,?)",
                (text, skill, action, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def log_whatsapp_message(self, chat_id: str, sender: str, text: str, is_ai: bool = False) -> None:
        """Log a WhatsApp message (incoming or outgoing) to the database."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO whatsapp_history(chat_id, sender, text, is_ai, created_at) VALUES(?,?,?,?,?)",
                (chat_id, sender, text, 1 if is_ai else 0, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def get_whatsapp_history(self, chat_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Retrieve recent WhatsApp history for a specific chat."""
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "SELECT sender, text, is_ai, created_at FROM whatsapp_history "
                "WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
                (chat_id, limit),
            )
            rows = await cur.fetchall()
        # Return in chronological order
        return [
            {"sender": r[0], "text": r[1], "is_ai": bool(r[2]), "created_at": r[3]}
            for r in reversed(rows)
        ]

    async def save_order_session(self, session_id: str, platform: str | None, query: str | None, state: dict[str, Any]) -> None:
        """Save or update an active order session."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO order_sessions(session_id, platform, query, state_json, updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET platform=excluded.platform, query=excluded.query, state_json=excluded.state_json, updated_at=excluded.updated_at",
                (session_id, platform, query, json.dumps(state), datetime.now().isoformat()),
            )
            await db.commit()

    async def get_active_order_session(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve an active order session if it hasn't expired (e.g., 30 mins)."""
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "SELECT platform, query, state_json, updated_at FROM order_sessions WHERE session_id = ?",
                (session_id,),
            )
            row = await cur.fetchone()
            if not row:
                return None
            
            # Simple expiry check: 30 minutes
            updated_at = datetime.fromisoformat(row[3])
            if (datetime.now() - updated_at).total_seconds() > 1800:
                return None
                
            return {
                "platform": row[0],
                "query": row[1],
                "state": json.loads(row[2]),
            }

    async def clear_order_session(self, session_id: str) -> None:
        """Clear an order session after completion or cancellation."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute("DELETE FROM order_sessions WHERE session_id = ?", (session_id,))
            await db.commit()

    # ── Address Management ──────────────────────────────────────────────────

    async def add_address(self, label: str, city: str, lat: float, lng: float, 
                         house_number: str = "", street_name: str = "", 
                         zipcode: str = "", landmark: str = "", 
                         set_active: bool = False) -> None:
        async with aiosqlite.connect(self._path) as db:
            if set_active:
                await db.execute("UPDATE addresses SET is_active = 0")
            
            await db.execute(
                "INSERT INTO addresses(label, house_number, street_name, city, zipcode, landmark, lat, lng, is_active, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(label) DO UPDATE SET house_number=excluded.house_number, street_name=excluded.street_name, city=excluded.city, zipcode=excluded.zipcode, landmark=excluded.landmark, lat=excluded.lat, lng=excluded.lng, is_active=excluded.is_active",
                (label, house_number, street_name, city, zipcode, landmark, lat, lng, 1 if set_active else 0, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def get_addresses(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM addresses ORDER BY created_at DESC") as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def set_active_address(self, label: str) -> bool:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE addresses SET is_active = 0")
            cur = await db.execute("UPDATE addresses SET is_active = 1 WHERE label = ?", (label,))
            await db.commit()
            return cur.rowcount > 0

    async def get_active_address(self) -> dict[str, Any] | None:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM addresses WHERE is_active = 1 LIMIT 1") as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def delete_address(self, label: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("DELETE FROM addresses WHERE label = ?", (label,))
            await db.commit()
