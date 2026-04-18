"""Google Docs API skill for document creation and writing."""

from typing import Any
import logging

from googleapiclient.discovery import build

from app.config import get_settings
from app.services.google_client import get_credentials
from app.skills.base import SkillBase

logger = logging.getLogger(__name__)

class DocsSkill(SkillBase):
    name = "docs"
    description = "Provides capabilities to create documents, format basic text, and write content in Google Docs."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The title of the document"},
                "content": {"type": "string", "description": "The text content to insert"}
            },
            "required": ["title"]
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = get_settings()
        creds = get_credentials(settings.google_credentials_path, settings.google_token_path)
        
        if not creds:
            msg = (
                "Google Docs credentials are not configured. "
                "Set GOOGLE_CREDENTIALS_PATH and complete OAuth to enable live Docs automation."
            )
            return {
                "message": msg,
                "summary_text": msg,
                "success": True,
                "mode": "setup_required",
                "skill_type": "docs",
            }

        if action not in ["create_doc", "insert_text", "create_and_write"]:
            return {"error": f"Unknown action: {action}"}

        title = parameters.get("title")
        if not title:
            return {"error": "Document title must be provided."}

        docs_service = build("docs", "v1", credentials=creds)
        drive_service = build("drive", "v3", credentials=creds)

        try:
            def _find_doc_id(name: str) -> str | None:
                query = f"name='{name}' and mimeType='application/vnd.google-apps.document' and trashed=false"
                results = drive_service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
                items = results.get("files", [])
                if items:
                    return items[0]["id"]
                return None

            doc_id = _find_doc_id(title)
            
            if action in ["create_doc", "create_and_write"]:
                if not doc_id:
                    doc = docs_service.documents().create(body={"title": title}).execute()
                    doc_id = doc.get("documentId")
                
                if action == "create_doc":
                    return {"result": f"Document '{title}' created/found.", "document_id": doc_id}
            
            if action in ["insert_text", "create_and_write"]:
                if not doc_id:
                    return {"error": f"Document '{title}' not found. Try 'create_and_write' to create it first."}
                    
                content = parameters.get("content")
                if not content:
                    return {"error": "No content provided to insert."}
                
                # Fetch document to find end index
                document = docs_service.documents().get(documentId=doc_id).execute()
                body = document.get('body')
                content_elements = body.get('content')
                
                # The end of the document is the end index of the last element, minus 1
                end_index = content_elements[-1]['endIndex'] - 1
                if end_index < 1:
                    end_index = 1
                
                requests = [
                    {
                        "insertText": {
                            "location": {
                                "index": end_index,
                            },
                            "text": content + "\n"
                        }
                    }
                ]
                
                result = docs_service.documents().batchUpdate(
                    documentId=doc_id, body={"requests": requests}
                ).execute()
                
                return {
                    "result": f"Successfully wrote text to document '{title}'",
                    "replies": result.get("replies")
                }
                
        except Exception as e:
            logger.error("Google Docs API error: %s", e)
            return {"error": f"Failed to perform {action}: {str(e)}"}
