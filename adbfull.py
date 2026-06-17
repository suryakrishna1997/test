from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtCore import Qt
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtGui import QIntValidator
from PyQt6.QtGui import (
    QPainter,
    QPen,
    QBrush,
    QColor,
    QLinearGradient,
    QRadialGradient,
    QFont,
    QPainterPath,
    QKeyEvent,
    QMouseEvent,
)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QGroupBox, QGridLayout, QVBoxLayout, QLabel, QFrame
from PyQt6.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QCheckBox,
    QPushButton,
    QWidget,
)
from PyQt6.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QMenu,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)
from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QSplitter,
    QMessageBox,
    QInputDialog,
    QScrollArea,
    QFrame,
)
from PyQt6.QtWidgets import QWidget
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Optional
import csv
import json
import math
import os
import subprocess
import sys
import threading
import time

# ============================================================
# File: recorder/event_types.py
# ============================================================
"""
event_types.py — Data models for recorded events and recording sessions.

Defines the core data structures used throughout the application:
  - RecordedEvent: A single captured user action (click, swipe, drag, key press)
  - Recording: A full session containing metadata and a list of events

All types are JSON-serializable for persistence and export.
"""


@dataclass
class RecordedEvent:
    """
    Represents a single recorded user action.

    Attributes:
        event_type: One of "click", "swipe", "drag", "key_press"
        timestamp:  Seconds elapsed since recording started
        data:       Type-specific payload dict:
                      click     → {"x": int, "y": int, "button": str}
                      swipe     → {"x1","y1","x2","y2": int, "duration_ms": int}
                      drag      → {"points": [{"x": int, "y": int, "t": float}, ...]}
                      key_press → {"key": str, "text": str, "modifiers": [str]}
    """

    event_type: str
    timestamp: float
    data: dict[str, Any]

    # ── Serialisation ──────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Convert to a plain dict for JSON serialisation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> RecordedEvent:
        """Reconstruct from a plain dict."""
        return cls(
            event_type=d["event_type"],
            timestamp=d["timestamp"],
            data=d["data"],
        )


@dataclass
class Recording:
    """
    A complete recording session: metadata + ordered list of events.

    Attributes:
        name:              Human-readable recording name (also used as filename stem)
        created_at:        ISO-8601 timestamp of when the recording was created
        device_resolution: Target device screen size (width, height) in pixels
        events:            Ordered list of RecordedEvent objects
        favorite:          Whether the user has marked this recording as a favourite
    """

    name: str
    created_at: str = ""
    device_resolution: tuple[int, int] = (1920, 1080)
    events: list[RecordedEvent] = field(default_factory=list)
    favorite: bool = False

    def __post_init__(self):
        """Auto-fill created_at if not provided."""
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    # ── Serialisation ──────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "device_resolution": list(self.device_resolution),
            "events": [e.to_dict() for e in self.events],
            "favorite": self.favorite,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Recording:
        events = [RecordedEvent.from_dict(e) for e in d.get("events", [])]
        res = d.get("device_resolution", [1920, 1080])
        return cls(
            name=d["name"],
            created_at=d.get("created_at", ""),
            device_resolution=(int(res[0]), int(res[1])),
            events=events,
            favorite=d.get("favorite", False),
        )

    def to_json(self) -> str:
        """Serialise to a pretty-printed JSON string."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> Recording:
        """Deserialise from a JSON string."""
        return cls.from_dict(json.loads(json_str))

    # ── Convenience ────────────────────────────────────────────────

    @property
    def duration(self) -> float:
        """Total duration of the recording in seconds."""
        if not self.events:
            return 0.0
        return self.events[-1].timestamp

    @property
    def event_count(self) -> int:
        return len(self.events)


# ============================================================
# File: ui/styles.py
# ============================================================
"""
styles.py — Premium dark theme QSS for the application.

Colour palette:
    Background    #0a0e27  (deepest navy)
    Surface       #111833  (panel/card backgrounds)
    Surface-Alt   #162040  (raised elements)
    Border        #1e2a5a  (subtle borders)
    Border-Hover  #4361ee  (electric blue accent)
    Primary       #4361ee  (buttons, accents)
    Danger        #e94560  (record button, errors)
    Success       #00d68f  (connected status)
    Warning       #ffaa00  (warnings)
    Text          #e0e0e0  (primary text)
    Text-Muted    #8090b0  (secondary text)
"""

DARK_THEME = """
/* ================================================================
   GLOBAL
   ================================================================ */

QMainWindow {
    background-color: #0a0e27;
}

QWidget {
    color: #e0e0e0;
    font-family: "Segoe UI", "Inter", "Roboto", sans-serif;
    font-size: 13px;
    outline: none;
}

QToolTip {
    background-color: #1e2a5a;
    color: #e0e0e0;
    border: 1px solid #2a3a7a;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}

/* ================================================================
   GROUP BOXES  (Panels)
   ================================================================ */

QGroupBox {
    background-color: #111833;
    border: 1px solid #1e2a5a;
    border-radius: 12px;
    margin-top: 20px;
    padding: 20px 14px 14px 14px;
    font-weight: 600;
    font-size: 13px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 14px;
    color: #80a0e0;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.5px;
}

/* ================================================================
   PUSH BUTTONS
   ================================================================ */

QPushButton {
    background-color: #162040;
    color: #d0d0e0;
    border: 1px solid #1e2a5a;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 13px;
    min-height: 30px;
}

QPushButton:hover {
    background-color: #1e2a5a;
    border-color: #4361ee;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #4361ee;
    border-color: #4361ee;
    color: #ffffff;
}

QPushButton:disabled {
    background-color: #0c1020;
    color: #3a3a5a;
    border-color: #141a30;
}

/* Record button — red accent */
QPushButton#btn_start_recording {
    background-color: #e94560;
    border-color: #e94560;
    color: #ffffff;
    font-weight: 700;
}
QPushButton#btn_start_recording:hover {
    background-color: #ff5a75;
    border-color: #ff5a75;
}
QPushButton#btn_start_recording:pressed {
    background-color: #c03050;
}
QPushButton#btn_start_recording:disabled {
    background-color: #4a1a25;
    color: #7a3a4a;
    border-color: #3a1520;
}

/* Stop recording — dark red */
QPushButton#btn_stop_recording {
    background-color: #3a1520;
    border-color: #e94560;
    color: #e94560;
    font-weight: 700;
}
QPushButton#btn_stop_recording:hover {
    background-color: #4a1a25;
}

/* Run / primary action — blue accent */
QPushButton#btn_run {
    background-color: #4361ee;
    border-color: #4361ee;
    color: #ffffff;
    font-weight: 700;
}
QPushButton#btn_run:hover {
    background-color: #5a7aff;
    border-color: #5a7aff;
}
QPushButton#btn_run:pressed {
    background-color: #3050cc;
}
QPushButton#btn_run:disabled {
    background-color: #1a2050;
    color: #3a4a7a;
    border-color: #1a2050;
}

/* Pause — amber */
QPushButton#btn_pause {
    background-color: #3a2a00;
    border-color: #ffaa00;
    color: #ffaa00;
    font-weight: 700;
}
QPushButton#btn_pause:hover {
    background-color: #4a3500;
}

/* Resume — green */
QPushButton#btn_resume {
    background-color: #003a2a;
    border-color: #00d68f;
    color: #00d68f;
    font-weight: 700;
}
QPushButton#btn_resume:hover {
    background-color: #004a35;
}

/* Stop execution — red outline */
QPushButton#btn_stop_execution {
    background-color: #3a1520;
    border-color: #e94560;
    color: #e94560;
    font-weight: 700;
}
QPushButton#btn_stop_execution:hover {
    background-color: #4a1a25;
}

/* Save — green accent */
QPushButton#btn_save_recording {
    background-color: #00d68f;
    border-color: #00d68f;
    color: #0a0e27;
    font-weight: 700;
}
QPushButton#btn_save_recording:hover {
    background-color: #00e6a0;
    border-color: #00e6a0;
}
QPushButton#btn_save_recording:disabled {
    background-color: #0a2a1a;
    color: #2a5a3a;
    border-color: #0a2a1a;
}

/* Refresh device button */
QPushButton#btn_refresh_device {
    background-color: #162040;
    border-color: #1e2a5a;
    padding: 6px 12px;
    min-height: 26px;
    font-size: 12px;
}

/* ================================================================
   LINE EDITS
   ================================================================ */

QLineEdit {
    background-color: #0c1025;
    color: #e0e0e0;
    border: 1px solid #1e2a5a;
    border-radius: 8px;
    padding: 8px 14px;
    font-size: 13px;
    selection-background-color: #4361ee;
    selection-color: #ffffff;
}

QLineEdit:focus {
    border-color: #4361ee;
    background-color: #0e1430;
}

QLineEdit:disabled {
    background-color: #0a0e1a;
    color: #3a3a5a;
    border-color: #141a30;
}

QLineEdit[readOnly="true"] {
    background-color: #0a0e1f;
    color: #8090b0;
}

/* ================================================================
   PROGRESS BAR
   ================================================================ */

QProgressBar {
    background-color: #0c1025;
    border: 1px solid #1e2a5a;
    border-radius: 10px;
    text-align: center;
    color: #e0e0e0;
    font-weight: 600;
    font-size: 12px;
    min-height: 22px;
    max-height: 22px;
}

QProgressBar::chunk {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #4361ee,
        stop:0.5 #6a5acd,
        stop:1 #e94560
    );
    border-radius: 9px;
}

/* ================================================================
   TEXT EDIT  (Logs)
   ================================================================ */

QTextEdit {
    background-color: #080c1e;
    color: #b0b8d0;
    border: 1px solid #1e2a5a;
    border-radius: 10px;
    padding: 10px;
    font-family: "Cascadia Code", "Consolas", "Fira Code", monospace;
    font-size: 12px;
    line-height: 1.5;
}

QTextEdit:disabled {
    background-color: #060a16;
    color: #3a3a5a;
}

/* ================================================================
   LIST WIDGET  (Library)
   ================================================================ */

QListWidget {
    background-color: #0c1025;
    border: 1px solid #1e2a5a;
    border-radius: 10px;
    padding: 6px;
    outline: none;
}

QListWidget::item {
    padding: 10px 14px;
    border-radius: 8px;
    margin: 2px 4px;
    color: #d0d0e0;
    font-size: 13px;
}

QListWidget::item:selected {
    background-color: #1e2a5a;
    color: #ffffff;
    border: 1px solid #4361ee;
}

QListWidget::item:hover:!selected {
    background-color: #141c3a;
}

/* ================================================================
   CHECK BOX
   ================================================================ */

QCheckBox {
    spacing: 10px;
    color: #c0c0d0;
    font-size: 13px;
}

QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border-radius: 5px;
    border: 2px solid #2a3a7a;
    background-color: #0c1025;
}

QCheckBox::indicator:hover {
    border-color: #4361ee;
}

QCheckBox::indicator:checked {
    background-color: #4361ee;
    border-color: #4361ee;
    image: none;
}

QCheckBox::indicator:disabled {
    background-color: #0a0e1a;
    border-color: #141a30;
}

/* ================================================================
   SCROLL BARS
   ================================================================ */

QScrollBar:vertical {
    background-color: transparent;
    width: 8px;
    margin: 4px 0;
}

QScrollBar::handle:vertical {
    background-color: #1e2a5a;
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #2a3a7a;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
    background: none;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    background-color: transparent;
    height: 8px;
    margin: 0 4px;
}

