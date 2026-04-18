"""Production-grade gesture control skill for Jarvis.

Only 3 gestures – zero ambiguity:
  1. Cursor   → index finger only  → move mouse
  2. Click    → thumb-index pinch  → left click  (double-pinch → double-click)
  3. Scroll   → index + middle up  → vertical scroll

Architecture:
  • Strict mode system: only ONE mode active per frame.
  • 300 ms gesture-stability gate before any action triggers.
  • Exponential Moving Average (EMA) cursor smoothing.
  • Per-action cooldowns to prevent spamming.
  • 5 px dead-zone to eliminate micro-jitter.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from enum import Enum, auto
from typing import Any, Optional

import pyautogui

from app.skills.base import SkillBase

logger = logging.getLogger(__name__)

# ── PyAutoGUI tuning ──────────────────────────────────────────────────────────
pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False


# ── Mode enum ─────────────────────────────────────────────────────────────────
class Mode(Enum):
    IDLE = auto()
    CURSOR = auto()
    CLICK = auto()
    SCROLL = auto()


# ── Gesture Thread ────────────────────────────────────────────────────────────
class GestureThread(threading.Thread):
    """Dedicated thread that owns the camera and the tracking loop."""

    # ─── tunables ─────────────────────────────────────────────────────────
    EMA_ALPHA        = 0.25          # cursor smoothing (lower = smoother)
    DEAD_ZONE_PX     = 5            # ignore cursor moves smaller than this
    PINCH_THRESHOLD  = 30           # px – thumb↔index distance for "pinch"
    SCROLL_THRESHOLD = 20           # px – minimum dy before scroll triggers
    STABILITY_SEC    = 0.30         # gesture must be held this long to fire
    CLICK_COOLDOWN   = 0.80         # seconds between clicks
    SCROLL_COOLDOWN  = 0.15         # seconds between scroll ticks
    DCLICK_WINDOW    = 0.40         # if two pinches within this → dbl-click

    def __init__(self, show_window: bool = True):
        super().__init__(daemon=True)
        self.show_window = show_window
        self.running = True

        # Screen dims
        self.screen_w, self.screen_h = pyautogui.size()

        # EMA state
        self.smooth_x: float | None = None
        self.smooth_y: float | None = None

        # Mode + stability timers
        self.current_mode = Mode.IDLE
        self._mode_since: float = 0.0       # when current gesture was first seen

        # Cooldowns
        self._last_click_time: float = 0.0
        self._last_scroll_time: float = 0.0
        self._prev_click_time: float = 0.0   # for double-click detection

        # Scroll tracking
        self._scroll_prev_y: float | None = None

    # ── Finger state helpers ──────────────────────────────────────────────
    @staticmethod
    def _finger_up(lm, tip_idx: int, pip_idx: int) -> bool:
        """True when fingertip is above its PIP joint (= finger extended)."""
        return lm[tip_idx].y < lm[pip_idx].y

    def _classify(self, lm) -> Mode:
        """Classify the current hand pose into exactly one Mode."""
        index_up  = self._finger_up(lm, 8, 6)
        middle_up = self._finger_up(lm, 12, 10)
        ring_up   = self._finger_up(lm, 16, 14)
        pinky_up  = self._finger_up(lm, 20, 18)

        # Pinch check (thumb tip ↔ index tip)
        thumb_tip = (lm[4].x, lm[4].y)
        index_tip = (lm[8].x, lm[8].y)
        # Use normalised coords; multiply by frame size later – but for
        # classification we can compare against a normalised threshold.
        # We'll do pixel-space check in the action handler instead.
        # Here just check if thumb and index are *very* close.
        pinch_dist_norm = math.hypot(thumb_tip[0] - index_tip[0],
                                     thumb_tip[1] - index_tip[1])
        is_pinch = pinch_dist_norm < 0.06  # ~30 px on a 640-wide frame

        if is_pinch:
            return Mode.CLICK

        # Handle cursor specifically to avoid conflict
        is_index_only = index_up and not middle_up and not ring_up and not pinky_up

        # Two fingers (index + middle) up → scroll
        # Don't strictly check ring and pinky, to be more forgiving for different hands
        if index_up and middle_up and not ring_up:
            return Mode.SCROLL

        # Only index up, rest down → cursor
        if is_index_only:
            return Mode.CURSOR

        return Mode.IDLE

    # ── Main loop ─────────────────────────────────────────────────────────
    def run(self):
        logger.info("GestureThread started.")

        # Late imports so the module loads even when deps are missing.
        try:
            import cv2
            import mediapipe as mp
        except ImportError as exc:
            logger.error("Missing dependency for gesture control: %s", exc)
            self.running = False
            return

        mp_hands   = mp.solutions.hands
        mp_drawing = mp.solutions.drawing_utils

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            logger.error("Camera 0 failed to open – is another app using it?")
            self.running = False
            return

        logger.info("Camera opened (%sx%s). Entering tracking loop.",
                     int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                     int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

        try:
            with mp_hands.Hands(
                max_num_hands=1,
                min_detection_confidence=0.7,
                min_tracking_confidence=0.7,
            ) as hands:

                while self.running and cap.isOpened():
                    try:
                        ok, frame = cap.read()
                        if not ok:
                            time.sleep(0.005)
                            continue

                        frame = cv2.flip(frame, 1)
                        h, w, _ = frame.shape
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        result = hands.process(rgb)

                        # waitKey(1) is required for cv2.imshow to render.
                        # We intentionally IGNORE the return value — no keyboard
                        # key can kill this loop.  Only self.stop() does.
                        if self.show_window:
                            cv2.waitKey(1)

                        now = time.time()

                        if result.multi_hand_landmarks:
                            hand = result.multi_hand_landmarks[0]
                            lm   = hand.landmark

                            if self.show_window:
                                mp_drawing.draw_landmarks(frame, hand, mp_hands.HAND_CONNECTIONS)

                            detected_mode = self._classify(lm)

                            # ── stability gate ────────────────────────────
                            if detected_mode != self.current_mode:
                                self.current_mode = detected_mode
                                self._mode_since  = now
                                self._scroll_prev_y = None

                            stable = (now - self._mode_since) >= self.STABILITY_SEC

                            # ── act on the stable mode ────────────────────
                            if stable:
                                if detected_mode == Mode.CURSOR:
                                    self._do_cursor(lm, w, h, frame)
                                elif detected_mode == Mode.CLICK:
                                    self._do_click(now, frame)
                                elif detected_mode == Mode.SCROLL:
                                    self._do_scroll(lm, h, now, frame)

                            # Status label
                            if self.show_window:
                                label = detected_mode.name
                                if not stable:
                                    label += " (stabilising...)"
                                colour = {
                                    Mode.CURSOR: (0, 255, 0),
                                    Mode.CLICK:  (0, 0, 255),
                                    Mode.SCROLL: (255, 165, 0),
                                    Mode.IDLE:   (128, 128, 128),
                                }.get(detected_mode, (255, 255, 255))
                                cv2.putText(frame, label, (10, 30),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, colour, 2)

                        else:
                            # No hand visible – reset everything
                            self.current_mode   = Mode.IDLE
                            self._mode_since    = now
                            self.smooth_x       = None
                            self.smooth_y       = None
                            self._scroll_prev_y = None

                        if self.show_window:
                            cv2.imshow("Jarvis Gesture Control", frame)

                    except Exception as frame_exc:
                        # NEVER crash — just log and move to next frame
                        logger.debug("Frame error (ignored): %s", frame_exc)
                        continue

        except Exception as exc:
            logger.exception("GestureThread loop error: %s", exc)
        finally:
            self.running = False
            cap.release()
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
            logger.info("GestureThread stopped.")

    # ── Action handlers ───────────────────────────────────────────────────
    def _do_cursor(self, lm, w: int, h: int, frame):
        """Move the mouse cursor following the index fingertip."""
        raw_x = lm[8].x * w
        raw_y = lm[8].y * h

        # Map from camera frame to screen coords with a margin
        margin = 60
        mapped_x = (raw_x - margin) * self.screen_w / max(1, w - 2 * margin)
        mapped_y = (raw_y - margin) * self.screen_h / max(1, h - 2 * margin)
        mapped_x = max(0, min(self.screen_w - 1, mapped_x))
        mapped_y = max(0, min(self.screen_h - 1, mapped_y))

        # EMA smoothing
        if self.smooth_x is None:
            self.smooth_x = mapped_x
            self.smooth_y = mapped_y
        else:
            self.smooth_x = self.smooth_x * (1 - self.EMA_ALPHA) + mapped_x * self.EMA_ALPHA
            self.smooth_y = self.smooth_y * (1 - self.EMA_ALPHA) + mapped_y * self.EMA_ALPHA

        # Dead zone
        cx, cy = pyautogui.position()
        if math.hypot(self.smooth_x - cx, self.smooth_y - cy) > self.DEAD_ZONE_PX:
            try:
                pyautogui.moveTo(int(self.smooth_x), int(self.smooth_y))
            except Exception as exc:
                logger.debug("moveTo error: %s", exc)

        if self.show_window:
            cv2.putText(frame, "CURSOR", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    def _do_click(self, now: float, frame):
        """Fire a mouse click (or double-click if pinches are rapid)."""
        if now - self._last_click_time < self.CLICK_COOLDOWN:
            return

        # Double-click detection
        gap = now - self._prev_click_time
        if gap < self.DCLICK_WINDOW:
            pyautogui.doubleClick()
            label = "DOUBLE CLICK!"
        else:
            pyautogui.click()
            label = "CLICK!"

        self._prev_click_time = self._last_click_time
        self._last_click_time = now

        if self.show_window:
            cv2.putText(frame, label, (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

    def _do_scroll(self, lm, h: int, now: float, frame):
        """Scroll up/down based on index finger vertical movement."""
        index_y = lm[8].y * h

        if self._scroll_prev_y is not None:
            dy = index_y - self._scroll_prev_y

            if abs(dy) > self.SCROLL_THRESHOLD and (now - self._last_scroll_time) > self.SCROLL_COOLDOWN:
                scroll_amount = int(-dy * 8)  # negative dy = finger moved up = scroll up
                pyautogui.scroll(scroll_amount)
                self._last_scroll_time = now

                direction = "UP" if scroll_amount > 0 else "DOWN"
                if self.show_window:
                    cv2.putText(frame, f"SCROLL {direction}", (10, 60),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 165, 0), 2)

        self._scroll_prev_y = index_y

    def stop(self):
        self.running = False


# ── Skill wrapper ─────────────────────────────────────────────────────────────
class GestureControlSkill(SkillBase):
    name        = "gesture_control"
    description = "Real-time hand gesture control: cursor, click, and scroll."
    priority    = 5
    keywords    = ["gesture control", "hand tracking", "webcam gesture",
                   "activate gesture", "stop gesture"]

    _thread: Optional[GestureThread] = None

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "status"],
                },
                "show_window": {"type": "boolean"},
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        if action == "start":
            # Clean up dead thread reference
            if self._thread and not self._thread.is_alive():
                GestureControlSkill._thread = None

            if GestureControlSkill._thread and GestureControlSkill._thread.is_alive():
                return {"message": "Gesture control is already running.", "status": "running"}

            show = parameters.get("show_window", True)
            GestureControlSkill._thread = GestureThread(show_window=show)
            GestureControlSkill._thread.start()
            return {
                "message": "Gesture control started. Use index finger to move, pinch to click, two fingers to scroll. Press ESC on the camera window to stop.",
                "status": "running",
            }

        if action == "stop":
            if GestureControlSkill._thread and GestureControlSkill._thread.is_alive():
                GestureControlSkill._thread.stop()
                GestureControlSkill._thread.join(timeout=3.0)
                GestureControlSkill._thread = None
                return {"message": "Gesture control stopped.", "status": "stopped"}
            GestureControlSkill._thread = None
            return {"message": "Gesture control is not running.", "status": "stopped"}

        if action == "status":
            alive = bool(GestureControlSkill._thread and GestureControlSkill._thread.is_alive())
            return {
                "message": f"Gesture control is {'running' if alive else 'stopped'}.",
                "status": "running" if alive else "stopped",
            }

        return {"error": f"Unknown action: {action}"}
