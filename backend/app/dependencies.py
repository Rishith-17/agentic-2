"""Application-wide singletons (initialized on startup)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.core.memory.chroma_store import ChromaMemory
from app.core.memory.sqlite_store import SqliteStore
from app.core.skill_registry import SkillRegistry, load_skills
from app.core.skill_router import SkillRouter
from app.services.wake_porcupine import WakeWordService
from app.vision.controller import VisionController

_TOKEN_FILENAME = "jarvis_api.token"
_bearer_scheme = HTTPBearer(auto_error=False)


def _load_or_create_token(data_dir: Path) -> str:
    token_path = data_dir / _TOKEN_FILENAME
    if token_path.exists():
        token = token_path.read_text().strip()
        if token:
            return token

    token = secrets.token_urlsafe(32)
    data_dir.mkdir(parents=True, exist_ok=True)
    token_path.write_text(token)
    try:
        token_path.chmod(0o600)
    except Exception:
        pass
    return token


@dataclass
class AppState:
    settings: Settings
    registry: SkillRegistry
    router: SkillRouter
    sqlite: SqliteStore
    chroma: ChromaMemory
    client: httpx.AsyncClient = field(default_factory=lambda: httpx.AsyncClient(timeout=120.0))
    api_token: str = field(default="")
    wake: WakeWordService | None = field(default=None)
    whatsapp_process: Any | None = field(default=None)
    pending_replies: dict[str, dict[str, Any]] = field(default_factory=dict)
    food_order_state: dict[str, Any] = field(default_factory=dict)
    user_location: dict[str, Any] = field(default_factory=dict)
    whatsapp_qr: str = field(default="")
    vision: VisionController | None = field(default=None)


_state: AppState | None = None


def get_app_state() -> AppState:
    if _state is None:
        raise RuntimeError("App not initialized")
    return _state


def get_sqlite_store() -> SqliteStore:
    return get_app_state().sqlite


async def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    state = get_app_state()
    if not state.settings.auth_enabled:
        return

    if credentials is None or credentials.credentials != state.api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def init_app() -> AppState:
    global _state
    if _state is not None:
        return _state

    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    sqlite = SqliteStore(settings)
    await sqlite.init()

    chroma = ChromaMemory(settings)
    chroma.init()

    registry = SkillRegistry()
    load_skills(registry)
    router = SkillRouter(registry, settings)

    wake = None
    if settings.porcupine_access_key:
        wake = WakeWordService(
            access_key=settings.porcupine_access_key,
            keyword_path=settings.porcupine_keyword_path,
        )

    _state = AppState(
        settings=settings,
        registry=registry,
        router=router,
        sqlite=sqlite,
        chroma=chroma,
        api_token=_load_or_create_token(settings.data_dir),
        wake=wake,
    )
    _state.vision = VisionController(_state)
    return _state


async def shutdown_app() -> None:
    global _state
    if _state is not None:
        if _state.vision:
            await _state.vision.shutdown()
        await _state.client.aclose()
        _state = None
