"""Learning: track progress on a study plan stored in SQLite."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

from app.skills.base import SkillBase  # noqa: E402


class LearningProgressSkill(SkillBase):
    """Mark topics complete, view progress, or reset a study plan."""

    name        = "learning_progress"
    description = "Track and update progress on a saved study plan."
    priority    = 4
    keywords    = [
        "progress", "complete", "done", "finished", "status",
        "mark complete", "how far", "study progress",
    ]

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action":  {"type": "string", "enum": ["mark_complete", "view", "reset"]},
                "plan_id": {"type": "integer"},
                "week":    {"type": "integer"},
                "topic":   {"type": "string"},
            },
            "required": ["action", "plan_id"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        import aiosqlite
        from app.dependencies import get_app_state
        state   = get_app_state()
        db_path = state.sqlite._path
        plan_id = parameters.get("plan_id")

        if not plan_id:
            return {"message": "Please provide a plan_id."}

        # ── Mark complete ─────────────────────────────────────────────────────
        if action == "mark_complete":
            week  = parameters.get("week")
            topic = (parameters.get("topic") or "").strip()
            if not week or not topic:
                return {"message": "Please provide both 'week' and 'topic' to mark complete."}

            async with aiosqlite.connect(db_path) as db:
                cur = await db.execute(
                    "UPDATE learning_progress SET completed=1, completed_at=? "
                    "WHERE plan_id=? AND week=? AND topic=?",
                    (datetime.utcnow().isoformat(), plan_id, week, topic),
                )
                await db.commit()
                updated = cur.rowcount

            if updated == 0:
                return {
                    "message": (
                        f"Topic '{topic}' in week {week} not found for plan {plan_id}. "
                        "Check the topic name exactly."
                    )
                }

            # Compute overall progress
            pct, remaining = await _get_progress(db_path, plan_id)
            msg = (
                f"✅ Week {week}, '{topic}' marked complete. "
                f"You are {pct:.0f}% done with the plan. "
                f"{len(remaining)} topic(s) remaining."
            )
            return {"message": msg, "summary_text": msg, "skill_type": "learning",
                    "data": {"progress_pct": pct, "remaining": remaining}}

        # ── View progress ─────────────────────────────────────────────────────
        if action == "view":
            pct, remaining = await _get_progress(db_path, plan_id)
            async with aiosqlite.connect(db_path) as db:
                cur = await db.execute(
                    "SELECT week, topic, completed, completed_at "
                    "FROM learning_progress WHERE plan_id=? ORDER BY week, id",
                    (plan_id,),
                )
                rows = await cur.fetchall()

            if not rows:
                return {"message": f"No progress data found for plan {plan_id}."}

            lines = [f"📊 Plan {plan_id} — {pct:.0f}% complete\n"]
            current_week = None
            for week, topic, completed, completed_at in rows:
                if week != current_week:
                    lines.append(f"\nWeek {week}:")
                    current_week = week
                status = "✅" if completed else "⬜"
                date   = f" ({completed_at[:10]})" if completed and completed_at else ""
                lines.append(f"  {status} {topic}{date}")

            msg = "\n".join(lines)
            return {"message": msg, "summary_text": f"Plan {plan_id}: {pct:.0f}% complete.",
                    "skill_type": "learning",
                    "data": {"progress_pct": pct, "remaining": remaining}}

        # ── Reset progress ────────────────────────────────────────────────────
        if action == "reset":
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "UPDATE learning_progress SET completed=0, completed_at=NULL WHERE plan_id=?",
                    (plan_id,),
                )
                await db.commit()
            msg = f"Plan {plan_id} progress has been reset."
            return {"message": msg, "summary_text": msg}

        return {"message": f"Unknown action: {action}"}


# ── Helper ────────────────────────────────────────────────────────────────────

async def _get_progress(db_path, plan_id: int) -> tuple[float, list[str]]:
    """Return (completion_pct, list_of_remaining_topic_strings)."""
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT week, topic, completed FROM learning_progress WHERE plan_id=?",
            (plan_id,),
        )
        rows = await cur.fetchall()

    if not rows:
        return 0.0, []

    total     = len(rows)
    done      = sum(1 for _, _, c in rows if c)
    remaining = [f"Week {w}: {t}" for w, t, c in rows if not c]
    pct       = (done / total * 100) if total else 0.0
    return pct, remaining
