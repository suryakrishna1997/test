#!/usr/bin/env python3
"""
adb_test_replay.py
==================

A Tkinter desktop application for recording real screen taps on an Android
device (via `adb shell getevent`) and replaying the exact sequence a
user-defined number of times.

Key features
------------
* Real device tap capture using `adb shell getevent` (parsed live).
* Coordinate scaling from raw touch-device coordinates to screen pixels
  using ranges discovered via `adb shell getevent -lp` and
  `adb shell wm size`.
* Fallback manual recording by clicking on a canvas that represents the
  device screen (useful if getevent parsing fails on some devices).
* Iteration count is read **directly from a GUI text box** (Spinbox with
  default value 50) - never hardcoded.
* Inter-cycle delay is also read from a GUI text box (default 1 sec).
* Threading for non-blocking recording/replay; UI stays responsive.
* Thread-safe logging via a queue polled with `root.after()`.
* Save / Load recordings as JSON.
* Robust ADB pre-checks and graceful abort on device disconnect.
* `adb devices -l` is run for real on every refresh and its raw output is
  written to the Log Console, so a "(no device)" state is always
  explainable instead of a silent guess.

Tested with Python 3.8+ on Windows / macOS / Linux. Requires `adb` in PATH.
"""

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk


# ============================================================
# ADB binary discovery
# ============================================================
# If "adb" isn't found on PATH, these locations are tried in order.
# Add your own path here first if it's still not found.
_home = os.path.expanduser("~")
FALLBACK_ADB_PATHS = [
    r"D:\adb 1\adb\abd.exe",
    r"D:\adb 1\adb\adb.exe",
    "/usr/bin/adb",
    "/usr/local/bin/adb",
    "/opt/homebrew/bin/adb",
    os.path.join(_home, "Library/Android/sdk/platform-tools/adb"),            # macOS
    os.path.join(_home, "AppData/Local/Android/Sdk/platform-tools/adb.exe"),  # Windows
    os.path.join(_home, "Android/Sdk/platform-tools/adb"),                    # Linux
]


def find_adb():
    """Return a working adb path/command, or None if none work."""
    which = shutil.which("adb")
    if which:
        return which
    for candidate in FALLBACK_ADB_PATHS:
        if os.path.isfile(candidate):
            return candidate
    return None


# ============================================================
# Constants
# ============================================================
APP_TITLE = "ADB Tap Recorder & Replay"
DEFAULT_ITERATIONS = 50                # default value in the Iterations box
DEFAULT_INTER_CYCLE_DELAY = 1.0        # seconds between full cycles
ADB_SHORT_TIMEOUT = 5                  # seconds for short ADB commands
DEFAULT_FALLBACK_DELAY_MS = 300        # delay for manually-clicked taps
SWIPE_DISTANCE_THRESHOLD_PX = 20       # screen-px movement beyond which a
                                        # gesture is treated as a swipe, not a tap
MIN_SWIPE_DURATION_MS = 50             # floor for `input swipe` duration

# Linux input-event constants (see <linux/input-event-codes.h>)
EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03

SYN_REPORT = 0x00
BTN_TOUCH = 0x14A
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
ABS_MT_TRACKING_ID = 0x39              # some devices use this instead of BTN_TOUCH
ABS_X = 0x00                           # legacy single-touch
ABS_Y = 0x01

# Regex for parsing a getevent stream line.
#   /dev/input/event2: 0003 0035 00000abc
#   [ 1234.567890] /dev/input/event2: 0003 0035 00000abc
_GETEVENT_RE = re.compile(
    r"^\s*(?:\[\s*[\d.]+\s*\]\s+)?"
    r"[^:]+:\s+"
    r"([0-9a-fA-F]{4})\s+"             # event type
    r"([0-9a-fA-F]{4})\s+"             # event code
    r"([0-9a-fA-F]+)"                  # value
)