QScrollBar::handle:horizontal {
    background-color: #1e2a5a;
    border-radius: 4px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #2a3a7a;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
    background: none;
}

QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: none;
}

/* ================================================================
   LABELS — special object-name based styles
   ================================================================ */

QLabel#label_status_connected {
    color: #00d68f;
    font-size: 15px;
    font-weight: 700;
}

QLabel#label_status_disconnected {
    color: #e94560;
    font-size: 15px;
    font-weight: 700;
}

QLabel#label_device_serial {
    color: #8090b0;
    font-size: 12px;
}

QLabel#label_recording_timer {
    color: #e94560;
    font-size: 18px;
    font-weight: 700;
    font-family: "Cascadia Code", "Consolas", monospace;
}

QLabel#label_event_count {
    color: #8090b0;
    font-size: 12px;
}

QLabel#label_iteration_info {
    color: #4361ee;
    font-size: 14px;
    font-weight: 600;
}

QLabel#label_stat_value {
    color: #ffffff;
    font-size: 15px;
    font-weight: 700;
}

QLabel#label_stat_label {
    color: #6070a0;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.8px;
}

QLabel#label_section_title {
    color: #8090b0;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}

/* ================================================================
   CONTEXT MENUS
   ================================================================ */

QMenu {
    background-color: #111833;
    border: 1px solid #1e2a5a;
    border-radius: 8px;
    padding: 6px;
}

QMenu::item {
    padding: 8px 28px 8px 14px;
    border-radius: 6px;
    font-size: 13px;
}

QMenu::item:selected {
    background-color: #1e2a5a;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #1e2a5a;
    margin: 4px 8px;
}

/* ================================================================
   COMBO BOX
   ================================================================ */

QComboBox {
    background-color: #0c1025;
    color: #e0e0e0;
    border: 1px solid #1e2a5a;
    border-radius: 8px;
    padding: 8px 14px;
    font-size: 13px;
    min-height: 28px;
}

QComboBox:hover {
    border-color: #4361ee;
}

QComboBox::drop-down {
    border: none;
    width: 28px;
}

QComboBox QAbstractItemView {
    background-color: #111833;
    border: 1px solid #1e2a5a;
    border-radius: 6px;
    selection-background-color: #1e2a5a;
    selection-color: #ffffff;
    padding: 4px;
    outline: none;
}

/* ================================================================
   SPLITTER
   ================================================================ */

QSplitter::handle {
    background-color: #1e2a5a;
    width: 2px;
    margin: 0 4px;
}

QSplitter::handle:hover {
    background-color: #4361ee;
}

/* ================================================================
   DIALOG
   ================================================================ */

QDialog {
    background-color: #0a0e27;
}

QDialogButtonBox QPushButton {
    min-width: 90px;
}

/* ================================================================
   MESSAGE BOX
   ================================================================ */

QMessageBox {
    background-color: #0a0e27;
}

QMessageBox QLabel {
    color: #e0e0e0;
    font-size: 13px;
}

/* ================================================================
   INPUT DIALOG
   ================================================================ */

QInputDialog {
    background-color: #0a0e27;
}

QInputDialog QLabel {
    color: #e0e0e0;
}
"""


# ============================================================
# File: recorder/event_recorder.py
# ============================================================
"""
event_recorder.py — Captures user actions from the canvas into a recording session.

The EventRecorder receives raw mouse/keyboard events from the CanvasWidget,
classifies them (click vs swipe vs drag), and stores them as RecordedEvent
objects with relative timestamps.
"""

# ── Classification thresholds ──────────────────────────────────────
CLICK_MAX_DISTANCE = 12  # pixels — movement below this is a click
CLICK_MAX_DURATION = 0.4  # seconds — press-release under this is a click


class EventRecorder:
    """
    Stateful recorder that captures events from the interactive canvas.

    Usage:
        recorder = EventRecorder(device_resolution=(1920, 1080))
        recorder.start("my_testcase")
        # ... feed events via record_click / record_swipe / etc.
        recording = recorder.stop()
    """

    def __init__(self, device_resolution: tuple[int, int] = (1920, 1080)):
        self._recording = False
        self._start_time = 0.0
        self._events: list[RecordedEvent] = []
        self._device_resolution = device_resolution
        self._name = ""

        # Drag tracking state
        self._drag_points: list[dict] = []
        self._press_time = 0.0
        self._press_pos: Optional[tuple[int, int]] = None

    # ── Lifecycle ──────────────────────────────────────────────────

    def start(self, name: str = "untitled") -> None:
        """Begin a new recording session, resetting all state."""
        self._recording = True
        self._start_time = time.time()
        self._events = []
        self._name = name
        self._drag_points = []
        self._press_time = 0.0
        self._press_pos = None

    def stop(self) -> Recording:
        """
        End the recording and return the completed Recording object.
        The recorder is reset and ready for a new session.
        """
        self._recording = False
        return Recording(
            name=self._name,
            device_resolution=self._device_resolution,
            events=self._events.copy(),
        )

    # ── Properties ─────────────────────────────────────────────────

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def elapsed_time(self) -> float:
        """Seconds since recording started (0 if not recording)."""
        if self._recording:
            return time.time() - self._start_time
        return 0.0

    # ── Mouse press / move / release → classify as click or swipe ─

    def on_mouse_press(self, x: int, y: int) -> None:
        """Call when the mouse/touch is pressed on the canvas."""
        if not self._recording:
            return
        self._press_time = time.time()
        self._press_pos = (x, y)
        self._drag_points = [{"x": x, "y": y, "t": time.time() - self._start_time}]

    def on_mouse_move(self, x: int, y: int) -> None:
        """Call while the mouse/touch is being dragged."""
        if not self._recording or self._press_pos is None:
            return
        self._drag_points.append({"x": x, "y": y, "t": time.time() - self._start_time})

    def on_mouse_release(self, x: int, y: int) -> None:
        """
        Call when the mouse/touch is released.
        Classifies the gesture as click, swipe, or drag.
        """
        if not self._recording or self._press_pos is None:
            return

        duration = time.time() - self._press_time
        dx = x - self._press_pos[0]
        dy = y - self._press_pos[1]
        distance = (dx**2 + dy**2) ** 0.5

        timestamp = time.time() - self._start_time

        if distance < CLICK_MAX_DISTANCE and duration < CLICK_MAX_DURATION:
            # ── Click ──
            self._events.append(
                RecordedEvent(
                    event_type="click",
                    timestamp=timestamp,
                    data={
                        "x": self._press_pos[0],
                        "y": self._press_pos[1],
                        "button": "left",
                    },
                )
            )
        elif len(self._drag_points) > 5:
            # ── Drag (complex path with many points) ──
            self._events.append(
                RecordedEvent(
                    event_type="drag",
                    timestamp=self._drag_points[0]["t"],
                    data={"points": self._drag_points.copy()},
                )
            )
        else:
            # ── Swipe (simple start → end) ──
            duration_ms = max(int(duration * 1000), 100)
            self._events.append(
                RecordedEvent(
                    event_type="swipe",
                    timestamp=timestamp,
                    data={
                        "x1": self._press_pos[0],
                        "y1": self._press_pos[1],
                        "x2": x,
                        "y2": y,
                        "duration_ms": duration_ms,
                    },
                )
            )

        # Reset press state
        self._press_pos = None
        self._drag_points = []

    # ── Direct event recording (keyboard) ──────────────────────────

    def record_click(self, x: int, y: int, button: str = "left") -> None:
        """Directly record a click event (bypasses press/release classification)."""
        if not self._recording:
            return
        self._events.append(
            RecordedEvent(
                event_type="click",
                timestamp=time.time() - self._start_time,
                data={"x": x, "y": y, "button": button},
            )
        )

    def record_key(
        self, key: str, text: str, modifiers: list[str] | None = None
    ) -> None:
        """Record a keyboard event."""
        if not self._recording:
            return
        self._events.append(
            RecordedEvent(
                event_type="key_press",
                timestamp=time.time() - self._start_time,
                data={"key": key, "text": text, "modifiers": modifiers or []},
            )
        )


# ============================================================
# File: player/event_player.py
# ============================================================
"""
event_player.py — Replays recorded events on an Android device via ADB input injection.

Each RecordedEvent is translated into the corresponding `adb shell input` command:
    click     → adb shell input tap X Y
    swipe     → adb shell input swipe X1 Y1 X2 Y2 DURATION
    drag      → adb shell input swipe START_X START_Y END_X END_Y DURATION
    key_press → adb shell input keyevent KEYCODE  (special keys)
                adb shell input text "..."         (printable text)
"""

# ── Qt Key Name → Android Keycode mapping ──────────────────────────
QT_TO_ANDROID_KEYMAP: dict[str, str] = {
    # Navigation
    "Key_Back": "KEYCODE_BACK",
    "Key_Home": "KEYCODE_HOME",
    "Key_Return": "KEYCODE_ENTER",
    "Key_Enter": "KEYCODE_ENTER",
    "Key_Escape": "KEYCODE_ESCAPE",
    "Key_Tab": "KEYCODE_TAB",
    "Key_Backspace": "KEYCODE_DEL",
    "Key_Delete": "KEYCODE_FORWARD_DEL",
    # D-Pad
    "Key_Up": "KEYCODE_DPAD_UP",
    "Key_Down": "KEYCODE_DPAD_DOWN",
    "Key_Left": "KEYCODE_DPAD_LEFT",
    "Key_Right": "KEYCODE_DPAD_RIGHT",
    # Common keys
    "Key_Space": "KEYCODE_SPACE",
    # Media keys
    "Key_VolumeUp": "KEYCODE_VOLUME_UP",
    "Key_VolumeDown": "KEYCODE_VOLUME_DOWN",
    "Key_VolumeMute": "KEYCODE_VOLUME_MUTE",
    "Key_MediaPlay": "KEYCODE_MEDIA_PLAY",
    "Key_MediaPause": "KEYCODE_MEDIA_PAUSE",
    "Key_MediaStop": "KEYCODE_MEDIA_STOP",
    "Key_MediaNext": "KEYCODE_MEDIA_NEXT",
    "Key_MediaPrevious": "KEYCODE_MEDIA_PREVIOUS",
    "Key_MediaTogglePlayPause": "KEYCODE_MEDIA_PLAY_PAUSE",
    # Function keys
    "Key_F1": "KEYCODE_F1",
    "Key_F2": "KEYCODE_F2",
    "Key_F3": "KEYCODE_F3",
    "Key_F4": "KEYCODE_F4",
    "Key_F5": "KEYCODE_F5",
    "Key_F6": "KEYCODE_F6",
    "Key_F7": "KEYCODE_F7",
    "Key_F8": "KEYCODE_F8",
    "Key_F9": "KEYCODE_F9",
    "Key_F10": "KEYCODE_F10",
    "Key_F11": "KEYCODE_F11",
    "Key_F12": "KEYCODE_F12",
    # Android-specific
    "Key_Menu": "KEYCODE_MENU",
    "Key_Search": "KEYCODE_SEARCH",
}


class EventPlayer:
    """
    Translates RecordedEvent objects into ADB shell input commands
    and executes them on the target Android device.
    """

    def __init__(self, device_serial: str = ""):
        self._device_serial = device_serial

    @property
    def device_serial(self) -> str:
        return self._device_serial

    @device_serial.setter
    def device_serial(self, serial: str) -> None:
        self._device_serial = serial

    # ── Core ADB command execution ─────────────────────────────────

    def _adb_cmd(self, *args: str) -> subprocess.CompletedProcess:
        """
        Execute an ADB command with optional device serial targeting.
        Returns the CompletedProcess result.
        """
        cmd: list[str] = ["adb"]
        if self._device_serial:
            cmd.extend(["-s", self._device_serial])
        cmd.extend(args)

        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )

    # ── Event dispatch ─────────────────────────────────────────────

    def play_event(self, event: RecordedEvent) -> None:
        """Play a single recorded event on the device."""
        handler = {
            "click": self._play_click,
            "swipe": self._play_swipe,
            "drag": self._play_drag,
            "key_press": self._play_key,
        }.get(event.event_type)

        if handler:
            handler(event.data)

    # ── Individual event handlers ──────────────────────────────────

    def _play_click(self, data: dict) -> None:
        """Send a tap at the given coordinates."""
        x, y = data["x"], data["y"]
        self._adb_cmd("shell", "input", "tap", str(x), str(y))

    def _play_swipe(self, data: dict) -> None:
        """Send a swipe from (x1,y1) to (x2,y2) over the given duration."""
        x1, y1 = data["x1"], data["y1"]
        x2, y2 = data["x2"], data["y2"]
        duration = data.get("duration_ms", 300)
        self._adb_cmd(
            "shell",
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration),
        )

    def _play_drag(self, data: dict) -> None:
        """
        Replay a drag gesture. ADB's input swipe supports start→end only,
        so we approximate the drag as a single swipe from first to last point.
        """
        points = data.get("points", [])
        if len(points) < 2:
            return

        start = points[0]
        end = points[-1]

        # Calculate duration from timestamps
        duration_ms = int((end.get("t", 0) - start.get("t", 0)) * 1000)
        duration_ms = max(duration_ms, 100)  # minimum 100ms

        self._adb_cmd(
            "shell",
            "input",
            "swipe",
            str(start["x"]),
            str(start["y"]),
            str(end["x"]),
            str(end["y"]),
            str(duration_ms),
        )

    def _play_key(self, data: dict) -> None:
        """
        Send a key event. Special keys are mapped to Android keycodes;
        printable characters are sent as text input.
        """
        key = data.get("key", "")
        text = data.get("text", "")

        # Check for mapped special keys first
        android_keycode = QT_TO_ANDROID_KEYMAP.get(key)
        if android_keycode:
            self._adb_cmd("shell", "input", "keyevent", android_keycode)
        elif text and text.isprintable() and text.strip():
            # Escape special shell characters
            escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
            escaped = escaped.replace(
                " ", "%s"
            )  # ADB text doesn't support spaces directly
            self._adb_cmd("shell", "input", "text", escaped)


# ============================================================
# File: storage/recording_manager.py
# ============================================================
"""
recording_manager.py — CRUD operations for recording persistence.

