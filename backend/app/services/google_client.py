"""Shared Google OAuth2 credential loading for Gmail, Calendar, Drive."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
]


def get_credentials(credentials_path: str, token_path: str) -> Credentials | None:
    if not credentials_path or not Path(credentials_path).is_file():
        logger.warning("Google credentials file not found: %s", credentials_path)
        return None
    creds: Credentials | None = None
    tok = Path(token_path)
    if tok.is_file():
        creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            tok.parent.mkdir(parents=True, exist_ok=True)
            with open(tok, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            return creds
        else:
            from app.config import get_settings
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            # Headless servers: user runs once locally with GOOGLE_OAUTH_LOCAL=1
            if get_settings().google_oauth_local:
                creds = flow.run_local_server(port=0)
            else:
                logger.warning(
                    "Set GOOGLE_OAUTH_LOCAL=true in .env and run auth once to create token at %s",
                    token_path,
                )
                return None
        tok.parent.mkdir(parents=True, exist_ok=True)
        with open(tok, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds
