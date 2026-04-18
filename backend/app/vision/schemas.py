"""Schemas shared by the vision backend and overlay UI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


VisionMode = Literal["passive", "active"]
VisionUrgency = Literal["low", "medium", "high"]
SuggestionKind = Literal["warning", "action", "info", "next_step"]
VisionPriority = Literal["critical", "actionable", "passive"]


class VisionHighlight(BaseModel):
    label: str = ""
    x: float = Field(default=0.0, ge=0.0, le=1.0)
    y: float = Field(default=0.0, ge=0.0, le=1.0)
    width: float = Field(default=0.0, ge=0.0, le=1.0)
    height: float = Field(default=0.0, ge=0.0, le=1.0)
    pulse: bool = False


class VisionSuggestion(BaseModel):
    title: str
    text: str
    anchor: str = "right"
    kind: SuggestionKind = "info"


class VisionHintPayload(BaseModel):
    summary: str = "Jarvis is ready."
    urgency: VisionUrgency = "low"
    priority: VisionPriority = "passive"
    action_required: bool = False
    no_action: bool = False
    suggestions: list[VisionSuggestion] = Field(default_factory=list)
    highlights: list[VisionHighlight] = Field(default_factory=list)
    mode: VisionMode = "passive"
    follow_up: str = ""
    model: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class VisionState(BaseModel):
    enabled: bool = False
    mode: VisionMode = "passive"
    active_reason: str = ""
    voice_enabled: bool = False
    click_through: bool = False
    last_frame_at: str | None = None
    last_error: str = ""
    processing: bool = False
    attention: bool = False
    last_diff_score: float = 0.0
    skipped_frames: int = 0
    latest: VisionHintPayload = Field(default_factory=VisionHintPayload)


class VisionStartRequest(BaseModel):
    mode: VisionMode = "passive"
    user_query: str = ""
    reason: str = ""


class VisionActivateRequest(BaseModel):
    phrase: str = ""


class VisionOverlaySettings(BaseModel):
    click_through: bool = False