Recordings are stored as individual JSON files in the recordings/ directory.
Each file is named {recording_name}.json.
"""


class RecordingManager:
    """
    Manages saving, loading, listing, deleting, renaming, and searching
    recordings on disk.
    """

    def __init__(self, recordings_dir: str | Path = "recordings"):
        self._dir = Path(recordings_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def directory(self) -> Path:
        return self._dir

    # ── Save / Load ────────────────────────────────────────────────

    def save(self, recording: Recording) -> str:
        """Save a recording to disk. Returns the file path."""
        # Sanitise filename: replace unsafe characters
        safe_name = self._sanitise_name(recording.name)
        filepath = self._dir / f"{safe_name}.json"
        filepath.write_text(recording.to_json(), encoding="utf-8")
        return str(filepath)

    def load(self, name: str) -> Recording:
        """Load a recording by name (without extension)."""
        safe_name = self._sanitise_name(name)
        filepath = self._dir / f"{safe_name}.json"
        if not filepath.exists():
            raise FileNotFoundError(f"Recording '{name}' not found at {filepath}")
        return Recording.from_json(filepath.read_text(encoding="utf-8"))

    # ── List ───────────────────────────────────────────────────────

    def list_all(self) -> list[dict]:
        """
        List all recordings with metadata.
        Returns dicts with: name, created_at, event_count, favorite, filename.
        Does NOT load full event data for performance.
        """
        recordings = []
        for filepath in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                recordings.append(
                    {
                        "name": data.get("name", filepath.stem),
                        "created_at": data.get("created_at", ""),
                        "event_count": len(data.get("events", [])),
                        "favorite": data.get("favorite", False),
                        "filename": filepath.stem,
                    }
                )
            except (json.JSONDecodeError, KeyError, OSError):
                continue  # skip corrupt files
        return recordings

    # ── Delete ─────────────────────────────────────────────────────

    def delete(self, name: str) -> bool:
        """Delete a recording file. Returns True if deleted, False if not found."""
        safe_name = self._sanitise_name(name)
        filepath = self._dir / f"{safe_name}.json"
        if filepath.exists():
            filepath.unlink()
            return True
        return False

    # ── Rename ─────────────────────────────────────────────────────

    def rename(self, old_name: str, new_name: str) -> bool:
        """
        Rename a recording. Updates both the filename and the internal name.
        Returns True on success, False if old doesn't exist or new already exists.
        """
        old_safe = self._sanitise_name(old_name)
        new_safe = self._sanitise_name(new_name)
        old_path = self._dir / f"{old_safe}.json"
        new_path = self._dir / f"{new_safe}.json"

        if not old_path.exists() or new_path.exists():
            return False

        recording = self.load(old_name)
        recording.name = new_name
        self.save(recording)
        old_path.unlink()
        return True

    # ── Favourite toggle ───────────────────────────────────────────

    def toggle_favorite(self, name: str) -> bool:
        """Toggle the favourite flag. Returns the new state."""
        recording = self.load(name)
        recording.favorite = not recording.favorite
        self.save(recording)
        return recording.favorite

    # ── Search ─────────────────────────────────────────────────────

    def search(self, query: str) -> list[dict]:
        """Filter recordings by name (case-insensitive substring match)."""
        all_recordings = self.list_all()
        if not query:
            return all_recordings
        q = query.lower()
        return [r for r in all_recordings if q in r["name"].lower()]

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _sanitise_name(name: str) -> str:
        """Replace characters that are unsafe in filenames."""
        unsafe = '<>:"/\\|?*'
        result = name
        for ch in unsafe:
            result = result.replace(ch, "_")
        return result.strip().rstrip(".")


# ============================================================
# File: storage/export_manager.py
# ============================================================
"""
export_manager.py — Export recordings to JSON/CSV and import from JSON/CSV.

Export formats:
    JSON  — full-fidelity, pretty-printed JSON (same as internal storage)
    CSV   — flattened table with one row per event, suitable for spreadsheets
"""


class ExportManager:
    """Handles exporting and importing recordings in various formats."""

    def __init__(self, exports_dir: str | Path = "exports"):
        self._dir = Path(exports_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def directory(self) -> Path:
        return self._dir

    # ── Export ──────────────────────────────────────────────────────

    def export_json(self, recording: Recording, filepath: str | None = None) -> str:
        """
        Export a recording as pretty-printed JSON.
        Returns the output filepath.
        """
        if filepath is None:
            filepath = str(self._dir / f"{recording.name}.json")
        Path(filepath).write_text(recording.to_json(), encoding="utf-8")
        return filepath

    def export_csv(self, recording: Recording, filepath: str | None = None) -> str:
        """
        Export a recording as a flat CSV table.
        Each row represents one event with all relevant fields.
        Returns the output filepath.
        """
        if filepath is None:
            filepath = str(self._dir / f"{recording.name}.csv")

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            # Header row
            writer.writerow(
                [
                    "event_index",
                    "event_type",
                    "timestamp_sec",
                    "x",
                    "y",
                    "x1",
                    "y1",
                    "x2",
                    "y2",
                    "duration_ms",
                    "key",
                    "text",
                    "button",
                    "modifiers",
                ]
            )

            # Data rows
            for i, event in enumerate(recording.events):
                d = event.data
                writer.writerow(
                    [
                        i,
                        event.event_type,
                        f"{event.timestamp:.4f}",
                        d.get("x", ""),
                        d.get("y", ""),
                        d.get("x1", ""),
                        d.get("y1", ""),
                        d.get("x2", ""),
                        d.get("y2", ""),
                        d.get("duration_ms", ""),
                        d.get("key", ""),
                        d.get("text", ""),
                        d.get("button", ""),
                        "|".join(d.get("modifiers", [])),
                    ]
                )

        return filepath

    # ── Import ─────────────────────────────────────────────────────

    def import_json(self, filepath: str) -> Recording:
        """Import a recording from a JSON file."""
        content = Path(filepath).read_text(encoding="utf-8")
        return Recording.from_json(content)

    def import_csv(self, filepath: str) -> Recording:
        """
        Import a recording from a CSV file.
        Reconstructs event objects from the flat row format.
        """
        events: list[RecordedEvent] = []
        name = Path(filepath).stem

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                event_type = row.get("event_type", "").strip()
                timestamp = float(row.get("timestamp_sec", 0))
                data: dict = {}

                if event_type == "click":
                    data = {
                        "x": int(row["x"]),
                        "y": int(row["y"]),
                        "button": row.get("button", "left"),
                    }
                elif event_type == "swipe":
                    data = {
                        "x1": int(row["x1"]),
                        "y1": int(row["y1"]),
                        "x2": int(row["x2"]),
                        "y2": int(row["y2"]),
                        "duration_ms": int(row.get("duration_ms", 300)),
                    }
                elif event_type == "drag":
                    # CSV export loses detailed drag points; import as swipe
                    data = {"points": []}
                elif event_type == "key_press":
                    mods_str = row.get("modifiers", "")
                    data = {
                        "key": row.get("key", ""),
                        "text": row.get("text", ""),
                        "modifiers": mods_str.split("|") if mods_str else [],
                    }
                else:
                    continue  # skip unknown event types

                events.append(
                    RecordedEvent(
                        event_type=event_type,
                        timestamp=timestamp,
                        data=data,
                    )
                )

        return Recording(name=name, events=events)


# ============================================================
# File: workers/device_worker.py
# ============================================================
"""
device_worker.py — Background thread for ADB device detection.

Runs `adb devices` in a subprocess and emits signals indicating
whether a device is connected. This is the ONLY ADB command
executed for device validation, per project constraints.
"""


class DeviceWorker(QThread):
    """
    Single-shot worker that checks for connected ADB devices.

    Signals:
        device_found(str):   Emitted with the device serial when a device is connected.
        no_device():         Emitted when no device is found.
        error_occurred(str): Emitted when ADB is not found or another error occurs.
    """

    device_found = pyqtSignal(str)
    no_device = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def run(self) -> None:
        """Execute `adb devices` and parse the output."""
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            # Parse output:
            #   List of devices attached
            #   SERIAL\tdevice
            #   SERIAL\tunauthorized
            #   ...
            lines = result.stdout.strip().split("\n")
            devices: list[str] = []

            for line in lines[1:]:  # skip "List of devices attached" header
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2 and parts[1].strip() == "device":
                    devices.append(parts[0].strip())

            if devices:
                # Use the first connected device
                self.device_found.emit(devices[0])
            else:
                self.no_device.emit()

        except FileNotFoundError:
            self.error_occurred.emit(
                "ADB not found. Please ensure Android SDK platform-tools "
                "is installed and 'adb' is on your system PATH."
            )
        except subprocess.TimeoutExpired:
            self.error_occurred.emit("ADB command timed out after 10 seconds.")
        except Exception as e:
            self.error_occurred.emit(f"Device detection error: {str(e)}")


# ============================================================
# File: workers/playback_worker.py
# ============================================================
"""
playback_worker.py — Background thread for replaying recordings.

