"""Voice trigger listener for Vision Mode."""

from __future__ import annotations

import asyncio
from collections import deque
import io
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np

try:
    import sounddevice as sd  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    sd = None

try:
    import soundfile as sf  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    sf = None

from app.services.stt_whisper import transcribe_upload_bytes

logger = logging.getLogger(__name__)


class VoiceTriggerService:
    """Continuously listens for short phrases and toggles Vision Mode."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self, on_phrase: Callable[[str], None]) -> bool:
        if sd is None or sf is None:
            logger.warning("Vision voice listener unavailable: install sounddevice and soundfile to enable it")
            return False

        if self._thread and self._thread.is_alive():
            return True

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._listen_loop, args=(on_phrase,), daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

    def _listen_loop(self, on_phrase: Callable[[str], None]) -> None:
        samplerate = 16000
        chunk_seconds = 0.32
        rolling: deque[np.ndarray] = deque(maxlen=5)
        cooldown_until = 0.0

        while not self._stop_event.is_set():
            try:
                audio = sd.rec(int(chunk_seconds * samplerate), samplerate=samplerate, channels=1, dtype="float32")
                sd.wait()
                if self._rms(audio) < 0.01:
                    continue

                rolling.append(audio.copy())
                if time.time() < cooldown_until or len(rolling) < 3:
                    continue

                merged = np.concatenate(list(rolling), axis=0)
                transcript = asyncio.run(self._transcribe(merged))
                text = transcript.lower().strip()
                if "jarvis, look at this" in text or "jarvis look at this" in text:
                    on_phrase("jarvis, look at this")
                    cooldown_until = time.time() + 1.5
                elif "jarvis, help me" in text or "jarvis help me" in text:
                    on_phrase("jarvis, help me")
                    cooldown_until = time.time() + 1.5
                elif "jarvis, stop watching" in text or "jarvis stop watching" in text:
                    on_phrase("jarvis, stop watching")
                    cooldown_until = time.time() + 1.5
            except Exception as exc:
                logger.debug("Vision voice listener cycle failed: %s", exc)
                time.sleep(0.25)

    async def _transcribe(self, audio: np.ndarray) -> str:
        if sf is None:
            raise RuntimeError("Vision voice listener requires the 'soundfile' package")
        buf = io.BytesIO()
        sf.write(buf, audio, 16000, format="WAV")
        return await transcribe_upload_bytes(buf.getvalue(), self._settings)

    @staticmethod
    def _rms(audio: np.ndarray) -> float:
        return float(np.sqrt(np.mean(np.square(audio))))
