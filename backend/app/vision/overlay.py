"""PyQt6 overlay UI for Jarvis Vision Mode."""

from __future__ import annotations

import json
import math
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class BackendClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("JARVIS_BACKEND_URL", "http://127.0.0.1:8765")
        self.token = os.getenv("JARVIS_API_TOKEN", self._read_repo_token())

    def _read_repo_token(self) -> str:
        token_path = Path(__file__).resolve().parents[3] / "data" / "jarvis_api.token"
        if token_path.exists():
            return token_path.read_text(encoding="utf-8").strip()
        return ""

    def get(self, path: str) -> dict:
        req = urllib.request.Request(f"{self.base_url}{path}", method="GET")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))

    def post(self, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))


class TypingLabel(QLabel):
    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self._full_text = text
        self._index = len(text)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_typed_text(self, text: str) -> None:
        if text == self._full_text and self.text():
            return
        self._full_text = text
        self._index = 0
        self.setText("")
        if not text:
            self._timer.stop()
            return
        self._timer.start(18)

    def _tick(self) -> None:
        self._index += 3
        self.setText(self._full_text[: self._index])
        if self._index >= len(self._full_text):
            self._timer.stop()


class PulseBorderOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._pulse = 0.0
        self._active = False
        self._attention = False
        self._highlights: list[dict] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_payload(self, payload: dict, active: bool) -> None:
        self._active = active
        self._attention = payload.get("attention", False)
        self._highlights = payload.get("latest", {}).get("highlights", [])
        geometry = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(geometry)
        if active:
            self.showFullScreen()
            if not self._timer.isActive():
                self._timer.start(45)
        else:
            self.hide()
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._pulse += 0.08
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._active:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(12, 12, -12, -12)
        glow_strength = 120 + int((95 if self._attention else 60) * (1 + math.sin(self._pulse)))
        border_color = QColor(128, 102, 255, min(255, glow_strength)) if self._attention else QColor(74, 163, 255, min(255, glow_strength))
        painter.setPen(QPen(border_color, 8 if self._attention else 7))
        painter.drawRoundedRect(rect, 28, 28)

        for item in self._highlights:
            x = int(item.get("x", 0) * self.width())
            y = int(item.get("y", 0) * self.height())
            w = int(item.get("width", 0) * self.width())
            h = int(item.get("height", 0) * self.height())
            if w <= 0 or h <= 0:
                continue
            pulse = bool(item.get("pulse"))
            alpha = 160 + int(80 * (1 + math.sin(self._pulse * 1.5))) if pulse else 190
            painter.setPen(QPen(QColor(125, 119, 255, min(255, alpha)), 4 if pulse else 3))
            painter.drawRoundedRect(QRect(x, y, w, h), 16, 16)
            label = item.get("label", "")
            if label:
                painter.drawText(x + 6, max(20, y - 8), label)