Plays all events in a recording for a specified number of iterations,
emitting progress signals throughout. Supports pause, resume, and stop.
"""


class PlaybackWorker(QThread):
    """
    Worker thread that replays recorded events on the Android device.

    Signals:
        iteration_started(int):   Emitted when an iteration begins (1-based).
        iteration_completed(int): Emitted when an iteration finishes.
        event_played(int, str):   Emitted after each event (index, description).
        progress_updated(int):    Overall progress percentage (0-100).
        playback_finished():      Emitted when all iterations complete or stopped.
        error_occurred(str):      Emitted on non-fatal errors.
        stats_updated(dict):      Execution statistics after each iteration.
    """

    iteration_started = pyqtSignal(int)
    iteration_completed = pyqtSignal(int)
    event_played = pyqtSignal(int, str)
    progress_updated = pyqtSignal(int)
    playback_finished = pyqtSignal()
    error_occurred = pyqtSignal(str)
    stats_updated = pyqtSignal(dict)

    def __init__(
        self,
        recording: Recording,
        device_serial: str,
        iterations: int = 1,
        delay_ms: int = 0,
        infinite_loop: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._recording = recording
        self._device_serial = device_serial
        self._iterations = iterations
        self._delay_ms = delay_ms
        self._infinite_loop = infinite_loop
        self._player = EventPlayer(device_serial)

        # Threading primitives for pause/stop control
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # not paused initially

        self._completed = 0
        self._start_time = 0.0

    # ── Control ────────────────────────────────────────────────────

    def pause(self) -> None:
        """Pause playback after the current event finishes."""
        self._pause_event.clear()

    def resume(self) -> None:
        """Resume paused playback."""
        self._pause_event.set()

    def stop(self) -> None:
        """Stop playback entirely. Unblocks pause if needed."""
        self._stop_event.set()
        self._pause_event.set()

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    # ── Main loop ──────────────────────────────────────────────────

    def run(self) -> None:
        """
        Main playback loop. Iterates through the recording's events,
        respecting original timing, and repeats for the requested
        number of iterations.
        """
        self._start_time = time.time()
        self._completed = 0
        iteration = 0

        try:
            while True:
                # ── Stop check ──
                if self._stop_event.is_set():
                    break

                # ── Iteration limit check ──
                if not self._infinite_loop and iteration >= self._iterations:
                    break

                iteration += 1
                self.iteration_started.emit(iteration)

                # ── Play all events in this iteration ──
                events = self._recording.events
                prev_timestamp = 0.0

                for idx, event in enumerate(events):
                    # Honour pause
                    self._pause_event.wait()

                    # Check stop
                    if self._stop_event.is_set():
                        break

                    # ── Maintain original timing ──
                    delay = event.timestamp - prev_timestamp
                    if delay > 0:
                        self._interruptible_sleep(delay)

                    if self._stop_event.is_set():
                        break

                    # ── Execute the event ──
                    try:
                        self._player.play_event(event)
                        desc = self._describe_event(event)
                        self.event_played.emit(idx, desc)
                    except Exception as e:
                        self.error_occurred.emit(f"Event {idx} failed: {str(e)}")

                    prev_timestamp = event.timestamp

                    # ── Update progress ──
                    if not self._infinite_loop and self._iterations > 0 and events:
                        total_events = len(events) * self._iterations
                        done_events = (iteration - 1) * len(events) + (idx + 1)
                        pct = min(int((done_events / total_events) * 100), 100)
                        self.progress_updated.emit(pct)

                # ── Check if stopped mid-iteration ──
                if self._stop_event.is_set():
                    break

                self._completed = iteration
                self.iteration_completed.emit(iteration)

                # ── Emit statistics ──
                elapsed = time.time() - self._start_time
                remaining = (
                    (self._iterations - iteration) if not self._infinite_loop else -1
                )
                self.stats_updated.emit(
                    {
                        "total": self._iterations if not self._infinite_loop else -1,
                        "completed": self._completed,
                        "remaining": remaining,
                        "elapsed": elapsed,
                    }
                )

                # ── Delay between iterations ──
                if self._delay_ms > 0:
                    self._interruptible_sleep(self._delay_ms / 1000.0)

        except Exception as e:
            self.error_occurred.emit(f"Playback error: {str(e)}")
        finally:
            # Final stats emission
            elapsed = time.time() - self._start_time
            self.stats_updated.emit(
                {
                    "total": self._iterations if not self._infinite_loop else -1,
                    "completed": self._completed,
                    "remaining": 0,
                    "elapsed": elapsed,
                }
            )
            self.playback_finished.emit()

    # ── Helpers ────────────────────────────────────────────────────

    def _interruptible_sleep(self, seconds: float) -> None:
        """
        Sleep for the given duration but wake early if stop is requested.
        Checks every 50ms so the UI remains responsive.
        """
        end_time = time.time() + seconds
        while time.time() < end_time:
            if self._stop_event.is_set():
                return
            # Also honour pause
            self._pause_event.wait(timeout=0.05)

    @staticmethod
    def _describe_event(event) -> str:
        """Generate a human-readable description of an event."""
        d = event.data
        if event.event_type == "click":
            return f"Tap ({d['x']}, {d['y']})"
        elif event.event_type == "swipe":
            return f"Swipe ({d['x1']},{d['y1']}) → ({d['x2']},{d['y2']})"
        elif event.event_type == "drag":
            pts = d.get("points", [])
            return f"Drag ({len(pts)} points)"
        elif event.event_type == "key_press":
            label = d.get("text", "") or d.get("key", "")
            return f"Key: {label}"
        return f"Event: {event.event_type}"


# ============================================================
# File: ui/canvas_widget.py
# ============================================================
"""
canvas_widget.py — Interactive recording surface.

