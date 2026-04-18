"""Offline TTS using pyttsx3 — runs in a dedicated ThreadPoolExecutor so it
never blocks the async event loop or starves other concurrent tasks.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger(__name__)

# Single-worker pool: pyttsx3 is not thread-safe; serialise all TTS calls.
_TTS_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")


def _speak_sync(text: str) -> bytes | None:
    """Blocking TTS synthesis — must only be called inside _TTS_EXECUTOR."""
    import pyttsx3

    engine = pyttsx3.init()
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out_path = Path(f.name)
        logger.info("TTS generating to: %s", out_path)
        engine.save_to_file(text, str(out_path))
        engine.runAndWait()

        if not out_path.exists():
            logger.error("TTS file not created at %s", out_path)
            return None

        data = out_path.read_bytes()
        logger.info("TTS generated %d bytes", len(data))
        out_path.unlink(missing_ok=True)
        return data
    except Exception as e:
        logger.warning("TTS save failed: %s — falling back to speak-only", e)
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass
        return None
    finally:
        try:
            engine.stop()
        except Exception:
            pass


async def speak_to_bytes(text: str) -> bytes | None:
    """Async wrapper: synthesise *text* to WAV bytes without blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_TTS_EXECUTOR, _speak_sync, text)


# Alias used by some callers
speak_text = speak_to_bytes