# ============================================================
# ADB wrapper
# ============================================================
class ADBInterface:
    """Thin wrapper around `adb` subprocess calls."""

    def __init__(self, device=None):
        self.device = device  # device serial; None = let adb pick the default
        self.adb_bin = find_adb()  # resolved path/command to the adb binary

    # ---------- low-level runner ----------
    def _build_cmd(self, *args):
        cmd = [self.adb_bin or "adb"]
        if self.device:
            cmd += ["-s", self.device]
        cmd += list(args)
        return cmd

    def run(self, *args, timeout=ADB_SHORT_TIMEOUT):
        """Run an adb command synchronously. Returns (rc, stdout, stderr)."""
        cmd = self._build_cmd(*args)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
        except FileNotFoundError:
            return -1, "", "adb not found in PATH"
        except subprocess.TimeoutExpired:
            return -1, "", f"adb command timed out: {' '.join(cmd)}"

    # ---------- high-level helpers ----------
    def is_installed(self):
        if not self.adb_bin:
            return False
        rc, _, _ = self.run("version")
        return rc == 0

    def restart_server(self):
        """Kill and restart the adb server. Fixes a lot of 'no device'
        false negatives caused by a stale/stuck server process."""
        self.run("kill-server", timeout=10)
        return self.run("start-server", timeout=10)

    def list_devices_raw(self):
        """
        Run `adb devices -l` (NOT cached, always a live call) and return
        (rc, raw_stdout, raw_stderr, entries) where entries is a list of
        dicts: {"serial": str, "state": str, "detail": str}.

        state is whatever adb reports verbatim: 'device', 'unauthorized',
        'offline', 'no permissions', etc. This is deliberately NOT
        collapsed down to a bool so the caller can show the real reason.
        """
        rc, out, err = self.run("devices", "-l", timeout=10)
        entries = []
        if rc == 0 and out:
            lines = out.splitlines()
            # First line is "List of devices attached" (skip it if present)
            for line in lines:
                line = line.strip()
                if not line or line.lower().startswith("list of devices"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    entries.append(
                        {
                            "serial": parts[0],
                            "state": parts[1],
                            "detail": " ".join(parts[2:]),
                        }
                    )
        return rc, out, err, entries

    def list_devices(self):
        """Backward-compatible helper: serials that are actually usable
        (state == 'device')."""
        _, _, _, entries = self.list_devices_raw()
        return [e["serial"] for e in entries if e["state"] == "device"]

    def get_state(self):
        rc, out, _ = self.run("get-state")
        return rc == 0 and out == "device"

    def device_online(self):
        return self.get_state()

    def get_screen_size(self):
        rc, out, _ = self.run("shell", "wm", "size")
        if rc != 0:
            return None
        m = re.search(r"(\d+)x(\d+)", out)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        return None

    def get_touch_device_info(self):
        """
        Discover the touch input device and its raw X/Y ranges by parsing
        `adb shell getevent -lp`. Returns a dict or None on failure.

        The dict contains: device_path, x_code, y_code, x_min, x_max,
        y_min, y_max.
        """
        rc, out, _ = self.run("shell", "getevent", "-lp", timeout=10)
        if rc != 0:
            return None

        devices = {}
        current = None
        for line in out.splitlines():
            m_dev = re.match(r"add device\s+\d+:\s+(.+)$", line.strip())
            if m_dev:
                current = m_dev.group(1).strip()
                devices[current] = {}
                continue
            if current is None:
                continue
            # Lines like:
            #   0035  : value 0, min 0, max 1080, fuzz 0, flat 0, resolution 0
            m_axis = re.match(
                r"\s*([0-9a-fA-F]{4})\s*:\s*value\s+\d+,\s*min\s+(\d+),\s*max\s+(\d+)",
                line,
            )
            if m_axis:
                code = int(m_axis.group(1), 16)
                lo = int(m_axis.group(2))
                hi = int(m_axis.group(3))
                devices[current][code] = (lo, hi)

        # Find a device that exposes either ABS_MT_POSITION_X/Y or ABS_X/Y.
        target_x = [ABS_MT_POSITION_X, ABS_X]
        target_y = [ABS_MT_POSITION_Y, ABS_Y]
        for path, axes in devices.items():
            xc = next((c for c in target_x if c in axes), None)
            yc = next((c for c in target_y if c in axes), None)
            if xc is not None and yc is not None:
                return {
                    "device_path": path,
                    "x_code": xc,
                    "y_code": yc,
                    "x_min": axes[xc][0],
                    "x_max": axes[xc][1],
                    "y_min": axes[yc][0],
                    "y_max": axes[yc][1],
                }
        return None

    def tap(self, x, y):
        """Send a tap. Returns (rc, stdout, stderr)."""
        return self.run("shell", "input", "tap", str(x), str(y))

    def swipe(self, x1, y1, x2, y2, duration_ms):
        """Send a swipe/drag from (x1,y1) to (x2,y2) over duration_ms.
        Returns (rc, stdout, stderr)."""
        return self.run(
            "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(int(duration_ms)),
        )

    def start_getevent_stream(self):
        """Start `adb shell getevent` as a streaming Popen."""
        cmd = self._build_cmd("shell", "getevent")
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
        )


