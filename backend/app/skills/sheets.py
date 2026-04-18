"""Google Sheets API skill for data entry and reading."""

from typing import Any
import logging

from googleapiclient.discovery import build

from app.config import get_settings
from app.services.google_client import get_credentials
from app.skills.base import SkillBase

logger = logging.getLogger(__name__)

class SheetsSkill(SkillBase):
    name = "sheets"
    description = "Provides capabilities to create spreadsheets, read data, and append rows in Google Sheets."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "sheet_name": {"type": "string", "description": "The name of the spreadsheet"},
                "data": {
                    "type": "array",
                    "items": {"type": ["string", "number", "boolean"]},
                    "description": "Row data to append"
                }
            },
            "required": ["sheet_name"]
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = get_settings()
        creds = get_credentials(settings.google_credentials_path, settings.google_token_path)
        
        if not creds:
            return {"error": "Google credentials not configured or expired."}

        if action not in ["create_sheet", "append_row", "read_sheet"]:
            return {"error": f"Unknown action: {action}"}

        sheet_name = parameters.get("sheet_name")
        if not sheet_name:
            return {"error": "sheet_name must be provided."}

        sheets_service = build("sheets", "v4", credentials=creds)
        drive_service = build("drive", "v3", credentials=creds)

        try:
            # Helper to find file by name
            def _find_sheet_id(name: str) -> str | None:
                query = f"name='{name}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
                results = drive_service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
                items = results.get("files", [])
                if items:
                    return items[0]["id"]
                return None

            if action == "create_sheet":
                existing_id = _find_sheet_id(sheet_name)
                if existing_id:
                    return {"result": f"Spreadsheet '{sheet_name}' already exists.", "spreadsheet_id": existing_id}
                
                spreadsheet = {
                    "properties": {"title": sheet_name}
                }
                spreadsheet = sheets_service.spreadsheets().create(
                    body=spreadsheet,
                    fields="spreadsheetId"
                ).execute()
                return {"result": f"Created spreadsheet '{sheet_name}'", "spreadsheet_id": spreadsheet.get("spreadsheetId")}

            elif action == "append_row":
                data = parameters.get("data", [])
                if not data:
                    return {"error": "No data provided to append."}
                    
                sheet_id = _find_sheet_id(sheet_name)
                if not sheet_id:
                    # Auto-create if doesn't exist
                    spreadsheet = {"properties": {"title": sheet_name}}
                    res_create = sheets_service.spreadsheets().create(body=spreadsheet, fields="spreadsheetId").execute()
                    sheet_id = res_create.get("spreadsheetId")
                
                body = {"values": [data]}
                result = sheets_service.spreadsheets().values().append(
                    spreadsheetId=sheet_id,
                    range="A1",
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body=body
                ).execute()
                
                return {
                    "result": f"Appended row to '{sheet_name}'",
                    "updates": result.get("updates")
                }
                
            elif action == "read_sheet":
                sheet_id = _find_sheet_id(sheet_name)
                if not sheet_id:
                    return {"error": f"Spreadsheet '{sheet_name}' not found."}
                    
                result = sheets_service.spreadsheets().values().get(
                    spreadsheetId=sheet_id,
                    range="A1:Z50" # default read range
                ).execute()
                
                rows = result.get("values", [])
                return {
                    "result": f"Read {len(rows)} rows from '{sheet_name}'",
                    "data": rows
                }
                
        except Exception as e:
            logger.error("Google Sheets API error: %s", e)
            return {"error": f"Failed to perform {action}: {str(e)}"}