Represents the infotainment display as a proportionally-scaled canvas.
Captures mouse clicks, swipes, drags, and keyboard input, forwarding
them to the EventRecorder.  Provides visual feedback (click ripples,
swipe trails, key indicators).
"""

# ── Visual feedback data ───────────────────────────────────────────


class _Ripple:
    """Expanding circle animation on click."""

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y
        self.radius = 0.0
        self.max_radius = 40.0
        self.opacity = 1.0
        self.alive = True

    def update(self):
        self.radius += 3.0
        self.opacity -= 0.06
        if self.opacity <= 0 or self.radius > self.max_radius:
            self.alive = False


class _TrailPoint:
    """Point in a swipe/drag trail."""

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y
        self.opacity = 1.0

    def fade(self):
        self.opacity -= 0.03


class _KeyIndicator:
    """Brief text overlay for key presses."""

    def __init__(self, text: str, x: float, y: float):
        self.text = text
        self.x = x
        self.y = y
        self.opacity = 1.0
        self.alive = True

    def update(self):
        self.opacity -= 0.04
        self.y -= 1.0
        if self.opacity <= 0:
            self.alive = False


class CanvasWidget(QWidget):
    """
    Touch/mouse/keyboard recording surface.

    Emits signals for recorded events that the MainWindow connects
    to the EventRecorder.

    Signals:
        mouse_pressed(int, int):  Emitted on press (device-scaled coords)
        mouse_moved(int, int):    Emitted on drag (device-scaled coords)
        mouse_released(int, int): Emitted on release (device-scaled coords)
        key_pressed(str, str, list): Emitted on key (key_name, text, modifiers)
    """

    mouse_pressed = pyqtSignal(int, int)
    mouse_moved = pyqtSignal(int, int)
    mouse_released = pyqtSignal(int, int)
    key_pressed = pyqtSignal(str, str, list)

    # Default infotainment resolution
    DEVICE_WIDTH = 1920
    DEVICE_HEIGHT = 1080

    def __init__(self, parent=None):
        super().__init__(parent)

        # Recording state
        self._recording = False
        self._enabled = False

        # Visual feedback
        self._ripples: list[_Ripple] = []
        self._trail: list[_TrailPoint] = []
        self._key_indicators: list[_KeyIndicator] = []
        self._is_dragging = False

        # Grid / crosshair state
        self._mouse_pos: Optional[QPointF] = None

        # Animation timer (60 fps)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)  # ~60fps
        self._anim_timer.timeout.connect(self._on_animation_tick)

        # Widget setup
        self.setMinimumSize(640, 360)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ── Public control ─────────────────────────────────────────────

    def set_recording(self, active: bool) -> None:
        """Enable/disable recording mode."""
        self._recording = active
        if active:
            self._anim_timer.start()
        else:
            self._ripples.clear()
            self._trail.clear()
            self._key_indicators.clear()
            self._anim_timer.stop()
        self.update()

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable the canvas (device connected state)."""
        self._enabled = enabled
        self.update()

    @property
    def is_recording(self) -> bool:
        return self._recording

    # ── Coordinate mapping ─────────────────────────────────────────

    def _canvas_rect(self) -> QRectF:
        """
        Calculate the proportionally-scaled area within the widget
        that represents the device screen.
        """
        w = self.width()
        h = self.height()
        aspect = self.DEVICE_WIDTH / self.DEVICE_HEIGHT

        canvas_w = w
        canvas_h = int(w / aspect)
        if canvas_h > h:
            canvas_h = h
            canvas_w = int(h * aspect)

        x_offset = (w - canvas_w) / 2
        y_offset = (h - canvas_h) / 2
        return QRectF(x_offset, y_offset, canvas_w, canvas_h)

    def _widget_to_device(self, wx: float, wy: float) -> tuple[int, int]:
        """Convert widget pixel coordinates to device coordinates."""
        rect = self._canvas_rect()
        if rect.width() == 0 or rect.height() == 0:
            return (0, 0)

        # Normalise to 0..1 within the canvas rect
        nx = (wx - rect.x()) / rect.width()
        ny = (wy - rect.y()) / rect.height()

        # Clamp
        nx = max(0.0, min(1.0, nx))
        ny = max(0.0, min(1.0, ny))

        return (int(nx * self.DEVICE_WIDTH), int(ny * self.DEVICE_HEIGHT))

    def _is_in_canvas(self, wx: float, wy: float) -> bool:
        """Check if widget coordinates fall within the canvas area."""
        return self._canvas_rect().contains(QPointF(wx, wy))

    # ── Mouse events ───────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self._recording or not self._enabled:
            return
        if not self._is_in_canvas(event.position().x(), event.position().y()):
            return

        dx, dy = self._widget_to_device(event.position().x(), event.position().y())
        self._is_dragging = True
        self._trail.clear()
        self._trail.append(_TrailPoint(event.position().x(), event.position().y()))
        self._ripples.append(_Ripple(event.position().x(), event.position().y()))
        self.mouse_pressed.emit(dx, dy)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._mouse_pos = event.position()

        if not self._recording or not self._enabled or not self._is_dragging:
            self.update()
            return
        if not self._is_in_canvas(event.position().x(), event.position().y()):
            return

        dx, dy = self._widget_to_device(event.position().x(), event.position().y())
        self._trail.append(_TrailPoint(event.position().x(), event.position().y()))
        self.mouse_moved.emit(dx, dy)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self._recording or not self._enabled or not self._is_dragging:
            return

        dx, dy = self._widget_to_device(event.position().x(), event.position().y())
        self._is_dragging = False
        self.mouse_released.emit(dx, dy)

    # ── Keyboard events ────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._recording or not self._enabled:
            return

        key_name = self._qt_key_name(event.key())
        text = event.text()
        modifiers = self._qt_modifiers(event.modifiers())

        # Visual feedback
        label = text if text and text.isprintable() else key_name
        cx = self.width() / 2
        cy = self.height() / 2
        self._key_indicators.append(_KeyIndicator(label, cx, cy))

        self.key_pressed.emit(key_name, text, modifiers)

    # ── Animation ──────────────────────────────────────────────────

    def _on_animation_tick(self) -> None:
        """Update all visual feedback animations."""
        # Update ripples
        for r in self._ripples:
            r.update()
        self._ripples = [r for r in self._ripples if r.alive]

        # Fade trail
        for p in self._trail:
            if not self._is_dragging:
                p.fade()
        self._trail = [p for p in self._trail if p.opacity > 0]

        # Update key indicators
        for k in self._key_indicators:
            k.update()
        self._key_indicators = [k for k in self._key_indicators if k.alive]

        self.update()

    # ── Painting ───────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── Background ──
        painter.fillRect(self.rect(), QColor("#060a18"))

        rect = self._canvas_rect()

        # ── Canvas area ──
        if self._enabled:
            # Gradient background for the canvas
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, QColor("#0e1430"))
            grad.setColorAt(1.0, QColor("#0a1025"))
            painter.fillRect(rect, QBrush(grad))

            # Subtle border
            pen = QPen(QColor("#1e2a5a"), 2)
            painter.setPen(pen)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)
        else:
            painter.fillRect(rect, QColor("#080c1a"))
            # "No Device" overlay
            painter.setPen(QColor("#3a3a5a"))
            font = QFont("Segoe UI", 16, QFont.Weight.Bold)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No Device Connected")
            painter.end()
            return

        # ── Recording indicator ──
        if self._recording:
            # Pulsing red dot in top-right corner
            dot_x = rect.right() - 20
            dot_y = rect.top() + 20
            pulse = abs(math.sin(time.time() * 3)) * 0.5 + 0.5
            color = QColor(233, 69, 96, int(255 * pulse))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QPointF(dot_x, dot_y), 6, 6)

            # "REC" label
            painter.setPen(QColor(233, 69, 96, int(255 * pulse)))
            font = QFont("Segoe UI", 10, QFont.Weight.Bold)
            painter.setFont(font)
            painter.drawText(int(dot_x - 40), int(dot_y + 4), "● REC")

        # ── Crosshair at mouse position ──
        if self._mouse_pos and self._is_in_canvas(
            self._mouse_pos.x(), self._mouse_pos.y()
        ):
            mx, my = self._mouse_pos.x(), self._mouse_pos.y()
            pen = QPen(QColor(67, 97, 238, 60), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(int(mx), int(rect.top()), int(mx), int(rect.bottom()))
            painter.drawLine(int(rect.left()), int(my), int(rect.right()), int(my))

            # Coordinate label
            dx, dy = self._widget_to_device(mx, my)
            painter.setPen(QColor(128, 160, 224, 180))
            font = QFont("Cascadia Code", 9)
            painter.setFont(font)
            painter.drawText(int(mx + 12), int(my - 8), f"({dx}, {dy})")

        # ── Swipe/drag trail ──
        if len(self._trail) >= 2:
            for i in range(1, len(self._trail)):
                p0 = self._trail[i - 1]
                p1 = self._trail[i]
                alpha = int(min(p0.opacity, p1.opacity) * 200)
                if alpha <= 0:
                    continue
                pen = QPen(QColor(67, 97, 238, alpha), 3, Qt.PenStyle.SolidLine)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(int(p0.x), int(p0.y), int(p1.x), int(p1.y))

        # ── Click ripples ──
        for ripple in self._ripples:
            alpha = int(ripple.opacity * 180)
            if alpha <= 0:
                continue
            color = QColor(233, 69, 96, alpha)
            pen = QPen(color, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(
                QPointF(ripple.x, ripple.y),
                ripple.radius,
                ripple.radius,
            )

        # ── Key indicators ──
        for ki in self._key_indicators:
            alpha = int(ki.opacity * 255)
            if alpha <= 0:
                continue
            painter.setPen(QColor(255, 170, 0, alpha))
            font = QFont("Cascadia Code", 14, QFont.Weight.Bold)
            painter.setFont(font)
            painter.drawText(int(ki.x - 20), int(ki.y), ki.text)

        painter.end()

    # ── Qt key / modifier helpers ──────────────────────────────────

    @staticmethod
    def _qt_key_name(key: int) -> str:
        """Convert a Qt key enum to a string name like 'Key_Return'."""
        from PyQt6.QtCore import Qt as QtNS

        # Try to find the key name in the Key enum
        try:
            key_enum = QtNS.Key(key)
            return key_enum.name
        except (ValueError, AttributeError):
            return f"Key_0x{key:x}"

    @staticmethod
    def _qt_modifiers(mods) -> list[str]:
        """Convert Qt keyboard modifiers to a list of strings."""
        result = []
        if mods & Qt.KeyboardModifier.ShiftModifier:
            result.append("Shift")
        if mods & Qt.KeyboardModifier.ControlModifier:
            result.append("Ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            result.append("Alt")
        if mods & Qt.KeyboardModifier.MetaModifier:
            result.append("Meta")
        return result


# ============================================================
# File: ui/device_panel.py
# ============================================================
"""
device_panel.py — Device connection status panel.

Shows whether an Android device is connected via ADB.
Displays ✅ / ❌ status with the device serial number.
"""


class DevicePanel(QGroupBox):
    """
    Device status display and refresh control.

    Signals:
        device_connected(bool, str): Emitted when status changes (connected, serial).
    """

    device_connected = pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__("Device Status", parent)
        self._device_serial = ""
        self._connected = False
        self._worker: DeviceWorker | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Status label
        self._label_status = QLabel("Checking device...")
        self._label_status.setObjectName("label_status_disconnected")
        self._label_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label_status)

        # Device serial label
        self._label_serial = QLabel("")
        self._label_serial.setObjectName("label_device_serial")
        self._label_serial.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label_serial)

        # Refresh button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_refresh = QPushButton("⟳  Refresh")
        self._btn_refresh.setObjectName("btn_refresh_device")
        self._btn_refresh.setFixedWidth(120)
        self._btn_refresh.clicked.connect(self.check_device)
        btn_row.addWidget(self._btn_refresh)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    # ── Public API ─────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def device_serial(self) -> str:
        return self._device_serial

    def check_device(self) -> None:
        """Launch a background check for connected ADB devices."""
        self._label_status.setText("Checking...")
        self._label_status.setObjectName("label_status_disconnected")
        self._label_status.setStyleSheet("")  # force re-apply
        self._btn_refresh.setEnabled(False)

        self._worker = DeviceWorker()
        self._worker.device_found.connect(self._on_device_found)
        self._worker.no_device.connect(self._on_no_device)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    # ── Slots ──────────────────────────────────────────────────────

    def _on_device_found(self, serial: str) -> None:
        self._connected = True
        self._device_serial = serial
        self._label_status.setText("✅  Device Connected")
        self._label_status.setObjectName("label_status_connected")
        # Force style re-evaluation after objectName change
        self._label_status.style().unpolish(self._label_status)
        self._label_status.style().polish(self._label_status)
        self._label_serial.setText(f"Serial: {serial}")
        self.device_connected.emit(True, serial)

    def _on_no_device(self) -> None:
        self._connected = False
        self._device_serial = ""
        self._label_status.setText(
            "❌  No Device Connected\nPlease connect the infotainment system."
        )
        self._label_status.setObjectName("label_status_disconnected")
        self._label_status.style().unpolish(self._label_status)
        self._label_status.style().polish(self._label_status)
        self._label_serial.setText("")
        self.device_connected.emit(False, "")

    def _on_error(self, message: str) -> None:
        self._connected = False
        self._device_serial = ""
        self._label_status.setText(f"⚠  {message}")
        self._label_status.setObjectName("label_status_disconnected")
        self._label_status.style().unpolish(self._label_status)
        self._label_status.style().polish(self._label_status)
        self._label_serial.setText("")
        self.device_connected.emit(False, "")

    def _on_worker_finished(self) -> None:
        self._btn_refresh.setEnabled(True)


# ============================================================
# File: ui/recording_panel.py
# ============================================================
"""
recording_panel.py — Recording controls panel.

Provides Start Recording, Stop Recording, and Save Recording buttons
along with a live recording timer and event counter.
"""


class RecordingPanel(QGroupBox):
    """
    Recording control panel with timer and event count.

    Signals:
        start_recording():  Emitted when Start Recording is clicked.
        stop_recording():   Emitted when Stop Recording is clicked.
        save_recording():   Emitted when Save Recording is clicked.
    """

    start_recording = pyqtSignal()
    stop_recording = pyqtSignal()
    save_recording = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Recording", parent)
        self._is_recording = False
        self._elapsed_seconds = 0
        self._event_count = 0
        self._has_unsaved_recording = False
        self._init_ui()

        # Timer for updating elapsed display
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Timer and event count row ──
        info_row = QHBoxLayout()

        self._label_timer = QLabel("00:00:00")
        self._label_timer.setObjectName("label_recording_timer")
        self._label_timer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_row.addWidget(self._label_timer)

        self._label_events = QLabel("0 events")
        self._label_events.setObjectName("label_event_count")
        self._label_events.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_row.addWidget(self._label_events)

        layout.addLayout(info_row)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._btn_start = QPushButton("⏺  Start Recording")
        self._btn_start.setObjectName("btn_start_recording")
        self._btn_start.clicked.connect(self._on_start)
        btn_row.addWidget(self._btn_start)

        self._btn_stop = QPushButton("⏹  Stop Recording")
        self._btn_stop.setObjectName("btn_stop_recording")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)
        btn_row.addWidget(self._btn_stop)

        layout.addLayout(btn_row)

        # Save button on its own row
        self._btn_save = QPushButton("💾  Save Recording")
        self._btn_save.setObjectName("btn_save_recording")
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_save)
        layout.addWidget(self._btn_save)

    # ── Public API ─────────────────────────────────────────────────

    def set_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable all controls based on device connection."""
        self._btn_start.setEnabled(enabled and not self._is_recording)
        if not enabled:
            self._btn_stop.setEnabled(False)
            self._btn_save.setEnabled(False)

    def update_event_count(self, count: int) -> None:
        """Update the event counter display."""
        self._event_count = count
        self._label_events.setText(f"{count} events")

    def reset(self) -> None:
        """Reset the panel to initial state."""
        self._is_recording = False
        self._elapsed_seconds = 0
        self._event_count = 0
        self._has_unsaved_recording = False
        self._label_timer.setText("00:00:00")
        self._label_events.setText("0 events")
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_save.setEnabled(False)
        self._timer.stop()

    # ── Slots ──────────────────────────────────────────────────────

    def _on_start(self) -> None:
        self._is_recording = True
        self._elapsed_seconds = 0
        self._event_count = 0
        self._label_timer.setText("00:00:00")
        self._label_events.setText("0 events")
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_save.setEnabled(False)
        self._timer.start()
        self.start_recording.emit()

    def _on_stop(self) -> None:
        self._is_recording = False
        self._has_unsaved_recording = True
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_save.setEnabled(True)
        self._timer.stop()
        self.stop_recording.emit()

    def _on_save(self) -> None:
        self.save_recording.emit()

    def _tick(self) -> None:
        """Update the elapsed time display every second."""
        self._elapsed_seconds += 1
        h = self._elapsed_seconds // 3600
        m = (self._elapsed_seconds % 3600) // 60
        s = self._elapsed_seconds % 60
        self._label_timer.setText(f"{h:02d}:{m:02d}:{s:02d}")


# ============================================================
# File: ui/logs_panel.py
# ============================================================
"""
logs_panel.py — Scrollable, colour-coded log viewer.