class SuggestionCard(QFrame):
    def __init__(self, title: str, text: str, anchor: str, kind: str) -> None:
        super().__init__()
        self.setObjectName("suggestionCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        badge = QLabel(kind.upper())
        badge.setObjectName("cardBadge")
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        title_label.setWordWrap(True)
        body_label = QLabel(f"{text}\n{anchor}")
        body_label.setObjectName("cardBody")
        body_label.setWordWrap(True)

        layout.addWidget(badge)
        layout.addWidget(title_label)
        layout.addWidget(body_label)

        opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(opacity)
        self._fade = QPropertyAnimation(opacity, b"opacity", self)
        self._fade.setDuration(220)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()


class VisionPanel(QWidget):
    def __init__(self, client: BackendClient) -> None:
        super().__init__()
        self.client = client
        self.current_state: dict = {}
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(360, 640)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 16)
        shadow.setColor(QColor(0, 0, 0, 160))

        root = QFrame(self)
        root.setObjectName("panelRoot")
        root.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 18, 14, 18)
        outer.addWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        self.status_dot = QLabel("READY")
        self.status_dot.setObjectName("statusDot")
        title = QLabel("Jarvis Vision")
        title.setObjectName("title")
        header.addWidget(self.status_dot)
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        self.summary = TypingLabel("Waiting for Vision Mode.")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("summary")
        layout.addWidget(self.summary)

        button_row = QHBoxLayout()
        self.toggle_button = QPushButton("Activate Vision")
        self.toggle_button.clicked.connect(self.toggle_vision)
        self.voice_button = QPushButton("Voice Trigger")
        self.voice_button.clicked.connect(self.toggle_voice)
        button_row.addWidget(self.toggle_button)
        button_row.addWidget(self.voice_button)
        layout.addLayout(button_row)

        self.click_checkbox = QCheckBox("Click-through overlay")
        self.click_checkbox.stateChanged.connect(self.toggle_click_through)
        layout.addWidget(self.click_checkbox)

        self.follow_up = TypingLabel("")
        self.follow_up.setObjectName("followUp")
        self.follow_up.setWordWrap(True)
        layout.addWidget(self.follow_up)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_host = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_host)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch()
        scroll.setWidget(self.cards_host)
        layout.addWidget(scroll, 1)

        self.setStyleSheet(
            """
            QWidget { color: #eef4ff; font-family: 'Segoe UI'; }
            #panelRoot {
              background: rgba(10, 18, 34, 200);
              border: 1px solid rgba(143, 191, 255, 90);
              border-radius: 28px;
            }
            #title { font-size: 22px; font-weight: 700; }
            #statusDot { color: #67d1ff; font-size: 14px; font-weight: 800; }
            #summary { font-size: 15px; color: rgba(238, 244, 255, 230); }
            #followUp { font-size: 13px; color: rgba(170, 200, 255, 220); }
            QPushButton {
              background: rgba(73, 137, 255, 180);
              border: 1px solid rgba(173, 220, 255, 110);
              border-radius: 16px;
              padding: 10px 14px;
              font-weight: 600;
            }
            QPushButton:hover { background: rgba(99, 156, 255, 210); }
            QCheckBox { spacing: 8px; color: rgba(221, 234, 255, 220); }
            #suggestionCard {
              background: rgba(255, 255, 255, 24);
              border: 1px solid rgba(157, 207, 255, 80);
              border-radius: 18px;
            }
            #cardTitle { font-size: 15px; font-weight: 700; }
            #cardBody { font-size: 13px; color: rgba(230, 238, 255, 210); }
            #cardBadge { color: #8ed8ff; font-size: 11px; font-weight: 700; }
            """
        )

        self._animation = QPropertyAnimation(self, b"geometry", self)
        self._animation.setDuration(340)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(260)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self.position_right()
        self._fade.start()
        self.show()

    def position_right(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        target = QRect(
            screen.right() - self.width() - 24,
            screen.top() + 40,
            self.width(),
            min(self.height(), screen.height() - 80),
        )
        if self.geometry().isNull():
            self.setGeometry(target)
        else:
            self._animation.stop()
            self._animation.setStartValue(self.geometry())
            self._animation.setEndValue(target)
            self._animation.start()

    def apply_state(self, payload: dict) -> None:
        self.current_state = payload
        latest = payload.get("latest", {})
        enabled = payload.get("enabled", False)
        no_action = latest.get("no_action", False) or latest.get("summary") == "NO_ACTION"
        summary_text = "Watching quietly." if no_action else latest.get("summary", "Waiting for Vision Mode.")
        follow_up = "" if no_action else latest.get("follow_up", "")

        self.summary.set_typed_text(summary_text)
        self.follow_up.set_typed_text(follow_up)
        self.toggle_button.setText("Stop Vision" if enabled else "Activate Vision")
        self.voice_button.setText("Stop Voice" if payload.get("voice_enabled") else "Voice Trigger")
        self.click_checkbox.blockSignals(True)
        self.click_checkbox.setChecked(payload.get("click_through", False))
        self.click_checkbox.blockSignals(False)

        attention = payload.get("attention", False)
        self.status_dot.setText("ACTIVE" if enabled else "READY")
        self.status_dot.setStyleSheet(
            "color: #ff90bd; font-size: 14px; font-weight: 800;"
            if attention
            else "color: #67d1ff; font-size: 14px; font-weight: 800;"
        )
        priority = (latest.get("priority") or "passive").upper()
        self._rebuild_cards([] if no_action else latest.get("suggestions", []), priority)

    def _rebuild_cards(self, suggestions: list[dict], priority: str) -> None:
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for suggestion in suggestions:
            card = SuggestionCard(
                suggestion.get("title", priority.title()),
                suggestion.get("text", ""),
                suggestion.get("anchor", "right"),
                suggestion.get("kind", "info"),
            )
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

    def toggle_vision(self) -> None:
        enabled = self.current_state.get("enabled", False)
        if enabled:
            self.client.post("/api/vision/stop")
        else:
            self.client.post("/api/vision/start", {"mode": "active", "reason": "overlay_button"})

    def toggle_voice(self) -> None:
        if self.current_state.get("voice_enabled"):
            self.client.post("/api/vision/voice/stop")
        else:
            self.client.post("/api/vision/voice/start")

    def toggle_click_through(self) -> None:
        self.client.post("/api/vision/overlay", {"click_through": self.click_checkbox.isChecked()})


class FloatingEyeButton(QWidget):
    def __init__(self, client: BackendClient) -> None:
        super().__init__()
        self.client = client
        self._enabled = False
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(88, 88)

        button = QPushButton("EYE", self)
        button.setGeometry(10, 10, 68, 68)
        button.clicked.connect(self._toggle)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            """
            QPushButton {
              background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 rgba(73, 137, 255, 230), stop:1 rgba(112, 92, 255, 230));
              border: 1px solid rgba(255, 255, 255, 90);
              border-radius: 34px;
              color: white;
              font-family: 'Segoe UI';
              font-size: 14px;
              font-weight: 700;
            }
            """
        )
        glow = QGraphicsDropShadowEffect(self)
        glow.setBlurRadius(28)
        glow.setOffset(0, 10)
        glow.setColor(QColor(93, 139, 255, 190))
        button.setGraphicsEffect(glow)
        self.button = button
        self.position_bottom_right()
        self.show()

    def position_bottom_right(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(QPoint(screen.right() - self.width() - 30, screen.bottom() - self.height() - 26))

    def set_enabled_state(self, enabled: bool) -> None:
        self._enabled = enabled
        self.button.setText("STOP" if enabled else "EYE")

    def set_attention_state(self, attention: bool) -> None:
        effect = self.button.graphicsEffect()
        if isinstance(effect, QGraphicsDropShadowEffect):
            effect.setBlurRadius(36 if attention else 28)
            effect.setColor(QColor(168, 104, 255, 220) if attention else QColor(93, 139, 255, 190))

    def _toggle(self) -> None:
        if self._enabled:
            self.client.post("/api/vision/stop")
        else:
            self.client.post("/api/vision/start", {"mode": "active", "reason": "floating_button"})


class VisionOverlayApp:
    def __init__(self) -> None:
        self.qt = QApplication(sys.argv)
        self.qt.setApplicationName("Jarvis Vision Mode")
        self.qt.setFont(QFont("Segoe UI", 10))
        self.client = BackendClient()
        self.panel = VisionPanel(self.client)
        self.button = FloatingEyeButton(self.client)
        self.border = PulseBorderOverlay()
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_state)
        self.timer.start(1000)
        self.refresh_state()

    def refresh_state(self) -> None:
        try:
            payload = self.client.get("/api/vision/status")
            self.panel.apply_state(payload)
            self.panel.position_right()
            self.button.set_enabled_state(payload.get("enabled", False))
            self.button.set_attention_state(payload.get("attention", False))
            self.button.position_bottom_right()
            self.border.set_payload(payload, payload.get("enabled", False))
        except urllib.error.URLError:
            fallback = {
                "enabled": False,
                "voice_enabled": False,
                "click_through": False,
                "attention": False,
                "latest": {
                    "summary": "Backend unavailable. Start FastAPI first, then reopen Vision Mode.",
                    "priority": "actionable",
                    "no_action": False,
                    "suggestions": [
                        {
                            "title": "Backend offline",
                            "text": "Run the Jarvis backend on port 8765.",
                            "anchor": "top-right",
                            "kind": "warning",
                        }
                    ],
                    "follow_up": "The overlay will reconnect automatically.",
                },
            }
            self.panel.apply_state(fallback)
            self.border.set_payload(fallback, False)

    def run(self) -> int:
        return self.qt.exec()


def main() -> int:
    app = VisionOverlayApp()
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
