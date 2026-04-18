"""Porcupine wake word listener (optional — requires access key)."""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class WakeWordService:
    """Background thread that calls on_wake when keyword is detected."""

    def __init__(
        self,
        access_key: str,
        keyword_path: str = "",
        sensitivity: float = 0.5,
    ) -> None:
        self._access_key = access_key
        self._keyword_path = keyword_path
        self._sensitivity = sensitivity
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self, on_wake: Callable[[], None]) -> bool:
        if not self._access_key:
            logger.info("Porcupine access key not set; wake word disabled")
            return False
        self._stop.clear()

        def run() -> None:
            try:
                import pvporcupine
                import sounddevice as sd
            except ImportError as e:
                logger.error("Wake word deps missing: %s", e)
                return

            try:
                if self._keyword_path:
                    porcupine = pvporcupine.create(
                        access_key=self._access_key,
                        keyword_paths=[self._keyword_path],
                        sensitivities=[self._sensitivity],
                    )
                else:
                    # Built-in keyword; train a custom "Jarvis" .ppn in Picovoice Console and set PORCUPINE_KEYWORD_PATH
                    porcupine = pvporcupine.create(access_key=self._access_key, keywords=["computer"])
            except Exception as e:
                logger.error("Porcupine init failed: %s", e)
                return

            try:
                frame_len = porcupine.frame_length
                sample_rate = porcupine.sample_rate
                q: queue.Queue[bytes] = queue.Queue()

                def audio_cb(indata, frames, time_info, status) -> None:  # type: ignore[no-untyped-def]
                    if status:
                        logger.debug("Audio status: %s", status)
                    q.put(bytes(indata))

                stream = sd.RawInputStream(
                    samplerate=sample_rate,
                    blocksize=frame_len,
                    dtype="int16",
                    channels=1,
                    callback=audio_cb,
                )
                with stream:
                    while not self._stop.is_set():
                        try:
                            pcm = q.get(timeout=0.5)
                        except queue.Empty:
                            continue
                        import array

                        arr = array.array("h")
                        arr.frombytes(pcm)
                        if porcupine.process(arr) >= 0:
                            on_wake()
            finally:
                porcupine.delete()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