Displays timestamped messages from all parts of the application.
Messages are colour-coded by severity level.
"""

# Colour codes for log levels
_COLOURS = {
    "info": "#b0b8d0",
    "success": "#00d68f",
    "warning": "#ffaa00",
    "error": "#e94560",
    "debug": "#6070a0",
}


class LogsPanel(QGroupBox):
    """
    Read-only log display with auto-scroll and colour-coded messages.
    """

    def __init__(self, parent=None):
        super().__init__("Activity Log", parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Log display
        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setMinimumHeight(100)
        layout.addWidget(self._text_edit)

        # Clear button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_clear = QPushButton("Clear Logs")
        self._btn_clear.setFixedWidth(100)
        self._btn_clear.clicked.connect(self._text_edit.clear)
        btn_row.addWidget(self._btn_clear)
        layout.addLayout(btn_row)

    # ── Public API ─────────────────────────────────────────────────

    def log(self, message: str, level: str = "info") -> None:
        """
        Append a timestamped, colour-coded message.

        Args:
            message: The log message text.
            level:   One of "info", "success", "warning", "error", "debug".
        """
        colour = _COLOURS.get(level, _COLOURS["info"])
        timestamp = datetime.now().strftime("%H:%M:%S")
        html = (
            f'<span style="color:#4a5a8a;">[{timestamp}]</span> '
            f'<span style="color:{colour};">{message}</span>'
        )
        self._text_edit.append(html)

        # Auto-scroll to bottom
        scrollbar = self._text_edit.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def log_info(self, message: str) -> None:
        self.log(message, "info")

    def log_success(self, message: str) -> None:
        self.log(message, "success")

    def log_warning(self, message: str) -> None:
        self.log(message, "warning")

    def log_error(self, message: str) -> None:
        self.log(message, "error")

    def set_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable controls based on device connection."""
        self._btn_clear.setEnabled(enabled)


# ============================================================
# File: ui/iteration_panel.py
# ============================================================
"""
iteration_panel.py — Iteration configuration and playback controls.

Provides inputs for iteration count, delay between iterations,
infinite loop toggle, and Run/Pause/Resume/Stop buttons.
"""


class IterationPanel(QGroupBox):
    """
    Iteration settings and execution controls.

    Signals:
        run_clicked(int, int, bool): Emitted with (iterations, delay_ms, infinite_loop)
        pause_clicked():             Emitted when Pause is pressed.
        resume_clicked():            Emitted when Resume is pressed.
        stop_clicked():              Emitted when Stop is pressed.
    """

    run_clicked = pyqtSignal(int, int, bool)
    pause_clicked = pyqtSignal()
    resume_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Execution Settings", parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Iterations input ──
        iter_row = QHBoxLayout()
        iter_label = QLabel("Iterations:")
        iter_label.setFixedWidth(130)
        iter_row.addWidget(iter_label)

        self._input_iterations = QLineEdit("1")
        self._input_iterations.setValidator(QIntValidator(1, 999999))
        self._input_iterations.setPlaceholderText("e.g. 100")
        self._input_iterations.setFixedWidth(120)
        iter_row.addWidget(self._input_iterations)
        iter_row.addStretch()
        layout.addLayout(iter_row)

        # ── Delay input ──
        delay_row = QHBoxLayout()
        delay_label = QLabel("Delay between (ms):")
        delay_label.setFixedWidth(130)
        delay_row.addWidget(delay_label)

        self._input_delay = QLineEdit("0")
        self._input_delay.setValidator(QIntValidator(0, 999999))
        self._input_delay.setPlaceholderText("e.g. 1000")
        self._input_delay.setFixedWidth(120)
        delay_row.addWidget(self._input_delay)
        delay_row.addStretch()
        layout.addLayout(delay_row)

        # ── Infinite loop checkbox ──
        self._chk_infinite = QCheckBox("Run Until Stopped")
        self._chk_infinite.stateChanged.connect(self._on_infinite_toggled)
        layout.addWidget(self._chk_infinite)

        # ── Run button ──
        self._btn_run = QPushButton("▶  Run Recording")
        self._btn_run.setObjectName("btn_run")
        self._btn_run.clicked.connect(self._on_run)
        layout.addWidget(self._btn_run)

        # ── Playback control buttons (hidden until running) ──
        self._controls_widget = QWidget()
        controls_layout = QHBoxLayout(self._controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)

        self._btn_pause = QPushButton("⏸  Pause")
        self._btn_pause.setObjectName("btn_pause")
        self._btn_pause.clicked.connect(self.pause_clicked.emit)
        controls_layout.addWidget(self._btn_pause)

        self._btn_resume = QPushButton("▶  Resume")
        self._btn_resume.setObjectName("btn_resume")
        self._btn_resume.setEnabled(False)
        self._btn_resume.clicked.connect(self.resume_clicked.emit)
        controls_layout.addWidget(self._btn_resume)

        self._btn_stop = QPushButton("⏹  Stop")
        self._btn_stop.setObjectName("btn_stop_execution")
        self._btn_stop.clicked.connect(self.stop_clicked.emit)
        controls_layout.addWidget(self._btn_stop)

        self._controls_widget.setVisible(False)
        layout.addWidget(self._controls_widget)

    # ── Public API ─────────────────────────────────────────────────

    def set_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable based on device connection and recording state."""
        self._btn_run.setEnabled(enabled)
        self._input_iterations.setEnabled(enabled)
        self._input_delay.setEnabled(enabled)
        self._chk_infinite.setEnabled(enabled)

    def set_running(self, running: bool) -> None:
        """Switch between config mode and running mode."""
        self._btn_run.setVisible(not running)
        self._input_iterations.setEnabled(not running)
        self._input_delay.setEnabled(not running)
        self._chk_infinite.setEnabled(not running)
        self._controls_widget.setVisible(running)
        if running:
            self._btn_pause.setEnabled(True)
            self._btn_resume.setEnabled(False)

    def set_paused(self, paused: bool) -> None:
        """Toggle pause/resume button states."""
        self._btn_pause.setEnabled(not paused)
        self._btn_resume.setEnabled(paused)

    def get_iterations(self) -> int:
        """Get the configured iteration count."""
        try:
            return max(1, int(self._input_iterations.text()))
        except ValueError:
            return 1

    def get_delay_ms(self) -> int:
        """Get the configured delay in milliseconds."""
        try:
            return max(0, int(self._input_delay.text()))
        except ValueError:
            return 0

    def is_infinite(self) -> bool:
        """Check if infinite loop mode is enabled."""
        return self._chk_infinite.isChecked()

    # ── Slots ──────────────────────────────────────────────────────

    def _on_run(self) -> None:
        iters = self.get_iterations()
        delay = self.get_delay_ms()
        infinite = self.is_infinite()
        self.run_clicked.emit(iters, delay, infinite)

    def _on_infinite_toggled(self, state: int) -> None:
        """Disable iteration count when infinite loop is checked."""
        infinite = state == Qt.CheckState.Checked.value
        self._input_iterations.setEnabled(not infinite)
        if infinite:
            self._input_iterations.setText("∞")
        else:
            self._input_iterations.setText("1")


# ============================================================
# File: ui/progress_panel.py
# ============================================================
"""
progress_panel.py — Progress display panel.

Shows a gradient progress bar and labels for current iteration,
remaining iterations, and estimated time.
"""


class ProgressPanel(QGroupBox):
    """
    Progress bar and iteration tracking display.
    """

    def __init__(self, parent=None):
        super().__init__("Progress", parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("%p%")
        layout.addWidget(self._progress_bar)

        # Iteration info row
        info_row = QHBoxLayout()

        # Current iteration
        col1 = QVBoxLayout()
        lbl1 = QLabel("CURRENT")
        lbl1.setObjectName("label_stat_label")
        lbl1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col1.addWidget(lbl1)
        self._label_current = QLabel("—")
        self._label_current.setObjectName("label_iteration_info")
        self._label_current.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col1.addWidget(self._label_current)
        info_row.addLayout(col1)

        # Remaining
        col2 = QVBoxLayout()
        lbl2 = QLabel("REMAINING")
        lbl2.setObjectName("label_stat_label")
        lbl2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col2.addWidget(lbl2)
        self._label_remaining = QLabel("—")
        self._label_remaining.setObjectName("label_iteration_info")
        self._label_remaining.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col2.addWidget(self._label_remaining)
        info_row.addLayout(col2)

        layout.addLayout(info_row)

    # ── Public API ─────────────────────────────────────────────────

    def set_progress(self, percent: int) -> None:
        """Update the progress bar (0–100)."""
        self._progress_bar.setValue(min(100, max(0, percent)))

    def set_iteration_info(self, current: int, total: int) -> None:
        """Update the current iteration display."""
        if total < 0:
            # Infinite mode
            self._label_current.setText(f"Iteration {current}")
            self._label_remaining.setText("∞")
        else:
            self._label_current.setText(f"{current} / {total}")
            remaining = max(0, total - current)
            self._label_remaining.setText(str(remaining))

    def reset(self) -> None:
        """Reset all displays to initial state."""
        self._progress_bar.setValue(0)
        self._label_current.setText("—")
        self._label_remaining.setText("—")

    def set_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable based on device connection."""
        # Progress panel is display-only, but we dim it when disabled
        self._progress_bar.setEnabled(enabled)


# ============================================================
# File: ui/statistics_panel.py
# ============================================================
"""
statistics_panel.py — Execution statistics display.

Shows total iterations, completed, remaining, execution time,
and average iteration duration in a grid of stat cards.
"""


class _StatCard(QFrame):
    """A single statistic display card with label and value."""

    def __init__(self, label_text: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background-color: #0c1025; border-radius: 8px; padding: 8px; }"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(2)
        layout.setContentsMargins(10, 8, 10, 8)

        self._label = QLabel(label_text)
        self._label.setObjectName("label_stat_label")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

        self._value = QLabel("—")
        self._value.setObjectName("label_stat_value")
        self._value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._value)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


class StatisticsPanel(QGroupBox):
    """
    Grid display of execution statistics.
    """

    def __init__(self, parent=None):
        super().__init__("Statistics", parent)
        self._init_ui()

    def _init_ui(self) -> None:
        grid = QGridLayout(self)
        grid.setSpacing(8)

        self._card_total = _StatCard("TOTAL")
        grid.addWidget(self._card_total, 0, 0)

        self._card_completed = _StatCard("COMPLETED")
        grid.addWidget(self._card_completed, 0, 1)

        self._card_remaining = _StatCard("REMAINING")
        grid.addWidget(self._card_remaining, 1, 0)

        self._card_time = _StatCard("ELAPSED")
        grid.addWidget(self._card_time, 1, 1)

        self._card_avg = _StatCard("AVG / ITER")
        grid.addWidget(self._card_avg, 2, 0, 1, 2)

    # ── Public API ─────────────────────────────────────────────────

    def update_stats(self, stats: dict) -> None:
        """
        Update statistics display.

        Args:
            stats: Dict with keys: total, completed, remaining, elapsed
        """
        total = stats.get("total", 0)
        completed = stats.get("completed", 0)
        remaining = stats.get("remaining", 0)
        elapsed = stats.get("elapsed", 0.0)

        # Total
        self._card_total.set_value("∞" if total < 0 else str(total))

        # Completed
        self._card_completed.set_value(str(completed))

        # Remaining
        self._card_remaining.set_value("∞" if remaining < 0 else str(remaining))

        # Elapsed time
        self._card_time.set_value(self._format_time(elapsed))

        # Average time per iteration
        if completed > 0:
            avg = elapsed / completed
            self._card_avg.set_value(self._format_time(avg))
        else:
            self._card_avg.set_value("—")

    def reset(self) -> None:
        """Reset all statistics to initial state."""
        for card in [
            self._card_total,
            self._card_completed,
            self._card_remaining,
            self._card_time,
            self._card_avg,
        ]:
            card.set_value("—")

    def set_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable based on device connection."""
        self.setEnabled(enabled)

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds into HH:MM:SS."""
        h = int(seconds) // 3600
        m = (int(seconds) % 3600) // 60
        s = int(seconds) % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"


