"""Google Calendar events, agenda, and Meet link generation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from googleapiclient.discovery import build

from app.config import get_settings
from app.services.google_client import get_credentials
from app.skills.base import SkillBase

logger = logging.getLogger(__name__)


class CalendarSkill(SkillBase):
    name = "calendar"
    description = "Create events with Meet links, list schedule, daily agenda, delete/update events."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create_event",
                        "list_events",
                        "daily_agenda",
                        "delete_event",
                        "update_event",
                    ],
                },
                "title": {"type": "string"},
                "start_iso": {"type": "string"},
                "end_iso": {"type": "string"},
                "days": {"type": "integer"},
                "event_id": {"type": "string"},
                "attendees": {"type": "array", "items": {"type": "string"}},
                "description": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        s = get_settings()
        creds = get_credentials(s.google_credentials_path, s.google_token_path)
        if not creds:
            return {
                "message": "Google OAuth not configured.",
                "summary_text": "Google OAuth not configured.",
            }

        svc = build("calendar", "v3", credentials=creds, cache_discovery=False)

        # ── Create event with optional Meet link ──
        if action == "create_event":
            title = parameters.get("title") or "Meeting"
            start_iso = parameters.get("start_iso")
            end_iso = parameters.get("end_iso")
            
            # Default: 1 hour from now if no time specified
            now = datetime.now(timezone.utc)
            if not start_iso:
                start_time = now + timedelta(hours=1)
                start_iso = start_time.isoformat()
            if not end_iso:
                start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00")) if "Z" in start_iso else datetime.fromisoformat(start_iso)
                end_iso = (start_dt + timedelta(hours=1)).isoformat()

            body: dict[str, Any] = {
                "summary": title,
                "start": {"dateTime": start_iso, "timeZone": "Asia/Kolkata"},
                "end": {"dateTime": end_iso, "timeZone": "Asia/Kolkata"},
                "conferenceData": {
                    "createRequest": {
                        "requestId": f"jarvis-meet-{int(now.timestamp())}",
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                },
            }

            # Add attendees if provided
            attendees = parameters.get("attendees") or []
            if attendees:
                body["attendees"] = [{"email": e} for e in attendees]

            # Add description if provided
            desc = parameters.get("description")
            if desc:
                body["description"] = desc

            ev = (
                svc.events()
                .insert(
                    calendarId="primary",
                    body=body,
                    conferenceDataVersion=1,
                    sendUpdates="all" if attendees else "none",
                )
                .execute()
            )

            meet_link = ""
            conf_data = ev.get("conferenceData", {})
            entry_points = conf_data.get("entryPoints", [])
            for ep in entry_points:
                if ep.get("entryPointType") == "video":
                    meet_link = ep.get("uri", "")
                    break

            msg = f"📅 Event created: {title}\n🔗 Link: {ev.get('htmlLink', '?')}"
            if meet_link:
                msg += f"\n🎥 Meet: {meet_link}"
            if attendees:
                msg += f"\n👥 Invited: {', '.join(attendees)}"

            return {"message": msg, "summary_text": msg, "skill_type": "calendar", "meet_link": meet_link}

        # ── List upcoming events ──
        now = datetime.now(timezone.utc)
        if action == "list_events":
            days = int(parameters.get("days") or 7)
            end = now + timedelta(days=days)
            evs = (
                svc.events()
                .list(
                    calendarId="primary",
                    timeMin=now.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=20,
                )
                .execute()
            )
            items = evs.get("items", [])
            if not items:
                msg = f"No events in the next {days} days."
                return {"message": msg, "summary_text": msg, "skill_type": "calendar"}
            
            lines = []
            for it in items:
                start = it.get("start", {})
                dt_str = start.get("dateTime", start.get("date", "?"))
                lines.append(f"📅 {it.get('summary', '(untitled)')} — {dt_str}")
            
            msg = f"Upcoming events ({days} days):\n" + "\n".join(lines)
            return {"message": msg, "summary_text": msg, "skill_type": "calendar"}

        # ── Daily agenda ──
        if action == "daily_agenda":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            evs = (
                svc.events()
                .list(
                    calendarId="primary",
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            items = evs.get("items", [])
            if not items:
                msg = "Nothing scheduled for today. Your day is free!"
                return {"message": msg, "summary_text": msg, "skill_type": "calendar"}
            
            lines = [f"📅 {it.get('summary','?')} — {it.get('start',{}).get('dateTime','?')}" for it in items]
            msg = "Today's agenda:\n" + "\n".join(lines)
            return {"message": msg, "summary_text": msg, "skill_type": "calendar"}

        # ── Delete event ──
        if action == "delete_event":
            event_id = parameters.get("event_id")
            if not event_id:
                return {"message": "event_id required to delete.", "summary_text": "event_id required."}
            svc.events().delete(calendarId="primary", eventId=event_id).execute()
            msg = f"Event {event_id} deleted."
            return {"message": msg, "summary_text": msg, "skill_type": "calendar"}

        # ── Update event ──
        if action == "update_event":
            event_id = parameters.get("event_id")
            if not event_id:
                return {"message": "event_id required to update.", "summary_text": "event_id required."}
            
            ev = svc.events().get(calendarId="primary", eventId=event_id).execute()
            if parameters.get("title"):
                ev["summary"] = parameters["title"]
            if parameters.get("start_iso"):
                ev["start"] = {"dateTime": parameters["start_iso"], "timeZone": "Asia/Kolkata"}
            if parameters.get("end_iso"):
                ev["end"] = {"dateTime": parameters["end_iso"], "timeZone": "Asia/Kolkata"}
            
            updated = svc.events().update(calendarId="primary", eventId=event_id, body=ev).execute()
            msg = f"Event updated: {updated.get('summary')} — {updated.get('htmlLink')}"
            return {"message": msg, "summary_text": msg, "skill_type": "calendar"}

        return {"message": f"Unknown action: {action}", "summary_text": f"Unknown action: {action}"}
