"""Speech-to-text using local Whisper."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_model: Any = None


def _get_model(settings: Any) -> Any:
    global _model
    if _model is None:
        import whisper

        _model = whisper.load_model(settings.whisper_model, device=settings.whisper_device)
    return _model


def transcribe_file(path: Path, settings: Any) -> str:
    model = _get_model(settings)
    result = model.transcribe(str(path))
    return (result.get("text") or "").strip()


async def transcribe_upload_bytes(data: bytes, settings: Any) -> str:
    import asyncio

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(data)
        tmp = Path(f.name)
    try:
        return await asyncio.to_thread(transcribe_file, tmp, settings)
    finally:
        tmp.unlink(missing_ok=True)