# ============================================================
# Main application
# ============================================================
class ADBTestReplayApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("980x780")
        self.root.minsize(800, 600)

        # ---------- State ----------
        self.adb = ADBInterface()
        self.recorded_taps = []  # list of (x, y, delay_ms)
        self.record_thread = None
        self.replay_thread = None
        self.stop_record_flag = threading.Event()
        self.stop_replay_flag = threading.Event()
        self.getevent_proc = None
        self.touch_info = None
        self.screen_size = None

        # Thread-safe log queue (worker threads -> main thread)
        self.log_queue = queue.Queue()

        # ---------- Tk variables ----------
        self.iterations_var = tk.StringVar(value=str(DEFAULT_ITERATIONS))
        self.delay_var = tk.StringVar(value=str(DEFAULT_INTER_CYCLE_DELAY))
        self.status_var = tk.StringVar(value="Idle")
        self.device_var = tk.StringVar(value="(no device)")
        self.summary_var = tk.StringVar(value="No recording yet.")

        # ---------- Build UI ----------
        self._build_ui()

        # ---------- Start background polling ----------
        self._start_log_polling()

        # ---------- Initial ADB checks ----------
        self._initial_checks()

    # ----------------------------------------------------
    # UI construction
    # ----------------------------------------------------
    def _build_ui(self):
        # --- Top status bar ---
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Status:").grid(row=0, column=0, sticky="w")
        ttk.Label(
            top,
            textvariable=self.status_var,
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=1, sticky="w", padx=(4, 16))

        ttk.Label(top, text="Device:").grid(row=0, column=2, sticky="w")
        ttk.Label(top, textvariable=self.device_var).grid(
            row=0, column=3, sticky="w", padx=(4, 16)
        )

        ttk.Button(
            top, text="Refresh Device", command=self._refresh_device_info
        ).grid(row=0, column=4, padx=4)

        ttk.Button(
            top, text="Restart ADB Server", command=self._on_restart_server
        ).grid(row=0, column=5, padx=4)

        # --- Control panel ---
        ctrl = ttk.LabelFrame(self.root, text="Controls", padding=10)
        ctrl.pack(fill="x", padx=8, pady=4)

        ttk.Button(
            ctrl,
            text="Start Recording",
            command=self.on_start_recording,
            width=18,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            ctrl,
            text="Stop Recording",
            command=self.on_stop_recording,
            width=18,
        ).grid(row=0, column=1, sticky="w")
        ttk.Button(
            ctrl,
            text="Clear Recording",
            command=self.on_clear_recording,
            width=18,
        ).grid(row=0, column=2, sticky="w")

        ttk.Label(ctrl, text="Iterations:").grid(
            row=1, column=0, sticky="e", pady=(8, 0)
        )
        # The CORE iteration text box - drives the replay loop count.
        ttk.Spinbox(
            ctrl,
            from_=1,
            to=100000,
            increment=1,
            textvariable=self.iterations_var,
            width=10,
        ).grid(row=1, column=1, sticky="w", pady=(8, 0))

        ttk.Label(ctrl, text="Delay between cycles (sec):").grid(
            row=1, column=2, sticky="e", pady=(8, 0)
        )
        ttk.Spinbox(
            ctrl,
            from_=0,
            to=3600,
            increment=0.5,
            textvariable=self.delay_var,
            width=10,
        ).grid(row=1, column=3, sticky="w", pady=(8, 0))

        ttk.Button(
            ctrl,
            text="Run (Replay)",
            command=self.on_run_replay,
            width=18,
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Button(
            ctrl,
            text="Stop Replay",
            command=self.on_stop_replay,
            width=18,
        ).grid(row=2, column=1, sticky="w", pady=(8, 0))
        ttk.Button(
            ctrl,
            text="Save Recording",
            command=self.on_save_recording,
            width=18,
        ).grid(row=2, column=2, sticky="w", pady=(8, 0))
        ttk.Button(
            ctrl,
            text="Load Recording",
            command=self.on_load_recording,
            width=18,
        ).grid(row=2, column=3, sticky="w", pady=(8, 0))

        # --- Mid section: canvas + log ---
        mid = ttk.Frame(self.root)
        mid.pack(fill="both", expand=True, padx=8, pady=4)

        # Left: fallback canvas for manual tap recording
        left = ttk.LabelFrame(
            mid,
            text="Fallback: click=tap, click-drag=swipe",
            padding=8,
        )
        left.pack(side="left", fill="y")
        self.canvas = tk.Canvas(
            left,
            width=180,
            height=320,
            bg="#f0f0f0",
            relief="sunken",
            borderwidth=2,
        )
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        ttk.Label(
            left,
            text="Click = tap\nClick-drag = swipe\n(default 300ms delay)",
            foreground="gray",
        ).pack(pady=4)
        ttk.Button(
            left, text="Clear Markers", command=self._clear_canvas_markers
        ).pack()

        # Right: log console
        right = ttk.LabelFrame(mid, text="Log Console", padding=4)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.log_text = scrolledtext.ScrolledText(
            right, wrap="word", height=15, font=("Consolas", 9)
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")

        # --- Bottom: recording summary ---
        bottom = ttk.Frame(self.root, padding=6)
        bottom.pack(fill="x")
        ttk.Label(bottom, textvariable=self.summary_var).pack(side="left")

    # ----------------------------------------------------
    # Logging & status (thread-safe via queue + after())
    # ----------------------------------------------------
    def log(self, msg, level="INFO"):
        ts = time.strftime("%H:%M:%S")
        self.log_queue.put(f"[{ts}] {level}: {msg}")

    def _start_log_polling(self):
        self._poll_log()
        self._poll_status()

    def _poll_log(self):
        """Drain the log queue and append lines to the ScrolledText."""
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log)

    def _poll_status(self):
        """Periodically update button enabled/disabled states."""
        recording = self.record_thread is not None and self.record_thread.is_alive()
        replaying = self.replay_thread is not None and self.replay_thread.is_alive()

        self._set_button_state("Start Recording", not recording and not replaying)
        self._set_button_state("Stop Recording", recording)
        # Run button stays enabled even with no recording so the validation
        # in on_run_replay can show the required error popup.
        self._set_button_state("Run (Replay)", not recording and not replaying)
        self._set_button_state("Stop Replay", replaying)

        self.root.after(200, self._poll_status)

    def _set_button_state(self, label, enabled):
        for w in self.root.winfo_children():
            self._recursive_set_button(w, label, enabled)

    def _recursive_set_button(self, widget, label, enabled):
        if isinstance(widget, ttk.Button) and widget.cget("text") == label:
            widget.configure(state="normal" if enabled else "disabled")
        for child in widget.winfo_children():
            self._recursive_set_button(child, label, enabled)

    def set_status(self, text):
        """Thread-safe status update."""
        self.root.after(0, self.status_var.set, text)

    def set_summary(self, text):
        self.root.after(0, self.summary_var.set, text)

    # ----------------------------------------------------
    # ADB pre-checks
    # ----------------------------------------------------
    def _initial_checks(self):
        if not self.adb.is_installed():
            self.log(
                "ADB binary not found on PATH or in common SDK locations. "
                "Edit FALLBACK_ADB_PATHS at the top of this script and add "
                "your adb.exe's exact path.",
                "ERROR",
            )
            messagebox.showerror(
                "ADB Missing",
                "Could not find an adb binary.\n"
                "Edit FALLBACK_ADB_PATHS at the top of this script and add "
                "the exact path to your adb.exe, then restart.",
            )
            return
        self.log(f"ADB found: {self.adb.adb_bin}")
        self._refresh_device_info()

    def _on_restart_server(self):
        self.log("Restarting adb server (adb kill-server / start-server)...")
        rc, out, err = self.adb.restart_server()
        if rc == 0:
            self.log("adb server restarted.")
        else:
            self.log(f"adb server restart returned rc={rc}: {err or out}", "WARN")
        self._refresh_device_info()

    def _refresh_device_info(self):
        # ---- Always run the REAL `adb devices -l` and show it verbatim ----
        rc, raw_out, raw_err, entries = self.adb.list_devices_raw()

        self.log(f"$ adb devices -l  (rc={rc})")
        if raw_out:
            for line in raw_out.splitlines():
                self.log(f"    {line}")
        else:
            self.log("    <empty output>")
        if raw_err:
            self.log(f"    stderr: {raw_err}", "WARN")

        if rc != 0:
            self.device_var.set("(no device)")
            self.log(
                "`adb devices` itself failed to run. Check that adb is "
                "installed and in PATH, and that no other process is "
                "holding the adb server port (5037).",
                "ERROR",
            )
            return

        if not entries:
            self.device_var.set("(no device)")
            self.log(
                "adb server reports zero devices at all (not even "
                "unauthorized/offline). This usually means: the USB "
                "cable is charge-only, the device isn't actually plugged "
                "into this machine, or a stale adb server needs a "
                "restart. Try 'Restart ADB Server'.",
                "WARN",
            )
            messagebox.showwarning(
                "No Device",
                "`adb devices -l` returned no entries at all.\n\n"
                "Check the Log Console for the raw output. Try a "
                "different USB cable/port, confirm the cable supports "
                "data (not charge-only), and try 'Restart ADB Server'.",
            )
            return

        ready = [e for e in entries if e["state"] == "device"]
        unauthorized = [e for e in entries if e["state"] == "unauthorized"]
        offline = [e for e in entries if e["state"] == "offline"]
        other = [
            e for e in entries
            if e not in ready and e not in unauthorized and e not in offline
        ]

        if unauthorized:
            self.device_var.set("(unauthorized)")
            self.log(
                f"Device {unauthorized[0]['serial']} is listed but "
                "UNAUTHORIZED. USB debugging is on, but you haven't "
                "accepted the 'Allow USB debugging?' RSA fingerprint "
                "prompt on the device screen yet. Unlock the phone and "
                "tap Allow, then Refresh Device again.",
                "WARN",
            )
            messagebox.showwarning(
                "Device Unauthorized",
                f"Device {unauthorized[0]['serial']} is connected but "
                "unauthorized.\n\nUnlock the device and accept the "
                "'Allow USB debugging?' prompt, then click Refresh "
                "Device.",
            )
            return

        if offline and not ready:
            self.device_var.set("(offline)")
            self.log(
                f"Device {offline[0]['serial']} is listed as OFFLINE. "
                "Try unplugging/replugging the USB cable or 'Restart ADB "
                "Server'.",
                "WARN",
            )
            return

        if not ready:
            self.device_var.set("(no device)")
            self.log(
                f"Devices found but in an unexpected state: {other}. "
                "See raw output above.",
                "WARN",
            )
            return

        # ---- We have at least one usable device ----
        if len(ready) == 1:
            self.adb.device = ready[0]["serial"]
        else:
            self.adb.device = ready[0]["serial"]
            self.log(
                f"Multiple authorized devices found; using "
                f"{ready[0]['serial']}.",
                "WARN",
            )
        self.device_var.set(self.adb.device)
        self.log(f"Using device: {self.adb.device}")

        # Screen size (for scaling and canvas mapping)
        ss = self.adb.get_screen_size()
        if ss:
            self.screen_size = ss
            self.log(f"Screen size: {ss[0]}x{ss[1]}")
        else:
            self.log("Could not retrieve screen size.", "WARN")

        # Touch-device ranges
        ti = self.adb.get_touch_device_info()
        if ti:
            self.touch_info = ti
            self.log(
                f"Touch device: {ti['device_path']} "
                f"X[{ti['x_min']}-{ti['x_max']}] "
                f"Y[{ti['y_min']}-{ti['y_max']}]"
            )
        else:
            self.log(
                "Could not auto-discover touch device. getevent parsing may "
                "still work, but coordinate scaling may be off. You can use "
                "the fallback canvas.",
                "WARN",
            )

    # ----------------------------------------------------
    # Coordinate scaling (raw touch -> screen pixels)
    # ----------------------------------------------------
    def _scale_raw_to_screen(self, raw_x, raw_y):
        if self.touch_info and self.screen_size:
            ti = self.touch_info
            sw, sh = self.screen_size
            x_range = max(1, ti["x_max"] - ti["x_min"])
            y_range = max(1, ti["y_max"] - ti["y_min"])
            x = int((raw_x - ti["x_min"]) * sw / x_range)
            y = int((raw_y - ti["y_min"]) * sh / y_range)
            x = max(0, min(sw - 1, x))
            y = max(0, min(sh - 1, y))
            return x, y
        return raw_x, raw_y

    # ----------------------------------------------------
    # Recording
    # ----------------------------------------------------
    def on_start_recording(self):
        if self.record_thread and self.record_thread.is_alive():
            self.log("Already recording.", "WARN")
            return
        if not self.adb.device_online():
            messagebox.showerror(
                "Device Offline",
                "Device is not online. Connect device and click Refresh Device.",
            )
            return
        # Start fresh - clear previous recording
        self.recorded_taps = []
        self._clear_canvas_markers()
        self.stop_record_flag.clear()
        self.record_thread = threading.Thread(
            target=self._record_worker, daemon=True
        )
        self.record_thread.start()

    def _record_worker(self):
        self.set_status("Recording...")
        self.log("Starting getevent stream. Tap or swipe the device screen now.")
        try:
            proc = self.adb.start_getevent_stream()
        except Exception as e:
            self.log(f"Failed to start getevent: {e}", "ERROR")
            self.set_status("Idle")
            return
        self.getevent_proc = proc

        cur_x = None
        cur_y = None
        pending_down = False   # a touch-down was seen, waiting for SYN to open gesture
        pending_up = False     # a touch-up was seen, waiting for SYN to close gesture
        gesture_active = False
        start_x = start_y = None
        start_time = None
        last_x = last_y = None
        last_event_time = None  # time.monotonic() of the previous recorded gesture's end

        x_codes = (ABS_MT_POSITION_X, ABS_X)
        y_codes = (ABS_MT_POSITION_Y, ABS_Y)
        if self.touch_info:
            x_codes = (self.touch_info["x_code"],)
            y_codes = (self.touch_info["y_code"],)

        try:
            for line in proc.stdout:
                if self.stop_record_flag.is_set():
                    break
                line = line.strip()
                if not line:
                    continue
                m = _GETEVENT_RE.match(line)
                if not m:
                    continue
                ev_type = int(m.group(1), 16)
                ev_code = int(m.group(2), 16)
                ev_value = int(m.group(3), 16)

                if ev_type == EV_ABS:
                    if ev_code in x_codes:
                        cur_x = ev_value
                    elif ev_code in y_codes:
                        cur_y = ev_value
                    elif ev_code == ABS_MT_TRACKING_ID:
                        # value 0xFFFFFFFF (= -1 signed) = touch up;
                        # anything else = new touch down
                        if ev_value != 0xFFFFFFFF:
                            pending_down = True
                        else:
                            pending_up = True
                elif ev_type == EV_KEY and ev_code == BTN_TOUCH:
                    if ev_value == 1:
                        pending_down = True
                    elif ev_value == 0:
                        pending_up = True
                elif ev_type == EV_SYN and ev_code == SYN_REPORT:
                    now = time.monotonic()

                    # Open a new gesture on touch-down.
                    if pending_down and not gesture_active and cur_x is not None and cur_y is not None:
                        gesture_active = True
                        start_x, start_y = cur_x, cur_y
                        last_x, last_y = cur_x, cur_y
                        start_time = now
                    pending_down = False

                    # Track movement while the finger is down.
                    if gesture_active and cur_x is not None and cur_y is not None:
                        last_x, last_y = cur_x, cur_y

                    # Close the gesture on touch-up.
                    if pending_up and gesture_active:
                        gesture_active = False
                        pending_up = False

                        sx1, sy1 = self._scale_raw_to_screen(start_x, start_y)
                        sx2, sy2 = self._scale_raw_to_screen(last_x, last_y)
                        duration_ms = max(
                            MIN_SWIPE_DURATION_MS, int((now - start_time) * 1000)
                        )
                        delay_ms = 0 if last_event_time is None else int(
                            (start_time - last_event_time) * 1000
                        )
                        last_event_time = now

                        dist = ((sx2 - sx1) ** 2 + (sy2 - sy1) ** 2) ** 0.5
                        if dist < SWIPE_DISTANCE_THRESHOLD_PX:
                            event = {
                                "type": "tap",
                                "x": sx1,
                                "y": sy1,
                                "delay_ms": delay_ms,
                            }
                            self.recorded_taps.append(event)
                            self.log(
                                f"Event #{len(self.recorded_taps)}: TAP "
                                f"({sx1},{sy1}) delay={delay_ms}ms"
                            )
                        else:
                            event = {
                                "type": "swipe",
                                "x1": sx1,
                                "y1": sy1,
                                "x2": sx2,
                                "y2": sy2,
                                "duration_ms": duration_ms,
                                "delay_ms": delay_ms,
                            }
                            self.recorded_taps.append(event)
                            self.log(
                                f"Event #{len(self.recorded_taps)}: SWIPE "
                                f"({sx1},{sy1})->({sx2},{sy2}) "
                                f"dur={duration_ms}ms delay={delay_ms}ms"
                            )
                    else:
                        pending_up = False
        except Exception as e:
            self.log(f"Recording error: {e}", "ERROR")
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            self.getevent_proc = None
            self.set_status("Idle")
            count = len(self.recorded_taps)
            self.log(f"Recording stopped. Captured {count} event(s).")
            self.set_summary(f"Recorded {count} event(s).")

    def on_stop_recording(self):
        if not (self.record_thread and self.record_thread.is_alive()):
            self.log("Not currently recording.", "WARN")
            return
        self.stop_record_flag.set()
        if self.getevent_proc:
            try:
                self.getevent_proc.terminate()
            except Exception:
                pass
        self.log("Stop signal sent to recording thread.")

    # ----------------------------------------------------
    # Replay
    # ----------------------------------------------------
    def on_run_replay(self):
        # Validate recording
        if not self.recorded_taps:
            messagebox.showerror(
                "No recording",
                "No recording found. Please record a sequence first.",
            )
            return
        if self.replay_thread and self.replay_thread.is_alive():
            messagebox.showwarning("Busy", "A replay is already running.")
            return

        # ---------- Read iterations FROM THE GUI TEXT BOX ----------
        raw_iter = self.iterations_var.get().strip()
        try:
            iterations = int(raw_iter)
        except ValueError:
            self.log(
                f"Invalid iterations value '{raw_iter}'. Defaulting to 1.",
                "WARN",
            )
            iterations = 1
            self.iterations_var.set("1")
        if iterations <= 0:
            self.log(
                f"Iterations must be positive (got {iterations}). "
                "Defaulting to 1.",
                "WARN",
            )
            iterations = 1
            self.iterations_var.set("1")

        # ---------- Read inter-cycle delay ----------
        raw_delay = self.delay_var.get().strip()
        try:
            inter_cycle_delay = float(raw_delay)
        except ValueError:
            self.log(
                f"Invalid delay value '{raw_delay}'. Defaulting to "
                f"{DEFAULT_INTER_CYCLE_DELAY}.",
                "WARN",
            )
            inter_cycle_delay = DEFAULT_INTER_CYCLE_DELAY
            self.delay_var.set(str(DEFAULT_INTER_CYCLE_DELAY))
        if inter_cycle_delay < 0:
            inter_cycle_delay = 0

        # Device check
        if not self.adb.device_online():
            messagebox.showerror(
                "Device Offline",
                "Device is not online. Connect device and click Refresh Device.",
            )
            return

        self.stop_replay_flag.clear()
        self.replay_thread = threading.Thread(
            target=self._replay_worker,
            args=(iterations, inter_cycle_delay),
            daemon=True,
        )
        self.replay_thread.start()

    @staticmethod
    def _normalize_event(raw_event):
        """Accepts either a new-style dict event ({"type": "tap"/"swipe", ...})
        or an old-style (x, y, delay_ms) tuple from a recording saved before
        swipe support was added, and returns a normalized dict."""
        if isinstance(raw_event, dict):
            return raw_event
        x, y, delay_ms = raw_event
        return {"type": "tap", "x": x, "y": y, "delay_ms": delay_ms}

    def _replay_worker(self, iterations, inter_cycle_delay):
        n_taps = len(self.recorded_taps)
        self.log(
            f"Replay starting: {iterations} iteration(s), "
            f"{n_taps} tap(s) per cycle."
        )
        for i in range(1, iterations + 1):
            if self.stop_replay_flag.is_set():
                self.log("Replay aborted by user.")
                break
            if not self.adb.device_online():
                self.log("Device went offline. Stopping replay.", "ERROR")
                break
            self.set_status(f"Playing iteration {i}/{iterations}")
            self.log(f"--- Iteration {i}/{iterations} ---")

            for idx, raw_event in enumerate(self.recorded_taps, start=1):
                if self.stop_replay_flag.is_set():
                    break
                ev = self._normalize_event(raw_event)
                delay_ms = ev["delay_ms"]

                if ev["type"] == "swipe":
                    self.log(
                        f"Event {idx}/{n_taps}: SWIPE ({ev['x1']},{ev['y1']})->"
                        f"({ev['x2']},{ev['y2']}) dur={ev['duration_ms']}ms "
                        f"+{delay_ms}ms"
                    )
                    rc, out, err = self.adb.swipe(
                        ev["x1"], ev["y1"], ev["x2"], ev["y2"], ev["duration_ms"]
                    )
                else:
                    self.log(
                        f"Event {idx}/{n_taps}: TAP ({ev['x']},{ev['y']}) "
                        f"+{delay_ms}ms"
                    )
                    rc, out, err = self.adb.tap(ev["x"], ev["y"])

                if rc != 0:
                    self.log(f"Event failed: {err}", "ERROR")
                    if not self.adb.device_online():
                        self.log(
                            "Device offline. Aborting replay.", "ERROR"
                        )
                        self.stop_replay_flag.set()
                        break
                if delay_ms > 0:
                    self._interruptible_sleep(delay_ms / 1000.0)

            if self.stop_replay_flag.is_set():
                break
            if i < iterations and inter_cycle_delay > 0:
                self.log(
                    f"Sleeping {inter_cycle_delay}s before next cycle..."
                )
                self._interruptible_sleep(inter_cycle_delay)

        self.set_status("Idle")
        if self.stop_replay_flag.is_set():
            self.log("Replay stopped early.")
        else:
            self.log("Replay finished.")
        self.replay_thread = None

    def _interruptible_sleep(self, seconds):
        """Sleep in small chunks so we can react to the stop flag quickly."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.stop_replay_flag.is_set():
                return
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))

    def on_stop_replay(self):
        if not (self.replay_thread and self.replay_thread.is_alive()):
            self.log("No replay in progress.", "WARN")
            return
        self.stop_replay_flag.set()
        self.log("Stop signal sent to replay thread.")

    # ----------------------------------------------------
    # Fallback canvas recording (click = tap, click-drag = swipe)
    # ----------------------------------------------------
    def _canvas_to_screen(self, cx, cy):
        sw, sh = self.screen_size
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        return int(cx * sw / cw), int(cy * sh / ch)

    def on_canvas_press(self, event):
        if not self.screen_size:
            messagebox.showinfo(
                "No Screen Size",
                "Screen size unknown. Click 'Refresh Device' first.",
            )
            return
        self._canvas_press_xy = (event.x, event.y)
        self._canvas_press_time = time.monotonic()

    def on_canvas_release(self, event):
        if not self.screen_size or not getattr(self, "_canvas_press_xy", None):
            return
        px, py = self._canvas_press_xy
        rx, ry = event.x, event.y
        self._canvas_press_xy = None

        sx1, sy1 = self._canvas_to_screen(px, py)
        sx2, sy2 = self._canvas_to_screen(rx, ry)
        elapsed_ms = max(
            MIN_SWIPE_DURATION_MS,
            int((time.monotonic() - self._canvas_press_time) * 1000),
        )
        delay_ms = 0 if not self.recorded_taps else DEFAULT_FALLBACK_DELAY_MS

        dist = ((sx2 - sx1) ** 2 + (sy2 - sy1) ** 2) ** 0.5
        if dist < SWIPE_DISTANCE_THRESHOLD_PX:
            event_data = {"type": "tap", "x": sx1, "y": sy1, "delay_ms": delay_ms}
            label = f"({sx1},{sy1})"
        else:
            event_data = {
                "type": "swipe", "x1": sx1, "y1": sy1, "x2": sx2, "y2": sy2,
                "duration_ms": elapsed_ms, "delay_ms": delay_ms,
            }
            label = f"({sx1},{sy1})->({sx2},{sy2}) dur={elapsed_ms}ms"

        self.recorded_taps.append(event_data)

        # Visualize
        if event_data["type"] == "swipe":
            self.canvas.create_line(px, py, rx, ry, fill="darkred", width=2, arrow="last")
        self.canvas.create_oval(px - 5, py - 5, px + 5, py + 5, fill="red", outline="darkred")
        self.canvas.create_text(
            px, py - 12, text=str(len(self.recorded_taps)),
            fill="darkred", font=("TkDefaultFont", 8, "bold"),
        )
        self.log(f"Manual event #{len(self.recorded_taps)} added: {label} delay={delay_ms}ms")
        self.set_summary(f"Recorded {len(self.recorded_taps)} event(s).")

    def _clear_canvas_markers(self):
        self.canvas.delete("all")

    # ----------------------------------------------------
    # Clear / Save / Load
    # ----------------------------------------------------
    def on_clear_recording(self):
        self.recorded_taps = []
        self._clear_canvas_markers()
        self.set_summary("No recording yet.")
        self.log("Recording cleared.")

    def on_save_recording(self):
        if not self.recorded_taps:
            messagebox.showinfo("Empty", "Nothing to save.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Save recording",
        )
        if not path:
            return
        try:
            with open(path, "w") as f:
                json.dump(
                    {
                        "screen_size": self.screen_size,
                        "events": [self._normalize_event(e) for e in self.recorded_taps],
                    },
                    f,
                    indent=2,
                )
            self.log(f"Recording saved to {path}")
        except Exception as e:
            self.log(f"Save failed: {e}", "ERROR")

    def on_load_recording(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Load recording",
        )
        if not path:
            return
        try:
            with open(path) as f:
                data = json.load(f)
            # Supports both new-style "events" (dicts) and old-style "taps"
            # (3-item lists) from recordings saved before swipe support.
            raw_events = data.get("events")
            if raw_events is None:
                raw_events = data.get("taps", [])
            self.recorded_taps = [self._normalize_event(e) for e in raw_events]
            if data.get("screen_size"):
                self.screen_size = tuple(data["screen_size"])
            self.log(f"Loaded {len(self.recorded_taps)} event(s) from {path}")
            self.set_summary(f"Loaded {len(self.recorded_taps)} tap(s).")
        except Exception as e:
            self.log(f"Load failed: {e}", "ERROR")


# ============================================================
# Entry point
# ============================================================
def main():
    root = tk.Tk()
    ADBTestReplayApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