# ============================================================
# File: ui/library_panel.py
# ============================================================
"""
library_panel.py — Saved recording library with search, favourites, and actions.

Displays all saved recordings in a list, with search filtering,
favourite toggling, and context actions (Load, Run, Rename, Delete,
Export, Import).
"""


class LibraryPanel(QGroupBox):
    """
    Saved recordings library with search and actions.

    Signals:
        recording_loaded(str):   Emitted with recording name when Load is clicked.
        recording_run(str):      Emitted with recording name when Run is clicked.
        recording_deleted(str):  Emitted with recording name when Delete confirms.
        recording_renamed(str, str): Emitted with (old_name, new_name).
        favorite_toggled(str):   Emitted with recording name.
        export_requested(str, str): Emitted with (recording_name, format).
        import_requested(str):   Emitted with the file path to import.
    """

    recording_loaded = pyqtSignal(str)
    recording_run = pyqtSignal(str)
    recording_deleted = pyqtSignal(str)
    recording_renamed = pyqtSignal(str, str)
    favorite_toggled = pyqtSignal(str)
    export_requested = pyqtSignal(str, str)
    import_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Recording Library", parent)
        self._recordings: list[dict] = []
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ── Search bar ──
        search_row = QHBoxLayout()
        search_icon = QLabel("🔍")
        search_row.addWidget(search_icon)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search recordings...")
        self._search_input.textChanged.connect(self._on_search)
        search_row.addWidget(self._search_input)
        layout.addLayout(search_row)

        # ── Recording list ──
        self._list_widget = QListWidget()
        self._list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self._list_widget.setMinimumHeight(120)
        layout.addWidget(self._list_widget)

        # ── Action buttons row 1 ──
        btn_row1 = QHBoxLayout()
        btn_row1.setSpacing(6)

        self._btn_load = QPushButton("📂 Load")
        self._btn_load.clicked.connect(self._on_load)
        btn_row1.addWidget(self._btn_load)

        self._btn_run = QPushButton("▶ Run")
        self._btn_run.clicked.connect(self._on_run)
        btn_row1.addWidget(self._btn_run)

        self._btn_delete = QPushButton("🗑 Delete")
        self._btn_delete.clicked.connect(self._on_delete)
        btn_row1.addWidget(self._btn_delete)

        layout.addLayout(btn_row1)

        # ── Action buttons row 2 ──
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(6)

        self._btn_rename = QPushButton("✏ Rename")
        self._btn_rename.clicked.connect(self._on_rename)
        btn_row2.addWidget(self._btn_rename)

        self._btn_favorite = QPushButton("★ Favorite")
        self._btn_favorite.clicked.connect(self._on_favorite)
        btn_row2.addWidget(self._btn_favorite)

        layout.addLayout(btn_row2)

        # ── Import / Export buttons ──
        btn_row3 = QHBoxLayout()
        btn_row3.setSpacing(6)

        self._btn_export = QPushButton("📤 Export")
        self._btn_export.clicked.connect(self._on_export)
        btn_row3.addWidget(self._btn_export)

        self._btn_import = QPushButton("📥 Import")
        self._btn_import.clicked.connect(self._on_import)
        btn_row3.addWidget(self._btn_import)

        layout.addLayout(btn_row3)

    # ── Public API ─────────────────────────────────────────────────

    def refresh_list(self, recordings: list[dict]) -> None:
        """Update the list with recording metadata."""
        self._recordings = recordings
        self._populate_list(recordings)

    def set_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable all controls."""
        self._search_input.setEnabled(enabled)
        self._list_widget.setEnabled(enabled)
        for btn in [
            self._btn_load,
            self._btn_run,
            self._btn_delete,
            self._btn_rename,
            self._btn_favorite,
            self._btn_export,
            self._btn_import,
        ]:
            btn.setEnabled(enabled)

    # ── Internal helpers ───────────────────────────────────────────

    def _populate_list(self, recordings: list[dict]) -> None:
        """Fill the list widget with recording entries."""
        self._list_widget.clear()
        for rec in recordings:
            star = "★ " if rec.get("favorite") else ""
            events = rec.get("event_count", 0)
            text = f"{star}{rec['name']}  ({events} events)"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, rec["name"])
            self._list_widget.addItem(item)

    def _selected_name(self) -> str | None:
        """Get the name of the currently selected recording."""
        item = self._list_widget.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    # ── Slots ──────────────────────────────────────────────────────

    def _on_search(self, query: str) -> None:
        if not query:
            self._populate_list(self._recordings)
        else:
            q = query.lower()
            filtered = [r for r in self._recordings if q in r["name"].lower()]
            self._populate_list(filtered)

    def _on_load(self) -> None:
        name = self._selected_name()
        if name:
            self.recording_loaded.emit(name)

    def _on_run(self) -> None:
        name = self._selected_name()
        if name:
            self.recording_run.emit(name)

    def _on_delete(self) -> None:
        name = self._selected_name()
        if not name:
            return
        reply = QMessageBox.question(
            self,
            "Delete Recording",
            f"Are you sure you want to delete '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.recording_deleted.emit(name)

    def _on_rename(self) -> None:
        name = self._selected_name()
        if not name:
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Recording",
            "Enter new name:",
            text=name,
        )
        if ok and new_name and new_name != name:
            self.recording_renamed.emit(name, new_name)

    def _on_favorite(self) -> None:
        name = self._selected_name()
        if name:
            self.favorite_toggled.emit(name)

    def _on_export(self) -> None:
        name = self._selected_name()
        if not name:
            return
        # Show format selection menu
        menu = QMenu(self)
        act_json = menu.addAction("Export as JSON")
        act_csv = menu.addAction("Export as CSV")
        action = menu.exec(
            self._btn_export.mapToGlobal(self._btn_export.rect().center())
        )
        if action == act_json:
            self.export_requested.emit(name, "json")
        elif action == act_csv:
            self.export_requested.emit(name, "csv")

    def _on_import(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Import Recording",
            "",
            "JSON Files (*.json);;CSV Files (*.csv);;All Files (*)",
        )
        if filepath:
            self.import_requested.emit(filepath)

    def _show_context_menu(self, pos) -> None:
        """Show right-click context menu on list items."""
        item = self._list_widget.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        menu.addAction("📂 Load", self._on_load)
        menu.addAction("▶ Run", self._on_run)
        menu.addSeparator()
        menu.addAction("✏ Rename", self._on_rename)
        menu.addAction("★ Toggle Favorite", self._on_favorite)
        menu.addSeparator()
        menu.addAction("📤 Export", self._on_export)
        menu.addSeparator()
        menu.addAction("🗑 Delete", self._on_delete)
        menu.exec(self._list_widget.mapToGlobal(pos))


# ============================================================
# File: ui/main_window.py
# ============================================================
"""
main_window.py — Main application window.

