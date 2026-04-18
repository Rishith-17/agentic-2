"""Learning: generate and store a week-by-week study plan using the LLM."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

from app.services import llm as llm_service  # noqa: E402
from app.services.llm import _extract_json   # noqa: E402  reuse robust extractor
from app.skills.base import SkillBase        # noqa: E402


class LearningStudyPlanSkill(SkillBase):
    """Generate a personalised week-by-week study plan and persist it in SQLite."""

    name        = "learning_study_plan"
    description = "Create a week-by-week study plan for any topic using available courses."
    priority    = 5
    keywords    = [
        "plan", "roadmap", "schedule", "study plan", "learning path",
        "week by week", "curriculum", "syllabus",
    ]

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action":         {"type": "string", "enum": ["create", "view"]},
                "topic":          {"type": "string"},
                "hours_per_week": {"type": "integer"},
                "weeks":          {"type": "integer"},
                "resources":      {"type": "array", "items": {"type": "string"}},
                "plan_id":        {"type": "integer"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        from app.dependencies import get_app_state
        state = get_app_state()

        # ── View existing plan ────────────────────────────────────────────────
        if action == "view":
            plan_id = parameters.get("plan_id")
            if not plan_id:
                # List all plans
                async with __import__("aiosqlite").connect(state.sqlite._path) as db:
                    cur = await db.execute(
                        "SELECT id, topic, weeks, hours_per_week, created_at FROM user_plans ORDER BY created_at DESC"
                    )
                    rows = await cur.fetchall()
                if not rows:
                    return {"message": "No study plans saved yet. Create one first."}
                lines = [f"• Plan {r[0]}: {r[1]} ({r[2]} weeks, {r[3]}h/week) — {r[4][:10]}" for r in rows]
                msg = "Your study plans:\n" + "\n".join(lines)
                return {"message": msg, "summary_text": msg, "skill_type": "learning"}

            async with __import__("aiosqlite").connect(state.sqlite._path) as db:
                cur = await db.execute("SELECT plan_json FROM user_plans WHERE id=?", (plan_id,))
                row = await cur.fetchone()
            if not row:
                return {"message": f"Plan {plan_id} not found."}
            plan_data = json.loads(row[0])
            return {
                "message":      _format_plan(plan_data),
                "summary_text": f"Study plan {plan_id} loaded.",
                "skill_type":   "learning",
                "data":         plan_data,
            }

        # ── Create plan ───────────────────────────────────────────────────────
        if action != "create":
            return {"message": f"Unknown action: {action}"}

        topic          = (parameters.get("topic") or "").strip()
        hours_per_week = int(parameters.get("hours_per_week") or 10)
        weeks          = int(parameters.get("weeks") or 8)
        resources      = parameters.get("resources") or []

        if not topic:
            return {"message": "Please provide a topic for the study plan."}

        # Fetch courses if no resources provided
        if not resources:
            try:
                from app.skills.learning_course_search import LearningCourseSearchSkill
                course_res = await LearningCourseSearchSkill().execute("search", {"topic": topic})
                courses    = (course_res.get("data") or {}).get("courses") or []
                resources  = [f"[{c['platform']}] {c['title']} — {c['url']}" for c in courses[:6]]
            except Exception as exc:
                logger.warning("Could not fetch courses for plan: %s", exc)
                resources = [f"Search for '{topic}' on NPTEL, Coursera, or YouTube"]

        resource_text = "\n".join(f"- {r}" for r in resources) if resources else "General online resources"

        prompt = (
            f"Create a {weeks}-week study plan for learning '{topic}' "
            f"with {hours_per_week} hours per week.\n"
            f"Available resources:\n{resource_text}\n\n"
            "Output ONLY a JSON object (no markdown) with this exact schema:\n"
            '{"weeks": [{"week": 1, "topics": ["topic1", "topic2"], '
            '"resources": ["resource1"], "hours": 10}, ...]}'
        )

        raw = ""
        try:
            plan_result = await llm_service.plan_intent(prompt)
            raw = plan_result.get("reply_text") or ""
            # The LLM may return the JSON directly in reply_text
            plan_json = _extract_json(raw)
        except Exception as exc:
            logger.warning("LLM plan generation failed: %s — building fallback plan", exc)
            plan_json = _build_fallback_plan(topic, weeks, hours_per_week, resources)

        # Validate structure
        if "weeks" not in plan_json or not isinstance(plan_json["weeks"], list):
            plan_json = _build_fallback_plan(topic, weeks, hours_per_week, resources)

        # Persist to SQLite
        async with __import__("aiosqlite").connect(state.sqlite._path) as db:
            cur = await db.execute(
                "INSERT INTO user_plans(topic, weeks, hours_per_week, plan_json, created_at) VALUES(?,?,?,?,?)",
                (topic, weeks, hours_per_week, json.dumps(plan_json), datetime.utcnow().isoformat()),
            )
            plan_id = cur.lastrowid
            # Seed progress rows
            for week_obj in plan_json.get("weeks", []):
                for t in week_obj.get("topics", []):
                    await db.execute(
                        "INSERT INTO learning_progress(plan_id, week, topic, completed) VALUES(?,?,?,0)",
                        (plan_id, week_obj.get("week", 0), t),
                    )
            await db.commit()

        formatted = _format_plan(plan_json)
        summary   = f"✅ Study plan created (ID: {plan_id}) for '{topic}' — {weeks} weeks, {hours_per_week}h/week."
        return {
            "message":      summary + "\n\n" + formatted,
            "summary_text": summary,
            "skill_type":   "learning",
            "data":         {"plan_id": plan_id, "plan": plan_json},
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_plan(plan_json: dict[str, Any]) -> str:
    lines = []
    for w in plan_json.get("weeks", []):
        lines.append(f"Week {w.get('week', '?')} ({w.get('hours', '?')}h):")
        for t in w.get("topics", []):
            lines.append(f"  • {t}")
        for r in w.get("resources", []):
            lines.append(f"    📚 {r}")
    return "\n".join(lines)


def _build_fallback_plan(
    topic: str, weeks: int, hours_per_week: int, resources: list[str]
) -> dict[str, Any]:
    """Simple evenly-distributed fallback when LLM fails."""
    week_list = []
    for i in range(1, weeks + 1):
        week_list.append({
            "week":      i,
            "topics":    [f"Week {i}: Study {topic} (part {i}/{weeks})"],
            "resources": resources[:2] if resources else [],
            "hours":     hours_per_week,
        })
    return {"weeks": week_list}
