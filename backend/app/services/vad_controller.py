"""Voice Activity Detection (VAD) controller for J.A.R.V.I.S.

Energy-based VAD that manages microphone recording based on speech activity.

Rules:
  1. Start recording when speech is detected (>200 ms of energy above threshold)
  2. Continue while speech is active
  3. Stop recording when silence > 1 second
  4. Ignore short noise bursts (<200 ms)
  5. Do not trigger on background noise
"""

from __future__ import annotations

import array
import logging
import queue
import struct
import threading
import time
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class VADState(str, Enum):
    IDLE = "IDLE"
    DETECTING = "DETECTING"  # Possible speech, waiting for 200ms confirmation
    RECORDING = "RECORDING"
    TRAILING_SILENCE = "TRAILING_SILENCE"  # Speech ended, waiting 1s to confirm


class VADSignal(str, Enum):
    START_RECORDING = "START_RECORDING"
    STOP_RECORDING = "STOP_RECORDING"
    CONTINUE = "CONTINUE"


class VADController:
    """Energy-based Voice Activity Detection controller.

    Monitors a stream of audio frames and emits signals:
        START_RECORDING  — when meaningful speech begins
        STOP_RECORDING   — when the user finishes speaking
        CONTINUE         — when state is unchanged
    """

    def __init__(
        self,
        *,
        energy_threshold: float = 300.0,
        speech_start_ms: int = 200,
        silence_stop_ms: int = 1000,
        noise_floor_samples: int = 30,
        sample_rate: int = 16000,
        frame_length: int = 512,
    ) -> None:
        self.energy_threshold = energy_threshold
        self.speech_start_ms = speech_start_ms
        self.silence_stop_ms = silence_stop_ms
        self.noise_floor_samples = noise_floor_samples
        self.sample_rate = sample_rate
        self.frame_length = frame_length

        self._state = VADState.IDLE
        self._speech_start_time: float = 0.0
        self._silence_start_time: float = 0.0
        self._noise_floor: float = 0.0
        self._noise_samples: list[float] = []
        self._calibrated = False

        # Collected audio frames during recording
        self._audio_buffer: list[bytes] = []

    @property
    def state(self) -> VADState:
        return self._state

    @property
    def is_recording(self) -> bool:
        return self._state in (VADState.RECORDING, VADState.TRAILING_SILENCE)

    def reset(self) -> None:
        """Reset VAD state back to IDLE."""
        self._state = VADState.IDLE
        self._speech_start_time = 0.0
        self._silence_start_time = 0.0
        self._audio_buffer.clear()

    def get_recorded_audio(self) -> bytes:
        """Return all audio frames collected during last recording session."""
        return b"".join(self._audio_buffer)

    def _rms_energy(self, pcm_bytes: bytes) -> float:
        """Calculate RMS energy of a PCM int16 audio frame."""
        n_samples = len(pcm_bytes) // 2
        if n_samples == 0:
            return 0.0
        samples = struct.unpack(f"<{n_samples}h", pcm_bytes[:n_samples * 2])
        sum_sq = sum(s * s for s in samples)
        return (sum_sq / n_samples) ** 0.5

    def _is_speech(self, energy: float) -> bool:
        """Determine if the energy level indicates speech."""
        threshold = max(self.energy_threshold, self._noise_floor * 2.5)
        return energy > threshold

    def _calibrate_noise_floor(self, energy: float) -> None:
        """Collect baseline noise floor samples during initial IDLE state."""
        if self._calibrated:
            return
        self._noise_samples.append(energy)
        if len(self._noise_samples) >= self.noise_floor_samples:
            self._noise_floor = sum(self._noise_samples) / len(self._noise_samples)
            self._calibrated = True
            logger.info("VAD noise floor calibrated: %.1f", self._noise_floor)

    def process_frame(self, pcm_bytes: bytes) -> VADSignal:
        """Process a single audio frame and return the VAD signal.

        Args:
            pcm_bytes: Raw PCM int16 audio bytes

        Returns:
            VADSignal indicating the current action
        """
        now = time.monotonic()
        energy = self._rms_energy(pcm_bytes)

        # Calibrate noise floor during idle
        if not self._calibrated:
            self._calibrate_noise_floor(energy)
            return VADSignal.CONTINUE

        speech = self._is_speech(energy)

        if self._state == VADState.IDLE:
            if speech:
                self._state = VADState.DETECTING
                self._speech_start_time = now
                self._audio_buffer.clear()
                self._audio_buffer.append(pcm_bytes)
            return VADSignal.CONTINUE

        elif self._state == VADState.DETECTING:
            self._audio_buffer.append(pcm_bytes)
            if speech:
                elapsed_ms = (now - self._speech_start_time) * 1000
                if elapsed_ms >= self.speech_start_ms:
                    # Confirmed speech — start recording
                    self._state = VADState.RECORDING
                    logger.info("VAD: Speech detected (%.0fms), START_RECORDING", elapsed_ms)
                    return VADSignal.START_RECORDING
                return VADSignal.CONTINUE
            else:
                # Short noise burst — go back to idle
                self._state = VADState.IDLE
                self._audio_buffer.clear()
                return VADSignal.CONTINUE

        elif self._state == VADState.RECORDING:
            self._audio_buffer.append(pcm_bytes)
            if not speech:
                self._state = VADState.TRAILING_SILENCE
                self._silence_start_time = now
            return VADSignal.CONTINUE

        elif self._state == VADState.TRAILING_SILENCE:
            self._audio_buffer.append(pcm_bytes)
            if speech:
                # User resumed speaking
                self._state = VADState.RECORDING
                return VADSignal.CONTINUE
            else:
                silence_ms = (now - self._silence_start_time) * 1000
                if silence_ms >= self.silence_stop_ms:
                    # Confirmed end of speech
                    self._state = VADState.IDLE
                    logger.info("VAD: Silence detected (%.0fms), STOP_RECORDING", silence_ms)
                    return VADSignal.STOP_RECORDING
                return VADSignal.CONTINUE

        return VADSignal.CONTINUE