Orchestrates all panels, the event recorder, playback workers,
and storage managers. Implements the full record → save → configure → run workflow.
"""


class MainWindow(QMainWindow):
    """
    The main application window for Automotive Infotainment
    Defect Reproduction Automation.
    """

    def __init__(self, base_dir: str = ""):
        super().__init__()

        # ── Resolve paths relative to the project root ──
        if not base_dir:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            base_dir = os.path.dirname(base_dir)  # go up from ui/

        recordings_dir = os.path.join(base_dir, "recordings")
        exports_dir = os.path.join(base_dir, "exports")

        # ── Core components ──
        self._recorder = EventRecorder()
        self._recording_manager = RecordingManager(recordings_dir)
        self._export_manager = ExportManager(exports_dir)
        self._current_recording: Recording | None = None
        self._playback_worker: PlaybackWorker | None = None
        self._device_serial = ""

        # ── UI Setup ──
        self.setWindowTitle("Automotive Infotainment — Defect Reproduction Automation")
        self.setMinimumSize(1280, 800)
        self.resize(1440, 900)

        self._init_ui()
        self._connect_signals()

        # ── Event count update timer ──
        self._event_timer = QTimer(self)
        self._event_timer.setInterval(250)
        self._event_timer.timeout.connect(self._update_event_count)

        # ── Initial device check ──
        QTimer.singleShot(300, self._device_panel.check_device)

    # ══════════════════════════════════════════════════════════════
    #  UI CONSTRUCTION
    # ══════════════════════════════════════════════════════════════

    def _init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # ── Splitter: left (canvas + logs) | right (control panels) ──
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(3)

        # ── LEFT COLUMN ──────────────────────────────────────────
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # Canvas
        self._canvas = CanvasWidget()
        left_layout.addWidget(self._canvas, stretch=3)

        # Logs
        self._logs_panel = LogsPanel()
        left_layout.addWidget(self._logs_panel, stretch=1)

        splitter.addWidget(left_widget)

        # ── RIGHT COLUMN (scrollable) ────────────────────────────
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setMinimumWidth(340)
        right_scroll.setMaximumWidth(420)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 4, 0)
        right_layout.setSpacing(8)

        # Panels in order
        self._device_panel = DevicePanel()
        right_layout.addWidget(self._device_panel)

        self._recording_panel = RecordingPanel()
        right_layout.addWidget(self._recording_panel)

        self._iteration_panel = IterationPanel()
        right_layout.addWidget(self._iteration_panel)

        self._progress_panel = ProgressPanel()
        right_layout.addWidget(self._progress_panel)

        self._statistics_panel = StatisticsPanel()
        right_layout.addWidget(self._statistics_panel)

        self._library_panel = LibraryPanel()
        right_layout.addWidget(self._library_panel)

        right_layout.addStretch()

        right_scroll.setWidget(right_widget)
        splitter.addWidget(right_scroll)

        # Set splitter proportions (65% / 35%)
        splitter.setSizes([900, 400])

        main_layout.addWidget(splitter)

        # ── Initially disable everything until device connected ──
        self._set_all_controls_enabled(False)

    # ══════════════════════════════════════════════════════════════
    #  SIGNAL CONNECTIONS
    # ══════════════════════════════════════════════════════════════

    def _connect_signals(self) -> None:
        # Device panel
        self._device_panel.device_connected.connect(self._on_device_status)

        # Recording panel
        self._recording_panel.start_recording.connect(self._on_start_recording)
        self._recording_panel.stop_recording.connect(self._on_stop_recording)
        self._recording_panel.save_recording.connect(self._on_save_recording)

        # Canvas → Recorder
        self._canvas.mouse_pressed.connect(self._recorder.on_mouse_press)
        self._canvas.mouse_moved.connect(self._recorder.on_mouse_move)
        self._canvas.mouse_released.connect(self._recorder.on_mouse_release)
        self._canvas.key_pressed.connect(self._recorder.record_key)

        # Iteration panel
        self._iteration_panel.run_clicked.connect(self._on_run)
        self._iteration_panel.pause_clicked.connect(self._on_pause)
        self._iteration_panel.resume_clicked.connect(self._on_resume)
        self._iteration_panel.stop_clicked.connect(self._on_stop)

        # Library panel
        self._library_panel.recording_loaded.connect(self._on_library_load)
        self._library_panel.recording_run.connect(self._on_library_run)
        self._library_panel.recording_deleted.connect(self._on_library_delete)
        self._library_panel.recording_renamed.connect(self._on_library_rename)
        self._library_panel.favorite_toggled.connect(self._on_library_favorite)
        self._library_panel.export_requested.connect(self._on_export)
        self._library_panel.import_requested.connect(self._on_import)

    # ══════════════════════════════════════════════════════════════
    #  DEVICE STATUS
    # ══════════════════════════════════════════════════════════════

    def _on_device_status(self, connected: bool, serial: str) -> None:
        """Handle device connection status changes."""
        self._device_serial = serial
        self._set_all_controls_enabled(connected)
        self._canvas.set_enabled(connected)

        if connected:
            self._logs_panel.log_success(f"Device connected: {serial}")
            self._refresh_library()
        else:
            self._logs_panel.log_error("No device connected")

    def _set_all_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable all panels based on device connection."""
        self._recording_panel.set_controls_enabled(enabled)
        self._iteration_panel.set_controls_enabled(enabled)
        self._progress_panel.set_controls_enabled(enabled)
        self._logs_panel.set_controls_enabled(enabled)
        self._library_panel.set_controls_enabled(enabled)
        self._statistics_panel.set_controls_enabled(enabled)

    # ══════════════════════════════════════════════════════════════
    #  RECORDING
    # ══════════════════════════════════════════════════════════════

    def _on_start_recording(self) -> None:
        """Start capturing events on the canvas."""
        self._recorder.start("untitled")
        self._canvas.set_recording(True)
        self._event_timer.start()
        self._iteration_panel.set_controls_enabled(False)
        self._logs_panel.log_info("⏺ Recording started — interact with the canvas")

    def _on_stop_recording(self) -> None:
        """Stop capturing and store the recording in memory."""
        self._canvas.set_recording(False)
        self._event_timer.stop()
        self._current_recording = self._recorder.stop()
        self._iteration_panel.set_controls_enabled(True)

        event_count = self._current_recording.event_count
        self._logs_panel.log_info(
            f"⏹ Recording stopped — {event_count} events captured"
        )

        # Show confirmation dialog
        reply = QMessageBox.question(
            self,
            "Recording Completed",
            "Recording completed.\n\nDo you want to save this recording?",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Ok:
            self._on_save_recording()

    def _on_save_recording(self) -> None:
        """Prompt for a name and save the current recording."""
        if not self._current_recording:
            self._logs_panel.log_warning("No recording to save")
            return

        name, ok = QInputDialog.getText(
            self,
            "Save Recording",
            "Enter a name for this recording:",
            text=(
                self._current_recording.name
                if self._current_recording.name != "untitled"
                else ""
            ),
        )
        if not ok or not name:
            return

        self._current_recording.name = name
        try:
            path = self._recording_manager.save(self._current_recording)
            self._logs_panel.log_success(f"💾 Recording saved: {name}")
            self._refresh_library()
            self._recording_panel.reset()
        except Exception as e:
            self._logs_panel.log_error(f"Save failed: {str(e)}")

    def _update_event_count(self) -> None:
        """Periodically update the event counter during recording."""
        if self._recorder.is_recording:
            self._recording_panel.update_event_count(self._recorder.event_count)

    # ══════════════════════════════════════════════════════════════
    #  PLAYBACK
    # ══════════════════════════════════════════════════════════════

    def _on_run(self, iterations: int, delay_ms: int, infinite: bool) -> None:
        """Start replaying the current recording."""
        if not self._current_recording:
            self._logs_panel.log_warning(
                "No recording loaded. Record or load one first."
            )
            return

        if self._current_recording.event_count == 0:
            self._logs_panel.log_warning("Recording has no events to replay.")
            return

        # Reset progress and statistics
        self._progress_panel.reset()
        self._statistics_panel.reset()

        # Create and start playback worker
        self._playback_worker = PlaybackWorker(
            recording=self._current_recording,
            device_serial=self._device_serial,
            iterations=iterations,
            delay_ms=delay_ms,
            infinite_loop=infinite,
        )

        # Connect worker signals
        self._playback_worker.iteration_started.connect(self._on_iteration_started)
        self._playback_worker.iteration_completed.connect(self._on_iteration_completed)
        self._playback_worker.event_played.connect(self._on_event_played)
        self._playback_worker.progress_updated.connect(
            self._progress_panel.set_progress
        )
        self._playback_worker.playback_finished.connect(self._on_playback_finished)
        self._playback_worker.error_occurred.connect(self._on_playback_error)
        self._playback_worker.stats_updated.connect(self._statistics_panel.update_stats)

        # Update UI state
        self._iteration_panel.set_running(True)
        self._recording_panel.set_controls_enabled(False)

        total_str = "∞" if infinite else str(iterations)
        self._logs_panel.log_info(
            f"▶ Playback started — {total_str} iterations, " f"{delay_ms}ms delay"
        )

        self._playback_worker.start()

    def _on_pause(self) -> None:
        if self._playback_worker:
            self._playback_worker.pause()
            self._iteration_panel.set_paused(True)
            self._logs_panel.log_warning("⏸ Playback paused")

    def _on_resume(self) -> None:
        if self._playback_worker:
            self._playback_worker.resume()
            self._iteration_panel.set_paused(False)
            self._logs_panel.log_info("▶ Playback resumed")

    def _on_stop(self) -> None:
        if self._playback_worker:
            self._playback_worker.stop()
            self._logs_panel.log_warning("⏹ Playback stopped by user")

    def _on_iteration_started(self, iteration: int) -> None:
        total = self._playback_worker._iterations if self._playback_worker else 1
        infinite = (
            self._playback_worker._infinite_loop if self._playback_worker else False
        )
        t = -1 if infinite else total
        self._progress_panel.set_iteration_info(iteration, t)

    def _on_iteration_completed(self, iteration: int) -> None:
        self._logs_panel.log_success(f"✅ Iteration {iteration} completed")

    def _on_event_played(self, index: int, description: str) -> None:
        # Log individual events at debug level (don't flood the log)
        pass

    def _on_playback_finished(self) -> None:
        self._iteration_panel.set_running(False)
        self._recording_panel.set_controls_enabled(True)
        self._logs_panel.log_success("🏁 Playback finished")
        self._playback_worker = None

    def _on_playback_error(self, message: str) -> None:
        self._logs_panel.log_error(f"⚠ {message}")

    # ══════════════════════════════════════════════════════════════
    #  LIBRARY
    # ══════════════════════════════════════════════════════════════

    def _refresh_library(self) -> None:
        """Reload the recording list in the library panel."""
        recordings = self._recording_manager.list_all()
        self._library_panel.refresh_list(recordings)

    def _on_library_load(self, name: str) -> None:
        """Load a recording from the library."""
        try:
            self._current_recording = self._recording_manager.load(name)
            self._logs_panel.log_info(
                f"📂 Loaded recording: {name} "
                f"({self._current_recording.event_count} events)"
            )
        except Exception as e:
            self._logs_panel.log_error(f"Load failed: {str(e)}")

    def _on_library_run(self, name: str) -> None:
        """Load and immediately run a recording from the library."""
        self._on_library_load(name)
        if self._current_recording:
            iters = self._iteration_panel.get_iterations()
            delay = self._iteration_panel.get_delay_ms()
            infinite = self._iteration_panel.is_infinite()
            self._on_run(iters, delay, infinite)

    def _on_library_delete(self, name: str) -> None:
        """Delete a recording from the library."""
        try:
            self._recording_manager.delete(name)
            self._logs_panel.log_info(f"🗑 Deleted recording: {name}")
            self._refresh_library()
        except Exception as e:
            self._logs_panel.log_error(f"Delete failed: {str(e)}")

    def _on_library_rename(self, old_name: str, new_name: str) -> None:
        """Rename a recording in the library."""
        try:
            if self._recording_manager.rename(old_name, new_name):
                self._logs_panel.log_info(f"✏ Renamed: {old_name} → {new_name}")
                self._refresh_library()
            else:
                self._logs_panel.log_warning("Rename failed — name may already exist")
        except Exception as e:
            self._logs_panel.log_error(f"Rename failed: {str(e)}")

    def _on_library_favorite(self, name: str) -> None:
        """Toggle favourite status of a recording."""
        try:
            is_fav = self._recording_manager.toggle_favorite(name)
            status = "★ Favourited" if is_fav else "☆ Unfavourited"
            self._logs_panel.log_info(f"{status}: {name}")
            self._refresh_library()
        except Exception as e:
            self._logs_panel.log_error(f"Favourite toggle failed: {str(e)}")

    # ══════════════════════════════════════════════════════════════
    #  EXPORT / IMPORT
    # ══════════════════════════════════════════════════════════════

    def _on_export(self, name: str, fmt: str) -> None:
        """Export a recording in the specified format."""
        try:
            recording = self._recording_manager.load(name)
            if fmt == "json":
                path = self._export_manager.export_json(recording)
            elif fmt == "csv":
                path = self._export_manager.export_csv(recording)
            else:
                self._logs_panel.log_warning(f"Unknown export format: {fmt}")
                return
            self._logs_panel.log_success(f"📤 Exported to: {path}")
        except Exception as e:
            self._logs_panel.log_error(f"Export failed: {str(e)}")

    def _on_import(self, filepath: str) -> None:
        """Import a recording from a file."""
        try:
            if filepath.lower().endswith(".csv"):
                recording = self._export_manager.import_csv(filepath)
            else:
                recording = self._export_manager.import_json(filepath)

            # Save into the recordings directory
            self._recording_manager.save(recording)
            self._logs_panel.log_success(f"📥 Imported: {recording.name}")
            self._refresh_library()
        except Exception as e:
            self._logs_panel.log_error(f"Import failed: {str(e)}")

    # ══════════════════════════════════════════════════════════════
    #  WINDOW CLOSE
    # ══════════════════════════════════════════════════════════════

    def closeEvent(self, event) -> None:
        """Ensure playback is stopped before closing."""
        if self._playback_worker and self._playback_worker.isRunning():
            self._playback_worker.stop()
            self._playback_worker.wait(3000)
        event.accept()


# ============================================================
# File: main.py
# ============================================================
"""
main.py — Application entry point.

Automotive Infotainment Defect Reproduction Automation Tool
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A PyQt6 desktop application for recording and replaying user actions
on AOSP/Android Automotive infotainment systems.

Usage:
    python main.py

Requirements:
    - Python 3.11+
    - PyQt6 >= 6.6.0
    - ADB (Android Debug Bridge) on system PATH
"""


def main() -> int:
    """Initialise and run the application."""

    # ── Resolve the project base directory ──
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # ── Ensure required directories exist ──
    for subdir in ("recordings", "exports", "assets"):
        os.makedirs(os.path.join(base_dir, subdir), exist_ok=True)

    # ── Create Qt Application ──
    app = QApplication(sys.argv)
    app.setApplicationName("Infotainment Defect Reproduction")
    app.setOrganizationName("AutomotiveQA")

    # ── Apply dark theme stylesheet ──
    app.setStyleSheet(DARK_THEME)

    # ── Set default font ──
    font = QFont("Segoe UI", 10)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)

    # ── Create and show the main window ──
    window = MainWindow(base_dir=base_dir)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
