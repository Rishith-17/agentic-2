"""Gesture control skill for Jarvis using MediaPipe."""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Optional

import pyautogui

from app.skills.base import SkillBase

logger = logging.getLogger(__name__)

# Reduce PyAutoGUI delay for smoother cursor tracking
pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False  # Disabled temporarily to allow reaching screen bounds


class GestureThread(threading.Thread):
    def __init__(self, show_window: bool = True):
        super().__init__()
        self.show_window = show_window
        self.running = True
        
        # Cooldown management (prevent spamming actions)
        self.cooldown_until = 0.0
        self.pinch_cooldown = 0.0
        
        # Screen dimensions
        self.screen_w, self.screen_h = pyautogui.size()
        
        # Moving Average Filter state
        self.cursor_history_x = []
        self.cursor_history_y = []
        self.history_size = 5
        
        # Tracking states
        self.prev_palm_x = None
        self.prev_palm_y = None
        
        # Distance and motion thresholds
        self.dead_zone = 20
        self.swipe_threshold = 50

    def calculate_distance(self, p1: tuple[int, int], p2: tuple[int, int]) -> float:
        return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

    def update_cursor(self, x: int, y: int, frame_w: int, frame_h: int) -> None:
        # Increase effective area by using a margin
        margin = 80
        mapped_x = int((x - margin) * self.screen_w / max(1, (frame_w - 2 * margin)))
        mapped_y = int((y - margin) * self.screen_h / max(1, (frame_h - 2 * margin)))
        
        # Constrain to screen boundary
        mapped_x = max(0, min(self.screen_w - 1, mapped_x))
        mapped_y = max(0, min(self.screen_h - 1, mapped_y))
        
        self.cursor_history_x.append(mapped_x)
        self.cursor_history_y.append(mapped_y)
        
        # Keep recent history to smooth jitter
        if len(self.cursor_history_x) > self.history_size:
            self.cursor_history_x.pop(0)
            self.cursor_history_y.pop(0)
            
        avg_x = int(sum(self.cursor_history_x) / len(self.cursor_history_x))
        avg_y = int(sum(self.cursor_history_y) / len(self.cursor_history_y))
        
        # Dead zone to prevent micro-jitter
        current_mouse_x, current_mouse_y = pyautogui.position()
        if math.hypot(avg_x - current_mouse_x, avg_y - current_mouse_y) > 5:
            try:
                pyautogui.moveTo(avg_x, avg_y)
            except Exception as e:
                logger.error("Cursor movement error: %s", e)

    def is_index_raised(self, lm: Any) -> bool:
        # Index tip (8) is higher than PIP (6)
        index_up = lm[8].y < lm[6].y
        # Middle, Ring, Pinky should be folded down
        middle_down = lm[12].y > lm[10].y
        ring_down = lm[16].y > lm[14].y
        pinky_down = lm[20].y > lm[18].y
        return index_up and middle_down and ring_down and pinky_down

    def is_open_palm(self, lm: Any) -> bool:
        return (lm[8].y < lm[6].y) and (lm[12].y < lm[10].y) and \
               (lm[16].y < lm[14].y) and (lm[20].y < lm[18].y)

    def is_fist(self, lm: Any) -> bool:
        return (lm[8].y > lm[6].y) and (lm[12].y > lm[10].y) and \
               (lm[16].y > lm[14].y) and (lm[20].y > lm[18].y)

    def run(self):
        logger.info("GestureThread: Thread started.")
        try:
            import cv2
            import mediapipe as mp
            logger.info("GestureThread: Successfully imported cv2 and mediapipe.")
        except ImportError as e:
            logger.error(f"GestureThread: Import failed: {e}. opencv-python and mediapipe must be installed.")
            self.running = False
            return
        except Exception as e:
            logger.exception(f"GestureThread: Unexpected import error: {e}")
            self.running = False
            return

        try:
            mp_hands = mp.solutions.hands
            mp_drawing = mp.solutions.drawing_utils
            logger.info("GestureThread: MediaPipe solutions initialized.")
        except Exception as e:
            logger.exception(f"GestureThread: Failed to initialize MediaPipe solutions: {e}")
            self.running = False
            return

        # Capture from default webcam
        logger.info("GestureThread: Attempting to open camera 0...")
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            logger.error("GestureThread: VideoCapture(0) failed to open. Check if camera is used by another app.")
            self.running = False
            return
            
        logger.info(f"GestureThread: Camera opened. Resolution: {cap.get(cv2.CAP_PROP_FRAME_WIDTH)}x{cap.get(cv2.CAP_PROP_FRAME_HEIGHT)}")
        
        try:
            with mp_hands.Hands(
                max_num_hands=2,
                min_detection_confidence=0.7,
                min_tracking_confidence=0.7
            ) as hands:
                logger.info("GestureThread: MediaPipe Hands model loaded. Entering loop.")
                while self.running and cap.isOpened():
                    success, frame = cap.read()
                    if not success:
                        logger.warning("GestureThread: Failed to read frame from camera.")
                        time.sleep(0.01)
                        continue

                    # Mirror frame for natural interaction
                    frame = cv2.flip(frame, 1)
                    h, w, c = frame.shape
                    
                    # MediaPipe works with RGB
                    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = hands.process(img_rgb)
                    
                    # Check keyboard ESC kill switch if window is shown
                    if self.show_window:
                        key = cv2.waitKey(1) & 0xFF
                        if key == 27:  # ESC
                            logger.info("GestureThread: Kill switch (ESC) activated.")
                            self.running = False
                            break

                    current_time = time.time()
                    
                    if results.multi_hand_landmarks:
                        # 🛑 Kill Switch: two closed fists
                        if len(results.multi_hand_landmarks) == 2:
                            fists = sum(1 for hl in results.multi_hand_landmarks if self.is_fist(hl.landmark))
                            if fists == 2:
                                logger.info("Kill switch (Two Fists) activated.")
                                self.running = False
                                break

                        # Process the first detected hand
                        hand_landmarks = results.multi_hand_landmarks[0]
                        lm = hand_landmarks.landmark
                    
                    if self.show_window:
                        mp_drawing.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)
                        
                    # Extract pixel coordinates
                    thumb_tip = (int(lm[4].x * w), int(lm[4].y * h))
                    index_tip = (int(lm[8].x * w), int(lm[8].y * h))
                    palm_center = (int(lm[9].x * w), int(lm[9].y * h))
                    
                    # 1. Cursor Mode
                    if self.is_index_raised(lm):
                        self.update_cursor(index_tip[0], index_tip[1], w, h)
                        if self.show_window:
                            cv2.putText(frame, "Cursor Mode Active", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    else:
                        self.cursor_history_x.clear()
                        self.cursor_history_y.clear()

                    # 2. Pinch Detection (Click)
                    pinch_dist = self.calculate_distance(thumb_tip, index_tip)
                    if pinch_dist < 40 and current_time > self.pinch_cooldown:
                        pyautogui.click()
                        self.pinch_cooldown = current_time + 0.8  # Cooldown
                        if self.show_window:
                            cv2.putText(frame, "Click!", (index_tip[0], index_tip[1] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    
                    # Execute gestures only if past global cooldown
                    if current_time > self.cooldown_until:
                        # 3. Window Management (Open hand vs. Fist)
                        if self.is_open_palm(lm):
                            pyautogui.hotkey('win', 'down')
                            self.cooldown_until = current_time + 1.5
                            if self.show_window:
                                cv2.putText(frame, "Minimize", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 255), 2)
                        elif self.is_fist(lm):
                            pyautogui.hotkey('win', 'up')
                            self.cooldown_until = current_time + 1.5
                            if self.show_window:
                                cv2.putText(frame, "Maximize", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 255), 2)
                        else:
                            # 4. Motion Detection (Swipes)
                            if self.prev_palm_x is not None and self.prev_palm_y is not None:
                                dx = palm_center[0] - self.prev_palm_x
                                dy = palm_center[1] - self.prev_palm_y
                                
                                # Ignore dead zone movements for swipes
                                if math.hypot(dx, dy) > self.dead_zone:
                                    if abs(dx) > abs(dy):
                                        if dx > self.swipe_threshold:
                                            pyautogui.hotkey('ctrl', 'tab')  # Next tab
                                            self.cooldown_until = current_time + 1.0
                                            if self.show_window:
                                                cv2.putText(frame, "Swipe Right", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                                        elif dx < -self.swipe_threshold:
                                            pyautogui.hotkey('ctrl', 'shift', 'tab')  # Previous tab
                                            self.cooldown_until = current_time + 1.0
                                            if self.show_window:
                                                cv2.putText(frame, "Swipe Left", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                                    else:
                                        if dy < -self.swipe_threshold:
                                            pyautogui.scroll(500)  # Scroll Up
                                            self.cooldown_until = current_time + 0.5
                                            if self.show_window:
                                                cv2.putText(frame, "Swipe Up", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                                        elif dy > self.swipe_threshold:
                                            pyautogui.scroll(-500)  # Scroll Down
                                            self.cooldown_until = current_time + 0.5
                                            if self.show_window:
                                                cv2.putText(frame, "Swipe Down", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

                    self.prev_palm_x = palm_center[0]
                    self.prev_palm_y = palm_center[1]
                else:
                    # Hand lost tracking
                    self.prev_palm_x = None
                    self.prev_palm_y = None
                    self.cursor_history_x.clear()
                    self.cursor_history_y.clear()

                if self.show_window:
                    cv2.imshow("Jarvis Gesture Control", frame)

        except Exception as e:
            logger.exception(f"GestureThread: Error in tracking loop: {e}")
        finally:
            # Cleanup properly
            self.running = False
            if 'cap' in locals() and cap.isOpened():
                cap.release()
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

    def stop(self):
        self.running = False


class GestureControlSkill(SkillBase):
    name = "gesture_control"
    description = "Tracks hand movements via webcam to map natural gestures to desktop OS actions."
    priority = 5
    keywords = ["gesture control", "hand tracking", "webcam gesture", "activate gesture", "stop gesture"]

    _gesture_thread: Optional[GestureThread] = None

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform: start, stop, or status.",
                    "enum": ["start", "stop", "status"]
                },
                "show_window": {
                    "type": "boolean",
                    "description": "Show the webcam debug window (default True)."
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        if action == "start":
            if GestureControlSkill._gesture_thread and GestureControlSkill._gesture_thread.is_alive():
                return {"message": "Gesture control is already running.", "status": "running"}
            
            show_window = parameters.get("show_window", True)
            GestureControlSkill._gesture_thread = GestureThread(show_window)
            GestureControlSkill._gesture_thread.start()
            return {"message": "Gesture control started successfully. You can use your webcam to navigate.", "status": "running"}
            
        elif action == "stop":
            if GestureControlSkill._gesture_thread and GestureControlSkill._gesture_thread.is_alive():
                GestureControlSkill._gesture_thread.stop()
                GestureControlSkill._gesture_thread.join(timeout=2.0)
                GestureControlSkill._gesture_thread = None
                return {"message": "Gesture control stopped.", "status": "stopped"}
            return {"message": "Gesture control is not running.", "status": "stopped"}
            
        elif action == "status":
            is_running = bool(GestureControlSkill._gesture_thread and GestureControlSkill._gesture_thread.is_alive())
            return {
                "message": f"Gesture control is {'running' if is_running else 'stopped'}.",
                "status": "running" if is_running else "stopped"
            }

        return {"error": "Invalid action mapping."}
