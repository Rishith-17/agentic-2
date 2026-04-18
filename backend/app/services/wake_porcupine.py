"""Porcupine wake word listener with VAD + Speech-to-Command pipeline.

Flow:
  1. Listen continuously for wake word ("hello vibe")
  2. On wake word → activate VAD
  3. VAD detects speech start → begin recording
  4. VAD detects speech end (1s silence) → stop recording
  5. Send audio to STT (Whisper) → raw text
  6. Send text to Speech-to-Command processor → structured JSON
  7. Execute the command via skill router
"""

from __future__ import annotations

import asyncio
import io
import logging
import queue
import struct
import threading
import wave
from typing import Any, Callable

from app.services.vad_controller import VADController, VADSignal

logger = logging.getLogger(__name__)


class WakeWordService:
    """Background thread that listens for wake word, then captures speech via VAD."""

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
        self._on_command: Callable[[dict[str, Any]], None] | None = None

    def start(
        self,
        on_wake: Callable[[], None],
        on_command: Callable[[dict[str, Any]], None] | None = None,
    ) -> bool:
        """Start the wake word listener.

        Args:
            on_wake: Called when wake word is detected.
            on_command: Called with structured command JSON after speech processing.
        """
        if not self._access_key:
            logger.info("Porcupine access key not set; wake word disabled")
            return False
        self._stop.clear()
        self._on_command = on_command

        def run() -> None:
            try:
                import pvporcupine
                import sounddevice as sd
            except ImportError as e:
                logger.error("Wake word deps missing: %s", e)
                return

            try:
                keyword_file = self._keyword_path
                use_custom = False

                # Validate the .ppn file — WASM-compiled files don't work on desktop
                if keyword_file:
                    import os
                    if os.path.exists(keyword_file):
                        if "_wasm_" in os.path.basename(keyword_file).lower():
                            logger.warning(
                                "Keyword file '%s' is compiled for WASM (browser). "
                                "Falling back to built-in 'jarvis' keyword. "
                                "Train a Windows .ppn at https://console.picovoice.ai/",
                                keyword_file,
                            )
                        else:
                            use_custom = True
                    else:
                        logger.warning("Keyword file not found: %s", keyword_file)

                if use_custom:
                    porcupine = pvporcupine.create(
                        access_key=self._access_key,
                        keyword_paths=[keyword_file],
                        sensitivities=[self._sensitivity],
                    )
                    logger.info("Porcupine loaded custom keyword: %s", keyword_file)
                else:
                    # Try built-in keywords in preference order
                    for kw in ["jarvis", "computer", "alexa"]:
                        try:
                            porcupine = pvporcupine.create(
                                access_key=self._access_key,
                                keywords=[kw],
                            )
                            logger.info("Porcupine loaded built-in keyword: '%s'", kw)
                            break
                        except Exception as kw_err:
                            logger.warning(
                                "Porcupine keyword '%s' failed: %s — trying next...",
                                kw, str(kw_err)[:120],
                            )
                    else:
                        logger.error(
                            "All Porcupine keywords failed. "
                            "Check your PORCUPINE_ACCESS_KEY at https://console.picovoice.ai/"
                        )
                        return
            except Exception as e:
                logger.error("Porcupine init failed: %s", e)
                return

            vad = VADController(
                sample_rate=porcupine.sample_rate,
                frame_length=porcupine.frame_length,
            )

            try:
                frame_len = porcupine.frame_length
                sample_rate = porcupine.sample_rate
                q: queue.Queue[bytes] = queue.Queue()
                listening_for_command = False

                def audio_cb(indata, frames, time_info, status) -> None:
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
                    logger.info(
                        "Wake word listener active (rate=%d, frame=%d, keyword=%s)",
                        sample_rate, frame_len,
                        self._keyword_path or "built-in:computer",
                    )

                    while not self._stop.is_set():
                        try:
                            pcm = q.get(timeout=0.5)
                        except queue.Empty:
                            continue

                        import array as arr_mod
                        pcm_array = arr_mod.array("h")
                        pcm_array.frombytes(pcm)

                        if not listening_for_command:
                            # ── Phase 1: Wake word detection ──
                            if porcupine.process(pcm_array) >= 0:
                                logger.info("🎤 WAKE WORD DETECTED — listening for command...")
                                on_wake()
                                listening_for_command = True
                                vad.reset()
                        else:
                            # ── Phase 2: VAD-controlled recording ──
                            signal = vad.process_frame(pcm)

                            if signal == VADSignal.START_RECORDING:
                                logger.info("🔴 VAD: Recording speech...")

                            elif signal == VADSignal.STOP_RECORDING:
                                logger.info("⏹️ VAD: Speech ended — processing...")
                                listening_for_command = False

                                # Get recorded audio and process it
                                audio_data = vad.get_recorded_audio()
                                if audio_data and self._on_command:
                                    self._process_audio_async(
                                        audio_data, sample_rate, on_wake
                                    )
                                vad.reset()

            finally:
                porcupine.delete()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return True

    def _process_audio_async(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        on_wake: Callable[[], None],
    ) -> None:
        """Convert PCM audio → WAV → STT → Command JSON in a background thread."""

        def _work() -> None:
            try:
                # Convert raw PCM to WAV format for Whisper
                wav_buffer = io.BytesIO()
                with wave.open(wav_buffer, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)  # 16-bit
                    wf.setframerate(sample_rate)
                    wf.writeframes(audio_bytes)
                wav_data = wav_buffer.getvalue()

                # Run the async pipeline in a new event loop
                asyncio.run(self._run_speech_pipeline(wav_data))

            except Exception as exc:
                logger.error("Speech processing failed: %s", exc)

        threading.Thread(target=_work, daemon=True).start()

    async def _run_speech_pipeline(self, wav_data: bytes) -> None:
        """STT → Speech-to-Command → callback."""
        try:
            from app.dependencies import get_app_state
            from app.services.stt_whisper import transcribe_upload_bytes
            from app.services.speech_command_processor import process_speech_llm

            state = get_app_state()

            # Step 1: Transcribe audio
            transcript = await transcribe_upload_bytes(wav_data, state.settings)
            if not transcript or len(transcript.strip()) < 2:
                logger.info("STT returned empty/short transcript, ignoring")
                return

            logger.info("🗣️ Transcript: '%s'", transcript)

            # Step 2: Convert to structured command
            command = await process_speech_llm(transcript, state.settings)
            logger.info("⚡ Command: %s", command)

            # Step 3: Invoke callback with structured command
            if self._on_command and command.get("intent") != "empty":
                self._on_command(command)

        except Exception as exc:
            logger.error("Speech pipeline error: %s", exc)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
