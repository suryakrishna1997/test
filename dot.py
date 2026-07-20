#!/usr/bin/env python3
"""
adb_status_dot.py
==================
Minimal ADB device detector: shows a green dot if a device is connected
and authorized, red dot otherwise. Auto-refreshes every 2 seconds, plus
a manual Refresh button. Log box under the dot shows the raw
`adb devices -l` output so a red dot is always explainable.

Tries several common adb locations if `adb` isn't found on PATH.
"""

import os
import shutil
import subprocess
import tkinter as tk
from tkinter import scrolledtext

# Common install locations to fall back to if "adb" isn't on PATH.
_home = os.path.expanduser("~")
FALLBACK_ADB_PATHS = [
    r"D:\adb 1\adb\abd.exe",
    r"D:\adb 1\adb\adb.exe",
    "/usr/bin/adb",
    "/usr/local/bin/adb",
    "/opt/homebrew/bin/adb",
    os.path.join(_home, "Library/Android/sdk/platform-tools/adb"),      # macOS
    os.path.join(_home, "AppData/Local/Android/Sdk/platform-tools/adb.exe"),  # Windows
    os.path.join(_home, "Android/Sdk/platform-tools/adb"),              # Linux
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


class AdbStatusApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ADB Device Status")
        self.root.geometry("420x260")

        self.adb_path = find_adb()

        top = tk.Frame(root, pady=12)
        top.pack()

        self.canvas = tk.Canvas(top, width=40, height=40, highlightthickness=0)
        self.dot = self.canvas.create_oval(4, 4, 36, 36, fill="red", outline="")
        self.canvas.pack(side="left", padx=(0, 12))

        self.label_var = tk.StringVar(value="No device detected")
        tk.Label(top, textvariable=self.label_var, font=("TkDefaultFont", 12)).pack(side="left")

        tk.Button(root, text="Refresh Now", command=self.refresh).pack(pady=(0, 8))

        self.log = scrolledtext.ScrolledText(root, height=8, font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.log.configure(state="disabled")

        if not self.adb_path:
            self._write_log("adb binary not found on PATH or in common SDK locations.\n"
                             "Set FALLBACK_ADB_PATHS in this script to your adb's exact path.")
        else:
            self._write_log(f"Using adb at: {self.adb_path}")

        self.refresh()

    def _write_log(self, text):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", text)
        self.log.configure(state="disabled")

    def set_dot(self, connected):
        self.canvas.itemconfig(self.dot, fill="green" if connected else "red")
        self.label_var.set("Device connected" if connected else "No device detected")

    def refresh(self):
        if not self.adb_path:
            self.set_dot(False)
            self.root.after(2000, self.refresh)
            return

        try:
            proc = subprocess.run(
                [self.adb_path, "devices", "-l"],
                capture_output=True, text=True, timeout=5,
            )
            out = proc.stdout.strip()
            err = proc.stderr.strip()
        except Exception as e:
            self.set_dot(False)
            self._write_log(f"Failed to run adb: {e}")
            self.root.after(2000, self.refresh)
            return

        lines = [l for l in out.splitlines() if l.strip() and "list of devices" not in l.lower()]
        # A device counts as "connected" only if its state is exactly "device"
        # (not "unauthorized" or "offline").
        connected = any(len(l.split()) >= 2 and l.split()[1] == "device" for l in lines)

        self.set_dot(connected)
        log_text = f"$ adb devices -l\n{out or '<empty>'}"
        if err:
            log_text += f"\nstderr: {err}"
        self._write_log(log_text)

        self.root.after(2000, self.refresh)


def main():
    root = tk.Tk()
    AdbStatusApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
