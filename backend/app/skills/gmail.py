"""Gmail read, summarize, send, auto-reply with LLM."""

from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText
from typing import Any

from googleapiclient.discovery import build

from app.config import get_settings
from app.services import llm
from app.services.google_client import get_credentials
from app.skills.base import SkillBase

logger = logging.getLogger(__name__)


class GmailSkill(SkillBase):
    name = "gmail"
    description = "List messages, summarize inbox, send mail, auto-reply, draft replies."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list_messages",
                        "read_unread",
                        "summarize_inbox",
                        "send_email",
                        "draft_reply",
                        "auto_reply_all",
                        "send_reply",
                    ],
                },
                "max_results": {"type": "integer"},
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "message_id": {"type": "string"},
                "thread_id": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        s = get_settings()
        creds = get_credentials(s.google_credentials_path, s.google_token_path)
        if not creds:
            return {
                "message": "Google OAuth not configured. Please check credentials.json and complete OAuth flow.",
                "summary_text": "Google OAuth not configured. Please check credentials.json and complete OAuth flow.",
            }

        service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        # ── List all inbox messages ──
        if action == "list_messages":
            n = int(parameters.get("max_results") or 10)
            res = (
                service.users()
                .messages()
                .list(userId="me", maxResults=n, q="in:inbox")
                .execute()
            )
            msgs = res.get("messages", [])
            lines = []
            for m in msgs:
                full = service.users().messages().get(userId="me", id=m["id"], format="metadata").execute()
                headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
                lines.append(f"- {headers.get('subject', '(no subject)')} from {headers.get('from', 'unknown')}")
            msg = "\n".join(lines) or "No messages in inbox."
            return {"message": msg, "summary_text": msg, "skill_type": "email"}

        # ── Read unread emails only ──
        if action == "read_unread":
            n = int(parameters.get("max_results") or 10)
            res = (
                service.users()
                .messages()
                .list(userId="me", maxResults=n, q="in:inbox is:unread")
                .execute()
            )
            msgs = res.get("messages", [])
            if not msgs:
                msg = "No unread emails. Your inbox is clean!"
                return {"message": msg, "summary_text": msg, "skill_type": "email"}
            
            lines = []
            for m in msgs:
                full = service.users().messages().get(userId="me", id=m["id"], format="metadata").execute()
                headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
                snippet = full.get("snippet", "")[:80]
                lines.append(f"📧 {headers.get('subject', '(no subject)')}\n   From: {headers.get('from', 'unknown')}\n   {snippet}...")
            
            msg = f"You have {len(msgs)} unread email(s):\n\n" + "\n\n".join(lines)
            return {"message": msg, "summary_text": msg, "skill_type": "email"}

        # ── Summarize inbox with LLM ──
        if action == "summarize_inbox":
            res = service.users().messages().list(userId="me", maxResults=10, q="in:inbox").execute()
            texts = []
            for m in res.get("messages", []):
                full = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
                headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
                payload = full.get("payload", {})
                body = _extract_body(payload)
                sender = headers.get('from', '?')
                subject = headers.get('subject', '?')
                snippet = body[:500] if body else full.get("snippet", "")[:200]
                texts.append(f"From: {sender}\nSubject: {subject}\nSnippet: {snippet}")
            
            blob = "\n---\n".join(texts)
            
            # JSON-based summarization prompt
            summarization_prompt = f"""You are a data-structuring AI engine inside Jarvis.
Your job is NOT to generate formatted text.
Your job is to generate structured JSON data that will be rendered by the UI.

---
OBJECTIVE
- Convert raw input into structured, categorized data
- Make output clean, minimal, and machine-readable
- Do NOT produce UI formatting or paragraphs

---
OUTPUT FORMAT (STRICT JSON ONLY)
{{
  "title": "Inbox Summary",
  "sections": [
    {{
      "type": "important",
      "items": ["...", "..."]
    }},
    {{
      "type": "updates",
      "items": ["...", "..."]
    }},
    {{
      "type": "others",
      "items": ["...", "..."]
    }}
  ]
}}

---
RULES
- Return ONLY valid JSON
- No explanations, no extra text
- Each item must be ONE short sentence
- Max 6 items per section
- Combine similar emails into one item
- Remove email addresses unless critical
- Do NOT repeat similar content

---
INTELLIGENCE
Classify data into:
- important → alerts, payments, security, deadlines
- updates → product updates, offers, newsletters
- others → low priority or general messages

---
STRICT BEHAVIOR
- If output is not JSON, regenerate internally
- If input is noisy, clean it before structuring
- If data is unclear, summarize conservatively

---
FINAL GOAL
Provide structured data so the frontend can render a clean dashboard UI.
You are a backend data engine, not a UI generator.

---
EMAILS TO SUMMARIZE:

{blob}

---
Return ONLY the JSON structure:"""
            
            # Use chat directly for JSON-structured summarization
            reply = await llm.chat(
                [{"role": "user", "content": summarization_prompt}],
                settings=s,
                temperature=0.3,  # Lower temperature for more consistent JSON
                force_smart=True
            )
            
            if not reply or len(reply.strip()) < 10:
                return {
                    "summary_text": "Could not summarize emails. Please try again.",
                    "message": "Could not summarize emails. Please try again.",
                    "skill_type": "email"
                }
            
            # Try to parse JSON response
            try:
                import json
                # Clean the response - remove markdown code blocks if present
                cleaned = reply.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.startswith("```"):
                    cleaned = cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
                
                data = json.loads(cleaned)
                
                # Format the JSON data into a clean dashboard view
                formatted = f"📬 {data.get('title', 'INBOX SUMMARY')}\n"
                formatted += "─" * 40 + "\n\n"
                
                for section in data.get('sections', []):
                    section_type = section.get('type', '').upper()
                    items = section.get('items', [])
                    
                    if not items:
                        continue
                    
                    # Add emoji based on type
                    emoji = "📌" if section_type == "IMPORTANT" else "📊" if section_type == "UPDATES" else "📂"
                    formatted += f"{emoji} {section_type}\n"
                    
                    for item in items:
                        formatted += f"• {item}\n"
                    
                    formatted += "\n" + "─" * 40 + "\n\n"
                
                return {"summary_text": formatted, "message": formatted, "skill_type": "email"}
                
            except json.JSONDecodeError:
                # Fallback: return the raw response if JSON parsing fails
                logger.warning("Failed to parse JSON from LLM response, returning raw text")
                return {"summary_text": reply, "message": reply, "skill_type": "email"}

        # ── Send email ──
        if action == "send_email":
            to_addr = parameters.get("to") or ""
            subject = parameters.get("subject") or ""
            body = parameters.get("body") or ""
            if not to_addr:
                return {"message": "No recipient specified.", "summary_text": "No recipient specified."}
            
            raw = _create_raw(to_addr, subject, body)
            sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
            msg = f"Email sent successfully to {to_addr}. Message ID: {sent.get('id')}"
            return {"message": msg, "summary_text": msg, "skill_type": "email"}

        # ── Draft reply to a specific message ──
        if action == "draft_reply":
            mid = parameters.get("message_id")
            if not mid:
                return {"message": "message_id required", "summary_text": "message_id required"}
            full = service.users().messages().get(userId="me", id=mid, format="full").execute()
            headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
            body = _extract_body(full.get("payload", {}))
            
            plan = await llm.plan_intent(
                f"Draft a concise professional reply to this email. Just write the reply text, not JSON:\n\nFrom: {headers.get('from','?')}\nSubject: {headers.get('subject','?')}\n\n{body[:6000]}",
                settings=s,
            )
            draft_text = plan.get("reply_text") or ""
            msg = f"Draft reply generated:\n\n{draft_text}"
            return {"summary_text": msg, "message": msg, "skill_type": "email"}

        # ── Auto-reply to all unread emails ──
        if action == "auto_reply_all":
            n = int(parameters.get("max_results") or 5)
            res = (
                service.users()
                .messages()
                .list(userId="me", maxResults=n, q="in:inbox is:unread")
                .execute()
            )
            msgs = res.get("messages", [])
            if not msgs:
                msg = "No unread emails to reply to."
                return {"message": msg, "summary_text": msg, "skill_type": "email"}

            drafts = []
            for m in msgs:
                try:
                    full = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
                    headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
                    body_text = _extract_body(full.get("payload", {}))
                    sender = headers.get("from", "unknown")
                    subject = headers.get("subject", "(no subject)")
                    thread_id = full.get("threadId", "")

                    # Generate reply using LLM
                    plan = await llm.plan_intent(
                        f"Write a concise, professional reply to this email. Just write the reply body, not JSON:\n\nFrom: {sender}\nSubject: {subject}\n\n{body_text[:4000]}",
                        settings=s,
                    )
                    reply_text = plan.get("reply_text") or "Thank you for your email. I'll get back to you shortly."
                    
                    # Actually send the reply
                    reply_subject = f"Re: {subject}" if not subject.startswith("Re:") else subject
                    raw = _create_raw(sender, reply_subject, reply_text)
                    send_body = {"raw": raw, "threadId": thread_id}
                    service.users().messages().send(userId="me", body=send_body).execute()
                    
                    drafts.append(f"✅ Replied to: {sender}\n   Subject: {subject}\n   Reply: {reply_text[:100]}...")
                except Exception as e:
                    logger.error("Auto-reply failed for message %s: %s", m.get("id"), e)
                    drafts.append(f"❌ Failed to reply to message {m.get('id')}: {str(e)[:60]}")

            msg = f"Auto-replied to {len(drafts)} email(s):\n\n" + "\n\n".join(drafts)
            return {"message": msg, "summary_text": msg, "skill_type": "email"}

        # ── Send reply to a specific thread ──
        if action == "send_reply":
            thread_id = parameters.get("thread_id") or ""
            to_addr = parameters.get("to") or ""
            subject = parameters.get("subject") or ""
            body = parameters.get("body") or ""
            
            raw = _create_raw(to_addr, subject, body)
            send_body = {"raw": raw}
            if thread_id:
                send_body["threadId"] = thread_id
            sent = service.users().messages().send(userId="me", body=send_body).execute()
            msg = f"Reply sent to {to_addr}. Message ID: {sent.get('id')}"
            return {"message": msg, "summary_text": msg, "skill_type": "email"}

        return {"message": f"Unknown action: {action}", "summary_text": f"Unknown action: {action}"}


def _extract_body(payload: dict[str, Any]) -> str:
    parts = payload.get("parts") or []
    if parts:
        for p in parts:
            if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(p["body"]["data"]).decode("utf-8", errors="replace")
        # Try nested parts
        for p in parts:
            if p.get("parts"):
                result = _extract_body(p)
                if result:
                    return result
    data = payload.get("body", {}).get("data")
    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    return ""


def _create_raw(to: str, subject: str, body: str) -> str:
    msg = MIMEText(body)
    msg["to"] = to
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return raw
