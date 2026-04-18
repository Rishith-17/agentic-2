"""Google Drive list, upload, download, search; document summarization."""

from __future__ import annotations

import io
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

from app.config import get_settings
from app.services import llm
from app.services.google_client import get_credentials
from app.skills.base import SkillBase


class DriveSkill(SkillBase):
    name = "drive"
    description = "List, upload, download, search Drive files; summarize text documents."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list_files", "upload", "download", "search", "summarize_document"],
                },
                "query": {"type": "string"},
                "local_path": {"type": "string"},
                "file_id": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        s = get_settings()
        creds = get_credentials(s.google_credentials_path, s.google_token_path)
        if not creds:
            return {"message": "Configure Google OAuth (see README)"}

        svc = build("drive", "v3", credentials=creds, cache_discovery=False)

        if action == "list_files":
            res = (
                svc.files()
                .list(pageSize=20, fields="files(id, name, mimeType, modifiedTime)")
                .execute()
            )
            files = res.get("files", [])
            lines = [f"- {f['name']} ({f['id']})" for f in files]
            msg = "\n".join(lines) or "No files"
            return {"message": msg, "summary_text": msg, "files": files}

        if action == "search":
            q = parameters.get("query") or ""
            res = (
                svc.files()
                .list(q=f"fullText contains '{q}'", pageSize=15, fields="files(id, name)")
                .execute()
            )
            files = res.get("files", [])
            msg = "\n".join(f"- {f['name']}" for f in files) or "No matches"
            return {"message": msg, "summary_text": msg}

        if action == "upload":
            path = parameters.get("local_path") or ""
            name = parameters.get("name") or path
            media = MediaFileUpload(path, resumable=True)
            f = svc.files().create(body={"name": name}, media_body=media, fields="id").execute()
            return {"message": f"Uploaded id {f.get('id')}"}

        if action == "download":
            fid = parameters.get("file_id")
            if not fid:
                return {"message": "file_id required"}
            req = svc.files().get_media(fileId=fid)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            data = fh.getvalue()[:50000]
            text = data.decode("utf-8", errors="replace")
            return {"message": "Downloaded", "content": text}

        if action == "summarize_document":
            fid = parameters.get("file_id")
            if not fid:
                return {"message": "file_id required"}
            meta = svc.files().get(fileId=fid, fields="mimeType,name").execute()
            if "google-apps" in meta.get("mimeType", ""):
                return {"message": "Export Google Docs via Drive API export is not implemented in this path"}
            req = svc.files().get_media(fileId=fid)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            text = fh.getvalue().decode("utf-8", errors="replace")[:12000]
            plan = await llm.plan_intent(f"Summarize this document:\n\n{text}", settings=s)
            reply = plan.get("reply_text") or ""
            return {"summary_text": reply, "message": reply}

        return {"message": f"Unknown action {action}"}
