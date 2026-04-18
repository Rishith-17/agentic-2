"""Screen capture helpers for Vision Mode."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

try:
    import dxcam  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    dxcam = None

try:
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Image = None

try:
    import mss  # type: ignore
    import mss.tools  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    mss = None


@dataclass(slots=True)
class CapturedFrame:
    png_bytes: bytes
    base64_image: str
    width: int
    height: int
    captured_at: str
    diff_signature: list[int]


class ScreenCaptureService:
    """Captures the current primary display entirely in memory."""

    def __init__(self) -> None:
        self._dxcam = None
        if dxcam is not None:
            try:
                self._dxcam = dxcam.create(output_color="RGB")
            except Exception:
                self._dxcam = None

    def capture(self) -> CapturedFrame:
        if self._dxcam is not None and Image is not None:
            frame = self._dxcam.grab()
            if frame is not None:
                image = Image.fromarray(frame)
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                payload = buf.getvalue()
                return CapturedFrame(
                    png_bytes=payload,
                    base64_image=base64.b64encode(payload).decode("ascii"),
                    width=image.width,
                    height=image.height,
                    captured_at=datetime.now(timezone.utc).isoformat(),
                    diff_signature=self._signature_from_image(image),
                )

        if mss is None:
            raise RuntimeError(
                "Vision Mode requires the 'mss' package for screen capture. "
                "Install it in backend/.venv with: pip install mss"
            )

        with mss.mss() as sct:
            monitor = sct.monitors[1]
            shot = sct.grab(monitor)
            payload = mss.tools.to_png(shot.rgb, shot.size)
            return CapturedFrame(
                png_bytes=payload,
                base64_image=base64.b64encode(payload).decode("ascii"),
                width=shot.width,
                height=shot.height,
                captured_at=datetime.now(timezone.utc).isoformat(),
                diff_signature=self._signature_from_rgb_bytes(shot.rgb, shot.size),
            )

    def _signature_from_image(self, image) -> list[int]:
        if Image is None:
            return []
        small = image.convert("L").resize((24, 24))
        return list(np.asarray(small, dtype=np.uint8).flatten())

    def _signature_from_rgb_bytes(self, rgb: bytes, size: tuple[int, int]) -> list[int]:
        if Image is None:
            return []
        image = Image.frombytes("RGB", size, rgb)
        return self._signature_from_image(image)
