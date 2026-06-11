"""
AOSP IVI Reproduction Tool
==========================
Production-ready Tkinter GUI for recording and replaying
touch interactions on AOSP-based Infotainment ECUs via ADB.

Author  : Built for Automotive Test Engineers
Requires: Python 3.8+  |  pip install pillow
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import subprocess
import threading
import time
import json
import os
import re
import datetime
import queue
from pathlib import Path

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# ─── COLOUR PALETTE ──────────────────────────────────────────────────────────
C = {
    "bg":        "#0F1923",
    "surface":   "#162030",
    "raised":    "#1E2D40",
    "border":    "#243548",
    "teal":      "#00D4C8",
    "teal_dim":  "#007A74",
    "amber":     "#F59E0B",
    "green":     "#22C55E",
    "red":       "#EF4444",
    "blue":      "#3B82F6",
    "purple":    "#8B5CF6",
    "text":      "#E8F4FD",
    "muted":     "#7A9BBF",
    "subtle":    "#4A6B8A",
    "white":     "#FFFFFF",
}

FONT_TITLE  = ("Segoe UI", 13, "bold")
FONT_LABEL  = ("Segoe UI", 10)
FONT_BOLD   = ("Segoe UI", 10, "bold")
FONT_SMALL  = ("Segoe UI", 9)
FONT_MONO   = ("Consolas", 9)
FONT_MONO_S = ("Consolas", 8)

STEP_ICONS = {
    "tap":        "👆",
    "swipe":      "👉",
    "wait":       "⏱",
    "keyevent":   "⌨",
    "launch_app": "🚀",
    "setprop":    "🔧",
}


# ─── ADB HELPER ──────────────────────────────────────────────────────────────
class ADB:
    """Thread-safe ADB wrapper with error handling."""

    @staticmethod
    def run(cmd: str, timeout: int = 10) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                f"adb {cmd}", shell=True,
                capture_output=True, text=True, timeout=timeout
            )
            out = (result.stdout + result.stderr).strip()
            return result.returncode == 0, out
        except subprocess.TimeoutExpired:
            return False, "TIMEOUT"
        except FileNotFoundError:
            return False, "ADB_NOT_FOUND"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def device_connected() -> tuple[bool, str]:
        ok, out = ADB.run("devices")
        if not ok:
            return False, "adb not found"
        lines = [l for l in out.splitlines() if "\tdevice" in l]
        if lines:
            serial = lines[0].split("\t")[0]
            return True, serial
        if "offline" in out:
            return False, "device offline"
        return False, "no device"

    @staticmethod
    def tap(x: int, y: int) -> bool:
        ok, _ = ADB.run(f"shell input tap {x} {y}")
        return ok

    @staticmethod
    def swipe(x1: int, y1: int, x2: int, y2: int, ms: int) -> bool:
        ok, _ = ADB.run(f"shell input swipe {x1} {y1} {x2} {y2} {ms}")
        return ok

    @staticmethod
    def keyevent(code: str) -> bool:
        ok, _ = ADB.run(f"shell input keyevent {code}")
        return ok

    @staticmethod
    def launch_app(package: str, activity: str = "") -> bool:
        if activity:
            ok, _ = ADB.run(f"shell am start -n {package}/{activity}")
        else:
            ok, _ = ADB.run(f"shell monkey -p {package} -c android.intent.category.LAUNCHER 1")
        return ok

    @staticmethod
    def setprop(key: str, value: str) -> bool:
        ok, _ = ADB.run(f"shell setprop {key} {value}")
        return ok

    @staticmethod
    def screenshot(path: str) -> bool:
        ok, _ = ADB.run(f"shell screencap -p /sdcard/_repro_tmp.png")
        if not ok:
            return False
        ok2, _ = ADB.run(f"pull /sdcard/_repro_tmp.png {path}")
        return ok2

    @staticmethod
    def logcat_snapshot(lines: int = 80) -> str:
        ok, out = ADB.run(f"shell logcat -d -t {lines} *:W", timeout=8)
        return out if ok else ""

    @staticmethod
    def clear_logcat() -> None:
        ADB.run("shell logcat -c")

    @staticmethod
    def get_screen_size() -> tuple[int, int]:
        ok, out = ADB.run("shell wm size")
        m = re.search(r"(\d+)x(\d+)", out)
        if m:
            return int(m.group(1)), int(m.group(2))
        return 1920, 720


# ─── CRASH DETECTOR ──────────────────────────────────────────────────────────
CRASH_PATTERNS = [
    "FATAL EXCEPTION",
    "ANR in",
    "Process.*crashed",
    "java.lang.NullPointerException",
    "java.lang.RuntimeException",
    "Watchdog.*killing",
    "Native crash",
    "Segmentation fault",
    "SIGSEGV",
    "force stop",
]

def detect_crash(logcat_text: str) -> tuple[bool, str]:
    for pattern in CRASH_PATTERNS:
        if re.search(pattern, logcat_text, re.IGNORECASE):
            for line in logcat_text.splitlines():
                if re.search(pattern, line, re.IGNORECASE):
                    return True, line.strip()
    return False, ""


# ─── TOOLTIP ─────────────────────────────────────────────────────────────────
class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tw = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _=None):
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tw = tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(self.tw, text=self.text, font=FONT_SMALL,
                       bg=C["raised"], fg=C["teal"], relief="flat",
                       padx=8, pady=4, bd=1)
        lbl.pack()

    def hide(self, _=None):
        if self.tw:
            self.tw.destroy()
            self.tw = None


# ─── STYLED WIDGETS ──────────────────────────────────────────────────────────
def make_button(parent, text, command, color=None, width=None, icon=""):
    bg = color or C["teal"]
    fg = C["bg"] if bg in (C["teal"], C["green"], C["amber"]) else C["text"]
    full_text = f"{icon} {text}".strip() if icon else text
    btn = tk.Button(
        parent, text=full_text, command=command,
        bg=bg, fg=fg, font=FONT_BOLD,
        relief="flat", cursor="hand2",
        padx=12, pady=6, bd=0,
        activebackground=_lighten(bg),
        activeforeground=fg,
        **({"width": width} if width else {})
    )
    btn.bind("<Enter>", lambda e: btn.config(bg=_lighten(bg)))
    btn.bind("<Leave>", lambda e: btn.config(bg=bg))
    return btn

def _lighten(hex_color: str) -> str:
    try:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        r = min(255, r + 30)
        g = min(255, g + 30)
        b = min(255, b + 30)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color

def make_entry(parent, textvariable=None, width=10, placeholder=""):
    e = tk.Entry(
        parent,
        textvariable=textvariable,
        width=width,
        bg=C["raised"],
        fg=C["text"],
        insertbackground=C["teal"],
        relief="flat",
        font=FONT_LABEL,
        bd=0,
        highlightthickness=1,
        highlightbackground=C["border"],
        highlightcolor=C["teal"],
    )
    return e

def make_label(parent, text, font=None, fg=None, **kw):
    return tk.Label(
        parent, text=text,
        bg=kw.pop("bg", C["surface"]),
        fg=fg or C["text"],
        font=font or FONT_LABEL,
        **kw
    )

def make_frame(parent, bg=None, **kw):
    return tk.Frame(parent, bg=bg or C["surface"], **kw)

def make_section(parent, title, bg=None):
    bg = bg or C["surface"]
    outer = make_frame(parent, bg=bg)
    hdr = make_frame(outer, bg=bg)
    hdr.pack(fill="x", padx=8, pady=(10, 4))
    make_label(hdr, title, font=("Segoe UI", 9, "bold"),
               fg=C["teal"], bg=bg).pack(side="left")
    sep = tk.Frame(outer, bg=C["border"], height=1)
    sep.pack(fill="x", padx=8)
    return outer


# ─── STEP DIALOG ─────────────────────────────────────────────────────────────
class StepDialog(tk.Toplevel):
    """Modal dialog for adding / editing a step."""

    STEP_TYPES = ["tap", "swipe", "wait", "keyevent", "launch_app", "setprop"]

    KEYEVENT_MAP = {
        "HOME": "3", "BACK": "4", "VOLUME UP": "24", "VOLUME DOWN": "25",
        "POWER": "26", "MENU": "82", "ENTER": "66", "MEDIA PLAY/PAUSE": "85",
        "MEDIA NEXT": "87", "MEDIA PREV": "88", "MUTE": "91",
    }

    def __init__(self, parent, existing_step=None, title="Add Step"):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.grab_set()

        self._type_var = tk.StringVar(value=existing_step["action"] if existing_step else "tap")
        self._label_var = tk.StringVar(value=existing_step.get("label", "") if existing_step else "")
        self._existing = existing_step or {}
        self._fields = {}

        self._build()
        self._on_type_change()
        if existing_step:
            self._populate(existing_step)

        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        px = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{px}+{py}")

    def _build(self):
        pad = dict(padx=16, pady=6)

        hdr = make_frame(self, bg=C["raised"])
        hdr.pack(fill="x")
        make_label(hdr, "  Configure Step", font=FONT_TITLE,
                   fg=C["teal"], bg=C["raised"]).pack(side="left", pady=12)

        body = make_frame(self, bg=C["bg"])
        body.pack(fill="both", padx=16, pady=8)

        # Type selector
        row = make_frame(body, bg=C["bg"])
        row.pack(fill="x", pady=4)
        make_label(row, "Step Type", bg=C["bg"], fg=C["muted"]).pack(side="left", padx=(0, 10))
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Dark.TCombobox",
                        fieldbackground=C["raised"],
                        background=C["raised"],
                        foreground=C["text"],
                        selectbackground=C["teal"],
                        selectforeground=C["bg"],
                        arrowcolor=C["teal"])
        self._type_combo = ttk.Combobox(
            row, textvariable=self._type_var,
            values=self.STEP_TYPES, state="readonly",
            style="Dark.TCombobox", width=14
        )
        self._type_combo.pack(side="left")
        self._type_combo.bind("<<ComboboxSelected>>", lambda _: self._on_type_change())

        # Dynamic fields container
        self._fields_frame = make_frame(body, bg=C["bg"])
        self._fields_frame.pack(fill="x")

        # Label
        lrow = make_frame(body, bg=C["bg"])
        lrow.pack(fill="x", pady=4)
        make_label(lrow, "Label (optional)", bg=C["bg"], fg=C["muted"]).pack(side="left", padx=(0, 10))
        make_entry(lrow, textvariable=self._label_var, width=28).pack(side="left")

        # Screenshot checkbox
        self._screenshot_var = tk.BooleanVar(value=self._existing.get("screenshot", False))
        sc_row = make_frame(body, bg=C["bg"])
        sc_row.pack(fill="x", pady=4)
        tk.Checkbutton(
            sc_row, text="Capture screenshot after this step",
            variable=self._screenshot_var,
            bg=C["bg"], fg=C["muted"], selectcolor=C["raised"],
            activebackground=C["bg"], activeforeground=C["teal"],
            font=FONT_SMALL
        ).pack(side="left")

        # Buttons
        btn_row = make_frame(self, bg=C["bg"])
        btn_row.pack(fill="x", padx=16, pady=(4, 14))
        make_button(btn_row, "Cancel", self.destroy,
                    color=C["raised"]).pack(side="right", padx=(6, 0))
        make_button(btn_row, "Save Step", self._save,
                    color=C["teal"]).pack(side="right")

    def _field_row(self, parent, label, var_name, default="", width=10):
        row = make_frame(parent, bg=C["bg"])
        row.pack(fill="x", pady=3)
        make_label(row, label, bg=C["bg"], fg=C["muted"],
                   width=14, anchor="w").pack(side="left")
        var = tk.StringVar(value=str(default))
        entry = make_entry(row, textvariable=var, width=width)
        entry.pack(side="left")
        self._fields[var_name] = var
        return var

    def _on_type_change(self):
        for w in self._fields_frame.winfo_children():
            w.destroy()
        self._fields.clear()
        t = self._type_var.get()

        if t == "tap":
            self._field_row(self._fields_frame, "X", "x", 540)
            self._field_row(self._fields_frame, "Y", "y", 960)
        elif t == "swipe":
            self._field_row(self._fields_frame, "Start X", "x1", 100)
            self._field_row(self._fields_frame, "Start Y", "y1", 500)
            self._field_row(self._fields_frame, "End X", "x2", 900)
            self._field_row(self._fields_frame, "End Y", "y2", 500)
            self._field_row(self._fields_frame, "Duration ms", "duration", 300)
        elif t == "wait":
            self._field_row(self._fields_frame, "Duration ms", "ms", 1000)
        elif t == "keyevent":
            row = make_frame(self._fields_frame, bg=C["bg"])
            row.pack(fill="x", pady=3)
            make_label(row, "Key", bg=C["bg"], fg=C["muted"],
                       width=14, anchor="w").pack(side="left")
            key_var = tk.StringVar(value="HOME")
            self._fields["keyevent"] = key_var
            combo = ttk.Combobox(row, textvariable=key_var,
                                 values=list(self.KEYEVENT_MAP.keys()),
                                 state="readonly", width=16)
            combo.pack(side="left")
            make_label(row, "  or custom code:", bg=C["bg"],
                       fg=C["muted"]).pack(side="left")
            cvar = tk.StringVar()
            self._fields["keyevent_custom"] = cvar
            make_entry(row, textvariable=cvar, width=6).pack(side="left", padx=(4, 0))
        elif t == "launch_app":
            self._field_row(self._fields_frame, "Package", "package",
                            "com.android.car.media", width=32)
            self._field_row(self._fields_frame, "Activity", "activity",
                            "(leave blank for launcher)", width=32)
        elif t == "setprop":
            self._field_row(self._fields_frame, "Property Key", "prop_key",
                            "audio.source", width=24)
            self._field_row(self._fields_frame, "Value", "prop_value",
                            "BT_A2DP", width=16)

    def _populate(self, step):
        t = step["action"]
        if t == "tap":
            self._fields.get("x", tk.StringVar()).set(str(step.get("x", 0)))
            self._fields.get("y", tk.StringVar()).set(str(step.get("y", 0)))
        elif t == "swipe":
            for k in ("x1", "y1", "x2", "y2", "duration"):
                if k in self._fields:
                    self._fields[k].set(str(step.get(k, 0)))
        elif t == "wait":
            if "ms" in self._fields:
                self._fields["ms"].set(str(step.get("ms", 1000)))
        elif t == "keyevent":
            if "keyevent" in self._fields:
                self._fields["keyevent"].set(step.get("keyevent", "HOME"))
        elif t == "launch_app":
            if "package" in self._fields:
                self._fields["package"].set(step.get("package", ""))
            if "activity" in self._fields:
                self._fields["activity"].set(step.get("activity", ""))
        elif t == "setprop":
            if "prop_key" in self._fields:
                self._fields["prop_key"].set(step.get("prop_key", ""))
            if "prop_value" in self._fields:
                self._fields["prop_value"].set(step.get("prop_value", ""))

    def _save(self):
        t = self._type_var.get()
        step = {"action": t, "label": self._label_var.get().strip(),
                "screenshot": self._screenshot_var.get()}
        try:
            if t == "tap":
                step["x"] = int(self._fields["x"].get())
                step["y"] = int(self._fields["y"].get())
            elif t == "swipe":
                step["x1"] = int(self._fields["x1"].get())
                step["y1"] = int(self._fields["y1"].get())
                step["x2"] = int(self._fields["x2"].get())
                step["y2"] = int(self._fields["y2"].get())
                step["duration"] = int(self._fields["duration"].get())
            elif t == "wait":
                step["ms"] = max(0, int(self._fields["ms"].get()))
            elif t == "keyevent":
                custom = self._fields.get("keyevent_custom", tk.StringVar()).get().strip()
                if custom:
                    step["keyevent"] = custom
                else:
                    key_name = self._fields["keyevent"].get()
                    step["keyevent"] = self.KEYEVENT_MAP.get(key_name, "3")
                    step["key_name"] = key_name
            elif t == "launch_app":
                step["package"] = self._fields["package"].get().strip()
                act = self._fields["activity"].get().strip()
                if act and "(leave" not in act:
                    step["activity"] = act
            elif t == "setprop":
                step["prop_key"] = self._fields["prop_key"].get().strip()
                step["prop_value"] = self._fields["prop_value"].get().strip()
                if not step["prop_key"]:
                    raise ValueError("Property key required")
        except (ValueError, KeyError) as e:
            messagebox.showerror("Invalid Input", str(e), parent=self)
            return

        if not step["label"]:
            step["label"] = self._auto_label(step)

        self.result = step
        self.destroy()

    @staticmethod
    def _auto_label(step) -> str:
        t = step["action"]
        if t == "tap":
            return f"Tap ({step['x']}, {step['y']})"
        if t == "swipe":
            return f"Swipe → ({step['x2']}, {step['y2']})"
        if t == "wait":
            return f"Wait {step['ms']}ms"
        if t == "keyevent":
            return f"Key: {step.get('key_name', step.get('keyevent'))}"
        if t == "launch_app":
            return f"Launch {step['package'].split('.')[-1]}"
        if t == "setprop":
            return f"setprop {step['prop_key']}={step['prop_value']}"
        return t


# ─── SEGMENT PROGRESS BAR ────────────────────────────────────────────────────
class SegmentBar(tk.Canvas):
    """Fuel-gauge style segmented progress bar — signature UI element."""

    def __init__(self, parent, total=100, **kw):
        kw.setdefault("bg", C["surface"])
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("height", 28)
        super().__init__(parent, **kw)
        self._total = max(1, total)
        self._segments: list[str] = []   # "pending","pass","fail","running"
        self.bind("<Configure>", lambda _: self._redraw())

    def reset(self, total: int):
        self._total = max(1, total)
        self._segments = ["pending"] * self._total
        self._redraw()

    def set_segment(self, idx: int, state: str):
        if 0 <= idx < len(self._segments):
            self._segments[idx] = state
            self._redraw()

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2 or h < 2 or not self._segments:
            return
        n = len(self._segments)
        gap = 2
        seg_w = max(1, (w - (n - 1) * gap) / n)
        colors = {
            "pending": C["border"],
            "pass":    C["green"],
            "fail":    C["red"],
            "running": C["amber"],
        }
        for i, state in enumerate(self._segments):
            x0 = i * (seg_w + gap)
            x1 = x0 + seg_w
            r = 3
            color = colors.get(state, C["border"])
            self._rounded_rect(x0, 2, x1, h - 2, r, color)

    def _rounded_rect(self, x0, y0, x1, y1, r, fill):
        self.create_arc(x0, y0, x0 + 2*r, y0 + 2*r, start=90,  extent=90,  fill=fill, outline=fill)
        self.create_arc(x1 - 2*r, y0, x1, y0 + 2*r, start=0,   extent=90,  fill=fill, outline=fill)
        self.create_arc(x0, y1 - 2*r, x0 + 2*r, y1, start=180, extent=90,  fill=fill, outline=fill)
        self.create_arc(x1 - 2*r, y1 - 2*r, x1, y1, start=270, extent=90,  fill=fill, outline=fill)
        self.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline=fill)
        self.create_rectangle(x0, y0 + r, x1, y1 - r, fill=fill, outline=fill)


# ─── MAIN APPLICATION ────────────────────────────────────────────────────────
class ReproTool(tk.Tk):

    SESSION_DIR = Path("repro_sessions")
    SCREENSHOT_DIR = Path("repro_screenshots")

    def __init__(self):
        super().__init__()
        self.title("AOSP IVI Reproduction Tool")
        self.configure(bg=C["bg"])
        self.minsize(1100, 720)
        self.geometry("1280x800")

        # State
        self._steps: list[dict] = []
        self._running = False
        self._paused = False
        self._stop_flag = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._log_queue: queue.Queue = queue.Queue()
        self._result_queue: queue.Queue = queue.Queue()
        self._run_thread: threading.Thread | None = None
        self._device_serial = "—"
        self._device_connected = False
        self._session_file: Path | None = None

        self.SESSION_DIR.mkdir(exist_ok=True)
        self.SCREENSHOT_DIR.mkdir(exist_ok=True)

        self._build_ui()
        self._start_device_monitor()
        self._process_queues()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI CONSTRUCTION ──────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        body = make_frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True)
        self._build_left_panel(body)
        self._build_right_panel(body)

    def _build_header(self):
        hdr = tk.Frame(self, bg=C["raised"], height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        # Logo area
        logo_frame = make_frame(hdr, bg=C["raised"])
        logo_frame.pack(side="left", padx=14)
        dot = tk.Label(logo_frame, text="●", fg=C["teal"], bg=C["raised"],
                       font=("Segoe UI", 16))
        dot.pack(side="left", padx=(0, 8))
        make_label(logo_frame, "AOSP IVI  Repro Tool",
                   font=("Segoe UI", 14, "bold"),
                   fg=C["text"], bg=C["raised"]).pack(side="left")
        make_label(logo_frame, "  v2.0",
                   font=FONT_SMALL, fg=C["muted"], bg=C["raised"]).pack(side="left")

        # Device status
        dev_frame = make_frame(hdr, bg=C["raised"])
        dev_frame.pack(side="right", padx=16)
        self._dev_dot = tk.Label(dev_frame, text="●", fg=C["red"],
                                  bg=C["raised"], font=("Segoe UI", 12))
        self._dev_dot.pack(side="left", padx=(0, 6))
        self._dev_label = make_label(dev_frame, "No device",
                                      fg=C["muted"], bg=C["raised"],
                                      font=FONT_SMALL)
        self._dev_label.pack(side="left")

        # Menu bar
        make_button(hdr, "New", self._new_session,
                    color=C["raised"], icon="📄").pack(side="right", padx=4, pady=8)
        make_button(hdr, "Open", self._load_session,
                    color=C["raised"], icon="📂").pack(side="right", padx=4, pady=8)
        make_button(hdr, "Save", self._save_session,
                    color=C["raised"], icon="💾").pack(side="right", padx=4, pady=8)

    def _build_left_panel(self, parent):
        left = make_frame(parent, bg=C["surface"])
        left.pack(side="left", fill="y", padx=(8, 4), pady=8)
        left.pack_propagate(False)
        left.configure(width=280)

        # Device info card
        dev_sec = make_section(left, "Device Info")
        dev_sec.pack(fill="x", pady=(0, 6))
        self._dev_info_frame = make_frame(dev_sec, bg=C["surface"])
        self._dev_info_frame.pack(fill="x", padx=10, pady=6)
        self._dev_rows = {}
        for key in ("Serial", "Screen", "Android", "Status"):
            row = make_frame(self._dev_info_frame, bg=C["surface"])
            row.pack(fill="x", pady=2)
            make_label(row, key, fg=C["muted"], bg=C["surface"],
                       font=FONT_SMALL, width=9, anchor="w").pack(side="left")
            val_lbl = make_label(row, "—", fg=C["text"], bg=C["surface"],
                                  font=FONT_SMALL)
            val_lbl.pack(side="left")
            self._dev_rows[key] = val_lbl
        make_button(dev_sec, "Refresh Device", self._refresh_device,
                    color=C["raised"], icon="🔄").pack(padx=10, pady=6, fill="x")

        # Quick actions
        qa_sec = make_section(left, "Quick Actions")
        qa_sec.pack(fill="x", pady=6)
        actions = [
            ("Screenshot Now", "📸", self._take_screenshot),
            ("Clear Logcat", "🗑", lambda: ADB.clear_logcat()),
            ("Reboot Device", "🔄", self._reboot_device),
            ("Get Screen Size", "📐", self._get_screen_size),
        ]
        for label, icon, cmd in actions:
            make_button(qa_sec, label, cmd, color=C["raised"],
                        icon=icon).pack(fill="x", padx=10, pady=3)

        # Session history
        hist_sec = make_section(left, "Session Files")
        hist_sec.pack(fill="both", expand=True, pady=6)

        hist_inner = make_frame(hist_sec, bg=C["surface"])
        hist_inner.pack(fill="both", expand=True, padx=10, pady=6)

        self._hist_listbox = tk.Listbox(
            hist_inner,
            bg=C["raised"], fg=C["text"], selectbackground=C["teal"],
            selectforeground=C["bg"], relief="flat", borderwidth=0,
            font=FONT_MONO_S, activestyle="none",
            highlightthickness=0
        )
        hist_scroll = ttk.Scrollbar(hist_inner, orient="vertical",
                                     command=self._hist_listbox.yview)
        self._hist_listbox.configure(yscrollcommand=hist_scroll.set)
        hist_scroll.pack(side="right", fill="y")
        self._hist_listbox.pack(fill="both", expand=True)
        self._hist_listbox.bind("<Double-Button-1>", self._load_from_history)
        self._refresh_history()

    def _build_right_panel(self, parent):
        right = make_frame(parent, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)

        # ── Steps section ──
        steps_sec = make_section(right, "Test Steps")
        steps_sec.pack(fill="x", pady=(0, 6))

        # Toolbar
        tb = make_frame(steps_sec, bg=C["surface"])
        tb.pack(fill="x", padx=10, pady=6)

        step_btns = [
            ("+ Tap",   C["teal"],   lambda: self._add_step("tap")),
            ("+ Swipe", C["blue"],   lambda: self._add_step("swipe")),
            ("+ Wait",  C["purple"], lambda: self._add_step("wait")),
            ("+ Key",   C["raised"], lambda: self._add_step("keyevent")),
            ("+ App",   C["raised"], lambda: self._add_step("launch_app")),
            ("+ Prop",  C["raised"], lambda: self._add_step("setprop")),
        ]
        for text, color, cmd in step_btns:
            b = make_button(tb, text, cmd, color=color)
            b.pack(side="left", padx=2)

        sep = tk.Frame(tb, bg=C["border"], width=1)
        sep.pack(side="left", fill="y", padx=8, pady=2)

        make_button(tb, "Edit",      self._edit_step,   color=C["raised"], icon="✏").pack(side="left", padx=2)
        make_button(tb, "Duplicate", self._dup_step,    color=C["raised"], icon="⧉").pack(side="left", padx=2)
        make_button(tb, "↑",         self._move_up,     color=C["raised"]).pack(side="left", padx=2)
        make_button(tb, "↓",         self._move_down,   color=C["raised"]).pack(side="left", padx=2)
        make_button(tb, "Delete",    self._delete_step, color=C["red"],    icon="✕").pack(side="left", padx=2)
        make_button(tb, "Clear All", self._clear_steps, color=C["raised"]).pack(side="right", padx=2)

        # Steps list
        list_frame = make_frame(steps_sec, bg=C["surface"])
        list_frame.pack(fill="x", padx=10, pady=(0, 8))

        self._steps_canvas = tk.Canvas(list_frame, bg=C["surface"],
                                        highlightthickness=0, height=200)
        s_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                  command=self._steps_canvas.yview)
        self._steps_canvas.configure(yscrollcommand=s_scroll.set)
        s_scroll.pack(side="right", fill="y")
        self._steps_canvas.pack(fill="both", expand=True)

        self._steps_inner = make_frame(self._steps_canvas, bg=C["surface"])
        self._steps_canvas_win = self._steps_canvas.create_window(
            (0, 0), window=self._steps_inner, anchor="nw"
        )
        self._steps_inner.bind("<Configure>",
            lambda e: self._steps_canvas.configure(
                scrollregion=self._steps_canvas.bbox("all")))
        self._steps_canvas.bind("<Configure>",
            lambda e: self._steps_canvas.itemconfig(
                self._steps_canvas_win, width=e.width))
        self._steps_canvas.bind("<MouseWheel>",
            lambda e: self._steps_canvas.yview_scroll(-1*(e.delta//120), "units"))

        self._selected_step_idx = -1
        self._render_steps()

        # ── Execution section ──
        exec_sec = make_section(right, "Execution")
        exec_sec.pack(fill="both", expand=True)

        # Config row
        cfg = make_frame(exec_sec, bg=C["surface"])
        cfg.pack(fill="x", padx=10, pady=8)

        # Iterations
        make_label(cfg, "Iterations", fg=C["muted"]).pack(side="left")
        self._iter_var = tk.StringVar(value="100")
        iter_e = make_entry(cfg, textvariable=self._iter_var, width=6)
        iter_e.pack(side="left", padx=(6, 20))
        Tooltip(iter_e, "Number of times to replay the steps")

        # Step delay
        make_label(cfg, "Step Delay ms", fg=C["muted"]).pack(side="left")
        self._delay_var = tk.StringVar(value="300")
        make_entry(cfg, textvariable=self._delay_var, width=6).pack(side="left", padx=(6, 20))

        # Stop on crash
        self._stop_on_crash = tk.BooleanVar(value=True)
        tk.Checkbutton(cfg, text="Stop on crash",
                       variable=self._stop_on_crash,
                       bg=C["surface"], fg=C["muted"],
                       selectcolor=C["raised"],
                       activebackground=C["surface"],
                       activeforeground=C["teal"],
                       font=FONT_SMALL).pack(side="left", padx=(0, 16))

        # Screenshot diff
        self._diff_check = tk.BooleanVar(value=False)
        tk.Checkbutton(cfg, text="Screenshot diff per iteration",
                       variable=self._diff_check,
                       bg=C["surface"], fg=C["muted"],
                       selectcolor=C["raised"],
                       activebackground=C["surface"],
                       activeforeground=C["teal"],
                       font=FONT_SMALL).pack(side="left")

        # Run control buttons
        ctrl = make_frame(exec_sec, bg=C["surface"])
        ctrl.pack(fill="x", padx=10, pady=(0, 8))

        self._btn_run = make_button(ctrl, "RUN", self._start_run,
                                     color=C["green"], icon="▶")
        self._btn_run.pack(side="left", padx=(0, 8))

        self._btn_pause = make_button(ctrl, "PAUSE", self._toggle_pause,
                                       color=C["amber"], icon="⏸")
        self._btn_pause.pack(side="left", padx=(0, 8))
        self._btn_pause.config(state="disabled")

        self._btn_stop = make_button(ctrl, "STOP", self._stop_run,
                                      color=C["red"], icon="⏹")
        self._btn_stop.pack(side="left")
        self._btn_stop.config(state="disabled")

        # Stats row
        self._stats_frame = make_frame(exec_sec, bg=C["surface"])
        self._stats_frame.pack(fill="x", padx=10)
        self._stat_labels = {}
        for key, color in [("Iter", C["text"]), ("Pass", C["green"]),
                            ("Fail", C["red"]), ("Crash", C["amber"]),
                            ("Elapsed", C["muted"])]:
            col = make_frame(self._stats_frame, bg=C["raised"])
            col.pack(side="left", padx=4, pady=4, ipadx=10, ipady=6)
            make_label(col, key, fg=C["muted"], bg=C["raised"],
                       font=FONT_SMALL).pack()
            val = make_label(col, "—", fg=color, bg=C["raised"],
                              font=("Segoe UI", 13, "bold"))
            val.pack()
            self._stat_labels[key] = val

        make_button(self._stats_frame, "Export Report", self._export_report,
                    color=C["raised"], icon="📊").pack(side="right", padx=8)

        # Segment bar
        bar_frame = make_frame(exec_sec, bg=C["surface"])
        bar_frame.pack(fill="x", padx=10, pady=(6, 4))
        self._seg_bar = SegmentBar(bar_frame, total=100,
                                    bg=C["surface"])
        self._seg_bar.pack(fill="x")

        # Live log
        log_frame = make_frame(exec_sec, bg=C["surface"])
        log_frame.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        log_hdr = make_frame(log_frame, bg=C["surface"])
        log_hdr.pack(fill="x")
        make_label(log_hdr, "Live Log", fg=C["teal"], bg=C["surface"],
                   font=("Segoe UI", 9, "bold")).pack(side="left")
        make_button(log_hdr, "Clear Log", self._clear_log,
                    color=C["raised"], icon="🗑").pack(side="right", pady=2)

        self._log_text = tk.Text(
            log_frame,
            bg=C["raised"], fg=C["text"],
            font=FONT_MONO, relief="flat",
            state="disabled", wrap="word",
            height=8,
            selectbackground=C["teal"],
            highlightthickness=0,
        )
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical",
                                    command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True)

        # Log colour tags
        self._log_text.tag_configure("pass",   foreground=C["green"])
        self._log_text.tag_configure("fail",   foreground=C["red"])
        self._log_text.tag_configure("warn",   foreground=C["amber"])
        self._log_text.tag_configure("info",   foreground=C["teal"])
        self._log_text.tag_configure("muted",  foreground=C["muted"])
        self._log_text.tag_configure("crash",  foreground=C["red"],
                                      background="#2D1515")

    # ── STEP RENDERING ───────────────────────────────────────────────────────

    def _render_steps(self):
        for w in self._steps_inner.winfo_children():
            w.destroy()

        if not self._steps:
            make_label(self._steps_inner,
                       "No steps yet. Click + Tap / + Swipe to add steps.",
                       fg=C["subtle"], bg=C["surface"],
                       font=FONT_SMALL).pack(pady=20)
            return

        for i, step in enumerate(self._steps):
            self._render_step_row(i, step)

    def _render_step_row(self, idx: int, step: dict):
        is_sel = idx == self._selected_step_idx
        bg = C["teal_dim"] if is_sel else C["raised"]
        fg_main = C["bg"] if is_sel else C["text"]

        row = tk.Frame(self._steps_inner, bg=bg, cursor="hand2",
                        relief="flat", bd=0)
        row.pack(fill="x", pady=2, padx=0)

        # Index badge
        badge = tk.Label(row, text=f" {idx + 1:02d} ", bg=C["border"],
                          fg=C["muted"], font=FONT_MONO_S, width=4)
        badge.pack(side="left", ipadx=2, ipady=6)

        # Icon
        icon_lbl = tk.Label(row, text=STEP_ICONS.get(step["action"], "•"),
                             bg=bg, fg=fg_main, font=("Segoe UI", 13))
        icon_lbl.pack(side="left", padx=(8, 4))

        # Label
        tk.Label(row, text=step.get("label", step["action"]),
                  bg=bg, fg=fg_main, font=FONT_BOLD,
                  anchor="w").pack(side="left", padx=4)

        # Detail
        detail = self._step_detail(step)
        if detail:
            tk.Label(row, text=detail, bg=bg, fg=C["muted"] if not is_sel else C["bg"],
                      font=FONT_SMALL, anchor="w").pack(side="left", padx=4)

        # Screenshot indicator
        if step.get("screenshot"):
            tk.Label(row, text="📸", bg=bg, font=FONT_SMALL).pack(side="right", padx=6)

        # Bind click to select
        def select(e, i=idx):
            self._selected_step_idx = i
            self._render_steps()

        for w in (row, icon_lbl):
            w.bind("<Button-1>", select)
            w.bind("<Double-Button-1>", lambda e, i=idx: self._edit_step(i))

    @staticmethod
    def _step_detail(step: dict) -> str:
        t = step["action"]
        if t == "tap":
            return f"({step.get('x')}, {step.get('y')})"
        if t == "swipe":
            return (f"({step.get('x1')},{step.get('y1')}) → "
                    f"({step.get('x2')},{step.get('y2')}) {step.get('duration')}ms")
        if t == "wait":
            return f"{step.get('ms')}ms"
        if t == "keyevent":
            return step.get("key_name", step.get("keyevent", ""))
        if t == "launch_app":
            return step.get("package", "")
        if t == "setprop":
            return f"{step.get('prop_key')}={step.get('prop_value')}"
        return ""

    # ── STEP MANAGEMENT ──────────────────────────────────────────────────────

    def _add_step(self, step_type: str):
        dlg = StepDialog(self, title=f"Add {step_type.title()} Step")
        dlg.wait_window()
        if dlg.result:
            dlg.result["action"] = step_type
            self._steps.append(dlg.result)
            self._selected_step_idx = len(self._steps) - 1
            self._render_steps()

    def _edit_step(self, idx=None):
        i = idx if idx is not None else self._selected_step_idx
        if i < 0 or i >= len(self._steps):
            self._log("Select a step to edit.", "warn")
            return
        dlg = StepDialog(self, existing_step=self._steps[i], title="Edit Step")
        dlg.wait_window()
        if dlg.result:
            self._steps[i] = dlg.result
            self._render_steps()

    def _delete_step(self):
        i = self._selected_step_idx
        if i < 0 or i >= len(self._steps):
            return
        self._steps.pop(i)
        self._selected_step_idx = max(0, i - 1) if self._steps else -1
        self._render_steps()

    def _dup_step(self):
        i = self._selected_step_idx
        if i < 0 or i >= len(self._steps):
            return
        import copy
        self._steps.insert(i + 1, copy.deepcopy(self._steps[i]))
        self._selected_step_idx = i + 1
        self._render_steps()

    def _move_up(self):
        i = self._selected_step_idx
        if i <= 0:
            return
        self._steps[i], self._steps[i - 1] = self._steps[i - 1], self._steps[i]
        self._selected_step_idx = i - 1
        self._render_steps()

    def _move_down(self):
        i = self._selected_step_idx
        if i < 0 or i >= len(self._steps) - 1:
            return
        self._steps[i], self._steps[i + 1] = self._steps[i + 1], self._steps[i]
        self._selected_step_idx = i + 1
        self._render_steps()

    def _clear_steps(self):
        if self._steps and messagebox.askyesno(
                "Clear Steps", "Remove all steps?", parent=self):
            self._steps.clear()
            self._selected_step_idx = -1
            self._render_steps()

    # ── EXECUTION ────────────────────────────────────────────────────────────

    def _start_run(self):
        if not self._steps:
            messagebox.showwarning("No Steps", "Add at least one step first.", parent=self)
            return
        if not self._device_connected:
            messagebox.showwarning("No Device", "Connect an ADB device first.", parent=self)
            return
        try:
            iterations = int(self._iter_var.get())
            delay_ms = int(self._delay_var.get())
            if iterations < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid", "Iterations and delay must be positive integers.", parent=self)
            return

        self._running = True
        self._paused = False
        self._stop_flag.clear()
        self._pause_event.set()

        self._btn_run.config(state="disabled")
        self._btn_pause.config(state="normal")
        self._btn_stop.config(state="normal")

        self._seg_bar.reset(iterations)
        for key in self._stat_labels:
            self._stat_labels[key].config(text="—")

        ADB.clear_logcat()
        self._log(f"▶ Starting {iterations} iterations × {len(self._steps)} steps", "info")

        self._run_thread = threading.Thread(
            target=self._run_loop,
            args=(iterations, delay_ms),
            daemon=True
        )
        self._run_thread.start()

    def _run_loop(self, iterations: int, delay_ms: int):
        results = []
        pass_count = 0
        fail_count = 0
        crash_count = 0
        start_time = time.time()
        ref_screenshot = None

        for i in range(iterations):
            # Check stop
            if self._stop_flag.is_set():
                self._log_queue.put(("STOPPED by user.", "warn"))
                break

            # Check pause
            self._log_queue.put((f"── Iteration {i + 1}/{iterations} ──", "muted"))
            self._result_queue.put(("seg", i, "running"))

            step_ok = True
            for step in self._steps:
                # Wait if paused
                self._pause_event.wait()

                if self._stop_flag.is_set():
                    break

                ok = self._execute_step(step, i + 1, delay_ms)
                if not ok:
                    step_ok = False

                # Per-step screenshot
                if step.get("screenshot"):
                    path = self.SCREENSHOT_DIR / f"iter{i+1:04d}_{step.get('label','step').replace(' ','_')}.png"
                    ADB.screenshot(str(path))
                    self._log_queue.put((f"  📸 {path.name}", "muted"))

            if self._stop_flag.is_set():
                break

            # Crash detection
            logcat = ADB.logcat_snapshot(100)
            crashed, crash_msg = detect_crash(logcat)

            # Screenshot diff (optional)
            diff_score = None
            if self._diff_check.get() and PIL_AVAILABLE:
                ss_path = self.SCREENSHOT_DIR / f"iter{i+1:04d}_end.png"
                if ADB.screenshot(str(ss_path)):
                    if ref_screenshot is None:
                        ref_screenshot = str(ss_path)
                    else:
                        diff_score = self._compare_screenshots(ref_screenshot, str(ss_path))

            if crashed:
                crash_count += 1
                fail_count += 1
                log_path = self.SCREENSHOT_DIR / f"crash_iter{i+1:04d}.log"
                log_path.write_text(logcat)
                self._log_queue.put((
                    f"  ❌ CRASH: {crash_msg[:100]}  → {log_path.name}", "crash"))
                self._result_queue.put(("seg", i, "fail"))
                results.append({"iteration": i + 1, "status": "FAIL", "crash": crash_msg})
                ADB.clear_logcat()
                if self._stop_on_crash.get():
                    self._log_queue.put(("⛔ Stopping on crash (option enabled).", "warn"))
                    self._stop_flag.set()
                    break
            elif not step_ok:
                fail_count += 1
                self._log_queue.put((f"  ⚠ Iter {i+1}: step execution error", "warn"))
                self._result_queue.put(("seg", i, "fail"))
                results.append({"iteration": i + 1, "status": "FAIL", "crash": ""})
            else:
                pass_count += 1
                msg = f"  ✅ PASS"
                if diff_score is not None:
                    msg += f"  (diff {diff_score:.1f}%)"
                self._log_queue.put((msg, "pass"))
                self._result_queue.put(("seg", i, "pass"))
                results.append({"iteration": i + 1, "status": "PASS", "crash": ""})
                ADB.clear_logcat()

            elapsed = time.time() - start_time
            self._result_queue.put(("stats",
                f"{i+1}/{iterations}", str(pass_count), str(fail_count),
                str(crash_count), self._fmt_time(elapsed)))

        # Final summary
        elapsed = time.time() - start_time
        total = len(results)
        self._log_queue.put(("─" * 50, "muted"))
        self._log_queue.put((
            f"DONE  {total} total  |  ✅ {pass_count} pass  |  "
            f"❌ {fail_count} fail  |  💥 {crash_count} crash  |  "
            f"⏱ {self._fmt_time(elapsed)}", "info"))

        # Save results JSON
        session_name = self._session_file.stem if self._session_file else "session"
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = self.SESSION_DIR / f"results_{session_name}_{ts}.json"
        try:
            out_path.write_text(json.dumps({
                "session": session_name,
                "timestamp": ts,
                "iterations": total,
                "pass": pass_count,
                "fail": fail_count,
                "crash": crash_count,
                "elapsed_s": round(elapsed, 1),
                "results": results
            }, indent=2))
            self._log_queue.put((f"📁 Results: {out_path.name}", "muted"))
        except Exception as e:
            self._log_queue.put((f"Could not save results: {e}", "warn"))

        self._result_queue.put(("done",))

    def _execute_step(self, step: dict, iter_num: int, delay_ms: int) -> bool:
        t = step["action"]
        label = step.get("label", t)
        try:
            if t == "tap":
                ok = ADB.tap(step["x"], step["y"])
            elif t == "swipe":
                ok = ADB.swipe(step["x1"], step["y1"],
                               step["x2"], step["y2"], step["duration"])
            elif t == "wait":
                time.sleep(step["ms"] / 1000)
                ok = True
            elif t == "keyevent":
                ok = ADB.keyevent(step["keyevent"])
            elif t == "launch_app":
                ok = ADB.launch_app(step["package"], step.get("activity", ""))
            elif t == "setprop":
                ok = ADB.setprop(step["prop_key"], step["prop_value"])
            else:
                ok = False

            if not ok:
                self._log_queue.put((f"  ⚠ Step failed: {label}", "warn"))

            if delay_ms > 0 and t != "wait":
                time.sleep(delay_ms / 1000)

            return ok
        except Exception as e:
            self._log_queue.put((f"  ✕ Exception in step [{label}]: {e}", "fail"))
            return False

    def _toggle_pause(self):
        if not self._running:
            return
        if self._paused:
            self._paused = False
            self._pause_event.set()
            self._btn_pause.config(text="⏸ PAUSE", bg=C["amber"])
            self._log("▶ Resumed.", "info")
        else:
            self._paused = True
            self._pause_event.clear()
            self._btn_pause.config(text="▶ RESUME", bg=C["green"])
            self._log("⏸ Paused.", "warn")

    def _stop_run(self):
        self._stop_flag.set()
        self._pause_event.set()  # unblock if paused
        self._log("⏹ Stop requested…", "warn")

    def _on_run_done(self):
        self._running = False
        self._paused = False
        self._btn_run.config(state="normal")
        self._btn_pause.config(state="disabled", text="⏸ PAUSE", bg=C["amber"])
        self._btn_stop.config(state="disabled")

    # ── QUEUE PROCESSORS ─────────────────────────────────────────────────────

    def _process_queues(self):
        # Process log queue
        try:
            while True:
                item = self._log_queue.get_nowait()
                msg, tag = item if len(item) == 2 else (item[0], "info")
                self._log(msg, tag)
        except queue.Empty:
            pass

        # Process result queue
        try:
            while True:
                item = self._result_queue.get_nowait()
                if item[0] == "seg":
                    _, idx, state = item
                    self._seg_bar.set_segment(idx, state)
                elif item[0] == "stats":
                    _, it, ps, fl, cr, el = item
                    self._stat_labels["Iter"].config(text=it)
                    self._stat_labels["Pass"].config(text=ps)
                    self._stat_labels["Fail"].config(text=fl)
                    self._stat_labels["Crash"].config(text=cr)
                    self._stat_labels["Elapsed"].config(text=el)
                elif item[0] == "done":
                    self._on_run_done()
        except queue.Empty:
            pass

        self.after(80, self._process_queues)

    # ── LOGGING ──────────────────────────────────────────────────────────────

    def _log(self, msg: str, tag: str = "info"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        self._log_text.config(state="normal")
        self._log_text.insert("end", line, tag)
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _clear_log(self):
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    # ── SESSION MANAGEMENT ───────────────────────────────────────────────────

    def _new_session(self):
        if self._steps and messagebox.askyesno(
                "New Session", "Discard current steps and start new?", parent=self):
            self._steps.clear()
            self._selected_step_idx = -1
            self._session_file = None
            self.title("AOSP IVI Reproduction Tool — New Session")
            self._render_steps()
            self._clear_log()

    def _save_session(self):
        if not self._session_file:
            path = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON Session", "*.json")],
                initialdir=str(self.SESSION_DIR),
                parent=self
            )
            if not path:
                return
            self._session_file = Path(path)

        data = {
            "version": "2.0",
            "saved": datetime.datetime.now().isoformat(),
            "iterations": self._iter_var.get(),
            "delay_ms": self._delay_var.get(),
            "steps": self._steps
        }
        try:
            self._session_file.write_text(json.dumps(data, indent=2))
            self.title(f"AOSP IVI Reproduction Tool — {self._session_file.name}")
            self._log(f"💾 Saved: {self._session_file.name}", "info")
            self._refresh_history()
        except Exception as e:
            messagebox.showerror("Save Error", str(e), parent=self)

    def _load_session(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON Session", "*.json"), ("All", "*.*")],
            initialdir=str(self.SESSION_DIR),
            parent=self
        )
        if path:
            self._load_from_file(Path(path))

    def _load_from_file(self, path: Path):
        try:
            data = json.loads(path.read_text())
            self._steps = data.get("steps", [])
            self._iter_var.set(str(data.get("iterations", "100")))
            self._delay_var.set(str(data.get("delay_ms", "300")))
            self._session_file = path
            self._selected_step_idx = -1
            self.title(f"AOSP IVI Reproduction Tool — {path.name}")
            self._render_steps()
            self._log(f"📂 Loaded: {path.name} ({len(self._steps)} steps)", "info")
        except Exception as e:
            messagebox.showerror("Load Error", str(e), parent=self)

    def _load_from_history(self, event=None):
        sel = self._hist_listbox.curselection()
        if not sel:
            return
        name = self._hist_listbox.get(sel[0])
        path = self.SESSION_DIR / name
        if path.exists():
            self._load_from_file(path)

    def _refresh_history(self):
        self._hist_listbox.delete(0, "end")
        files = sorted(self.SESSION_DIR.glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files[:30]:
            self._hist_listbox.insert("end", f.name)

    # ── DEVICE MONITOR ───────────────────────────────────────────────────────

    def _start_device_monitor(self):
        def monitor():
            while True:
                ok, serial = ADB.device_connected()
                self.after(0, self._update_device_status, ok, serial)
                time.sleep(3)

        threading.Thread(target=monitor, daemon=True).start()

    def _update_device_status(self, connected: bool, info: str):
        self._device_connected = connected
        self._device_serial = info if connected else "—"
        if connected:
            self._dev_dot.config(fg=C["green"])
            self._dev_label.config(text=f"Connected  {info}", fg=C["green"])
            self._dev_rows["Serial"].config(text=info)
            self._dev_rows["Status"].config(text="✅ Ready", fg=C["green"])
        else:
            self._dev_dot.config(fg=C["red"])
            self._dev_label.config(text=f"No device  ({info})", fg=C["red"])
            self._dev_rows["Serial"].config(text="—")
            self._dev_rows["Status"].config(text="❌ " + info, fg=C["red"])

    def _refresh_device(self):
        ok, serial = ADB.device_connected()
        self._update_device_status(ok, serial)
        if ok:
            # Get screen size
            w, h = ADB.get_screen_size()
            self._dev_rows["Screen"].config(text=f"{w}×{h}")
            # Get Android version
            _, ver = ADB.run("shell getprop ro.build.version.release")
            self._dev_rows["Android"].config(text=f"Android {ver.strip()}")
            self._log(f"🔄 Device refreshed: {serial}  {w}×{h}  Android {ver.strip()}", "info")

    def _get_screen_size(self):
        w, h = ADB.get_screen_size()
        self._dev_rows["Screen"].config(text=f"{w}×{h}")
        self._log(f"📐 Screen: {w}×{h}", "info")
        messagebox.showinfo("Screen Size", f"Resolution: {w} × {h}", parent=self)

    def _reboot_device(self):
        if messagebox.askyesno("Reboot", "Reboot the connected device?", parent=self):
            ADB.run("reboot")
            self._log("🔄 Reboot command sent.", "warn")

    def _take_screenshot(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.SCREENSHOT_DIR / f"manual_{ts}.png"
        if ADB.screenshot(str(path)):
            self._log(f"📸 Screenshot saved: {path.name}", "info")
            if PIL_AVAILABLE:
                self._show_screenshot(str(path))
        else:
            self._log("Screenshot failed — is device connected?", "warn")

    def _show_screenshot(self, path: str):
        try:
            win = tk.Toplevel(self)
            win.title("Screenshot")
            win.configure(bg=C["bg"])
            img = Image.open(path)
            img.thumbnail((600, 400))
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(win, image=photo, bg=C["bg"])
            lbl.image = photo
            lbl.pack(padx=10, pady=10)
        except Exception:
            pass

    # ── SCREENSHOT DIFF ──────────────────────────────────────────────────────

    def _compare_screenshots(self, path1: str, path2: str) -> float:
        if not PIL_AVAILABLE:
            return 0.0
        try:
            img1 = Image.open(path1).convert("L").resize((160, 90))
            img2 = Image.open(path2).convert("L").resize((160, 90))
            import statistics
            diffs = [abs(a - b) for a, b in zip(img1.getdata(), img2.getdata())]
            return (statistics.mean(diffs) / 255) * 100
        except Exception:
            return 0.0

    # ── EXPORT REPORT ────────────────────────────────────────────────────────

    def _export_report(self):
        results_files = sorted(
            self.SESSION_DIR.glob("results_*.json"),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        if not results_files:
            messagebox.showinfo("No Results", "Run a test first to generate results.", parent=self)
            return

        latest = results_files[0]
        try:
            data = json.loads(latest.read_text())
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)
            return

        save_path = filedialog.asksaveasfilename(
            defaultextension=".html",
            filetypes=[("HTML Report", "*.html"), ("Text", "*.txt")],
            initialfile=f"report_{data.get('timestamp', 'unknown')}.html",
            parent=self
        )
        if not save_path:
            return

        html = self._build_html_report(data)
        Path(save_path).write_text(html)
        self._log(f"📊 Report exported: {Path(save_path).name}", "info")
        messagebox.showinfo("Exported", f"Report saved:\n{save_path}", parent=self)

    @staticmethod
    def _build_html_report(data: dict) -> str:
        rows = ""
        for r in data.get("results", []):
            color = "#22C55E" if r["status"] == "PASS" else "#EF4444"
            crash = r.get("crash", "") or ""
            rows += (f"<tr>"
                     f"<td>{r['iteration']}</td>"
                     f"<td style='color:{color};font-weight:bold'>{r['status']}</td>"
                     f"<td style='color:#F59E0B;font-size:12px'>{crash[:120]}</td>"
                     f"</tr>\n")

        pct = round(data.get("pass", 0) / max(data.get("iterations", 1), 1) * 100, 1)
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Repro Report — {data.get('session','')}</title>
<style>
  body{{font-family:Segoe UI,sans-serif;background:#0F1923;color:#E8F4FD;margin:0;padding:24px}}
  h1{{color:#00D4C8;margin-bottom:4px}}
  .meta{{color:#7A9BBF;font-size:13px;margin-bottom:24px}}
  .stats{{display:flex;gap:20px;margin-bottom:24px}}
  .stat{{background:#162030;border-radius:10px;padding:16px 24px;text-align:center}}
  .stat .val{{font-size:28px;font-weight:700;margin:4px 0}}
  .stat .lbl{{font-size:12px;color:#7A9BBF}}
  table{{width:100%;border-collapse:collapse;background:#162030;border-radius:8px;overflow:hidden}}
  th{{background:#1E2D40;padding:10px 14px;text-align:left;font-size:13px;color:#7A9BBF}}
  td{{padding:8px 14px;border-bottom:1px solid #243548;font-size:13px}}
  tr:last-child td{{border-bottom:none}}
</style></head>
<body>
<h1>AOSP IVI Reproduction Report</h1>
<div class="meta">Session: {data.get('session','')} &nbsp;|&nbsp;
  {data.get('timestamp','')} &nbsp;|&nbsp; {data.get('elapsed_s',0)}s elapsed</div>
<div class="stats">
  <div class="stat"><div class="val">{data.get('iterations',0)}</div><div class="lbl">Total</div></div>
  <div class="stat"><div class="val" style="color:#22C55E">{data.get('pass',0)}</div><div class="lbl">Pass</div></div>
  <div class="stat"><div class="val" style="color:#EF4444">{data.get('fail',0)}</div><div class="lbl">Fail</div></div>
  <div class="stat"><div class="val" style="color:#F59E0B">{data.get('crash',0)}</div><div class="lbl">Crash</div></div>
  <div class="stat"><div class="val">{pct}%</div><div class="lbl">Pass Rate</div></div>
</div>
<table>
<tr><th>Iter</th><th>Status</th><th>Crash Detail</th></tr>
{rows}
</table>
</body></html>"""

    # ── UTILITIES ────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s:02d}s" if m else f"{s}s"

    def _on_close(self):
        if self._running:
            if not messagebox.askyesno("Exit", "A run is in progress. Stop and exit?", parent=self):
                return
            self._stop_run()
            time.sleep(0.3)
        self.destroy()


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = ReproTool()
    app.mainloop()
