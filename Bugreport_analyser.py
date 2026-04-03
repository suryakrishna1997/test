#!/usr/bin/env python3
"""
automotive_bugreport_analyzer.py  —  v3.0  SCALE EDITION
Handles 1,000,000+ line bugreports without freezing or OOM.

Key engineering decisions vs v2:
  • Streaming line-by-line parser  → O(1) RAM per line, no full file load
  • Compiled regex with re.compile  → single pass, no repeated compilation
  • Progress throttled to 1 UI update / 50 ms  → no event-queue flooding
  • Lazy tree population in batches via root.after() chain → UI stays alive
  • CrashEvent stores only lightweight strings, no redundant full-file refs
  • Export streams directly to disk → no in-memory copy of output
  • Search / filter runs on crash list only (~hundreds), not millions of lines
  • All long ops on daemon threads — main thread is always responsive
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re
import threading
import json
import time
import mmap
import io
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional, Iterator

# ──────────────────────────────────────────────────────────────────────────────
# THEME
# ──────────────────────────────────────────────────────────────────────────────
C = {
    "bg":      "#0d0f12", "bg2":    "#141720", "bg3":    "#1c2030",
    "panel":   "#1a1d26", "border": "#2a2e3d",
    "accent":  "#00c8ff", "accent2":"#ff4f5a", "accent3":"#ffc947",
    "accent4": "#5aff8c",
    "text":    "#d8dce8", "text2":  "#7a8099", "text3":  "#4a5066",
    "fatal":   "#ff4f5a", "anr":    "#ffc947", "native": "#ff8c42",
    "watchdog":"#c47aff", "kernel": "#ff5f80", "system": "#ff6b6b",
    "unknown": "#7a8099", "nav":    "#00c8ff", "bt":     "#5aff8c",
    "media":   "#ffc947", "sys_mod":"#ff8c42", "hvac":   "#c47aff",
}

FM  = ("Consolas", 10)      # mono
FMs = ("Consolas", 9)       # mono small
FU  = ("Segoe UI", 10)      # ui normal
FUb = ("Segoe UI", 10, "bold")
FST = ("Consolas", 18, "bold")  # stat number

# ──────────────────────────────────────────────────────────────────────────────
# PARSER — compiled patterns, streaming, zero full-file load
# ──────────────────────────────────────────────────────────────────────────────
MODULES = {
    "navigation": [r"\b(?:navigation|gps|gps_hal|gnss|maprender|tilecache|routecalc)\b"],
    "bluetooth":  [r"\b(?:bluetooth|a2dp|hfp|headset(?:service)?|btservice)\b"],
    "media":      [r"\b(?:media|audio(?:track|policy|service)?|mediaplayer|drm)\b"],
    "system":     [r"\b(?:system.?server|watchdog|zygote|activitymanager|windowmanager|servicemanager)\b"],
    "hvac":       [r"\b(?:hvac|climate)\b"],
    "carservice": [r"\b(?:carservice|car.service|vehicleprop)\b"],
}
# pre-compile module patterns
_MOD_RE = {mod: re.compile("|".join(pats), re.IGNORECASE)
           for mod, pats in MODULES.items()}

# crash trigger patterns — compiled once
_CRASH_TRIGGERS = [
    (re.compile(r"FATAL EXCEPTION",                              re.I), "java_crash"),
    (re.compile(r"ANR in\s",                                     re.I), "anr"),
    (re.compile(r"Native crash|signal\s+\d+\s+\(SIG\w+\)",      re.I), "native_crash"),
    (re.compile(r"Kernel panic|kernel BUG at",                   re.I), "kernel_panic"),
    (re.compile(r"Watchdog.*KILLING|WATCHDOG\s",                 re.I), "watchdog"),
    (re.compile(r"FATAL EXCEPTION IN SYSTEM PROCESS",            re.I), "system_crash"),
    (re.compile(r"android\.os\.DeadObjectException",             re.I), "binder_death"),
]

# block-continuation keywords (set for O(1) lookup)
_BLOCK_KEEP = frozenset([
    "Exception", "Error", "Caused by", "signal", "fault addr",
    "backtrace", "  at ", "  #", "Reason:", "Process:", "PID:",
    "CPU:", "Load:", "TOTAL:", "pc ", "lr ", "sp ",
    "Abort message", "Build fingerprint", "Call trace",
])

_TS_RE      = re.compile(r"(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})")
_ROOT_RE    = re.compile(r"((?:[\w$]+\.)+(?:Exception|Error)):\s*(.*)", re.I)
_PACKAGE_RE = re.compile(r"Process:\s*([\w.]+),\s*PID:\s*(\d+)")
_SIGNAL_RE  = re.compile(r"signal\s+(\d+)\s+\((\w+)\)")

SEVERITY_MAP = {
    "java_crash":   ("FATAL",    C["fatal"]),
    "anr":          ("ANR",      C["anr"]),
    "native_crash": ("NATIVE",   C["native"]),
    "kernel_panic": ("KERNEL",   C["kernel"]),
    "watchdog":     ("WATCHDOG", C["watchdog"]),
    "system_crash": ("SYSTEM",   C["system"]),
    "binder_death": ("BINDER",   C["accent2"]),
    "unknown":      ("?",        C["unknown"]),
}
MODULE_COLORS = {
    "navigation": C["nav"],   "bluetooth": C["bt"],
    "media":      C["media"], "system":    C["sys_mod"],
    "hvac":       C["hvac"],  "carservice":C["accent3"],
    "unknown":    C["text3"],
}


@dataclass
class CrashEvent:
    idx:         int
    timestamp:   Optional[str]
    byte_offset: int            # position in file for on-demand re-read
    line_number: int
    module:      Optional[str]
    crash_type:  str
    root_cause:  str
    package:     Optional[str]
    pid:         Optional[str]
    signal:      Optional[str]
    stack_trace: List[str] = field(default_factory=list)
    # raw_block deliberately kept small — only top N lines
    raw_block:   str       = ""

    @property
    def severity(self):
        return SEVERITY_MAP.get(self.crash_type, SEVERITY_MAP["unknown"])


def _detect_module(text: str) -> Optional[str]:
    for mod, rx in _MOD_RE.items():
        if rx.search(text):
            return mod
    return None


def _line_has_block_kw(line: str) -> bool:
    """Fast check: does this line contain any block-continuation keyword?"""
    for kw in _BLOCK_KEEP:
        if kw in line:
            return True
    return False


class StreamingParser:
    """
    Single-pass streaming parser.  Never holds more than one window of lines
    in memory.  Yields CrashEvent objects as they are found.

    Strategy:
      - Read file line-by-line via a buffered iterator (8 MB buffer).
      - On crash trigger → collect up to MAX_BLOCK_LINES of stack context.
      - Throttle progress callback: fire at most once every PROG_INTERVAL bytes.
    """
    MAX_BLOCK_LINES  = 80          # max stack lines captured per event
    PROG_INTERVAL_B  = 4 * 1024 * 1024   # 4 MB between progress fires

    def __init__(self, filepath: Path, progress_cb=None, cancel_event=None):
        self.filepath    = filepath
        self.progress_cb = progress_cb
        self.cancel      = cancel_event or threading.Event()
        self.total_bytes = filepath.stat().st_size
        self.total_lines = 0
        self.file_size_mb = self.total_bytes / (1024 * 1024)

    def _iter_lines(self) -> Iterator[tuple]:
        """Yield (line_number, byte_offset, raw_line) with 8 MB read buffer."""
        byte_pos = 0
        line_no  = 0
        last_prog_byte = 0

        with open(self.filepath, "rb", buffering=8 * 1024 * 1024) as fh:
            for raw in fh:
                line_no  += 1
                offset    = byte_pos
                byte_pos += len(raw)

                # throttled progress
                if self.progress_cb and (byte_pos - last_prog_byte) >= self.PROG_INTERVAL_B:
                    self.progress_cb(byte_pos, self.total_bytes, line_no)
                    last_prog_byte = byte_pos

                line = raw.decode("utf-8", errors="replace")
                yield line_no, offset, line

        self.total_lines = line_no
        if self.progress_cb:
            self.progress_cb(self.total_bytes, self.total_bytes, line_no)

    def parse(self) -> List[CrashEvent]:
        events: List[CrashEvent] = []
        idx    = 1

        line_buf: List[tuple] = []   # sliding window: (lineno, offset, text)
        BUF_SIZE = 2                 # lines of look-ahead context before trigger

        # We use a small deque-style approach:
        # Keep a tiny pre-buffer so we have the anchor line available.
        # For the actual block, we collect inline.

        iter_lines = self._iter_lines()
        pending: List[tuple] = []    # lines already read but not yet consumed

        def next_line():
            if pending:
                return pending.pop(0)
            try:
                return next(iter_lines)
            except StopIteration:
                return None

        while True:
            if self.cancel.is_set():
                break

            item = next_line()
            if item is None:
                break

            lineno, offset, line = item

            # check for crash trigger
            ctype = None
            for rx, ct in _CRASH_TRIGGERS:
                if rx.search(line):
                    ctype = ct
                    break

            if ctype is None:
                continue

            # ── we have a crash anchor — collect block ──
            block_lines = [line.rstrip()]
            ts    = None
            m = _TS_RE.search(line)
            if m:
                ts = m.group(1)

            depth = 0
            for _ in range(self.MAX_BLOCK_LINES):
                if self.cancel.is_set():
                    break
                nxt = next_line()
                if nxt is None:
                    break
                nl, no, nline = nxt
                stripped = nline.rstrip()
                if not stripped.strip():
                    depth += 1
                    if depth >= 2:
                        pending.append(nxt)
                        break
                    block_lines.append("")
                    continue
                depth = 0
                if _line_has_block_kw(stripped):
                    block_lines.append(stripped)
                else:
                    pending.append(nxt)
                    break

            full_block = "\n".join(block_lines)

            # root cause
            root_cause = ""
            for ln in block_lines:
                m2 = _ROOT_RE.search(ln)
                if m2:
                    root_cause = f"{m2.group(1)}: {m2.group(2)[:120]}"
                    break
            if not root_cause:
                for ln in block_lines:
                    if any(k in ln for k in ("signal", "Reason:", "Abort message")):
                        root_cause = ln[:140]
                        break
            if not root_cause:
                root_cause = block_lines[0][:140]

            # package / pid
            pkg = pid = None
            for ln in block_lines:
                m3 = _PACKAGE_RE.search(ln)
                if m3:
                    pkg, pid = m3.group(1), m3.group(2)
                    break

            # signal
            sig = None
            for ln in block_lines:
                m4 = _SIGNAL_RE.search(ln)
                if m4:
                    sig = f"signal {m4.group(1)} ({m4.group(2)})"
                    break

            ev = CrashEvent(
                idx         = idx,
                timestamp   = ts,
                byte_offset = offset,
                line_number = lineno,
                module      = _detect_module(full_block),
                crash_type  = ctype,
                root_cause  = root_cause,
                package     = pkg,
                pid         = pid,
                signal      = sig,
                stack_trace = block_lines,
                raw_block   = full_block,
            )
            events.append(ev)
            idx += 1

        return events


# ──────────────────────────────────────────────────────────────────────────────
# STATS ACCUMULATOR (separate from parser — no coupling)
# ──────────────────────────────────────────────────────────────────────────────
class CrashStats:
    def __init__(self, events: List[CrashEvent]):
        self.module_stats     = defaultdict(int)
        self.crash_type_stats = defaultdict(int)
        for e in events:
            self.module_stats[e.module or "unknown"] += 1
            self.crash_type_stats[e.crash_type]      += 1


# ──────────────────────────────────────────────────────────────────────────────
# UI HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def _scrollbar(parent, orient, command):
    return tk.Scrollbar(
        parent, orient=orient, command=command,
        bg=C["bg3"], troughcolor=C["bg"], activebackground=C["accent"],
        width=10, relief="flat", bd=0, highlightthickness=0)


# ──────────────────────────────────────────────────────────────────────────────
# MAIN APPLICATION
# ──────────────────────────────────────────────────────────────────────────────
_BATCH = 200          # tree rows inserted per after() tick
_PROG_MS = 50         # minimum ms between UI progress refreshes

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Automotive Bugreport Analyzer  ·  Scale Edition v3")
        self.root.geometry("1440x880")
        self.root.configure(bg=C["bg"])
        self.root.minsize(1100, 700)

        self.filepath:  Optional[Path]   = None
        self.parser:    Optional[StreamingParser] = None
        self.crashes:   List[CrashEvent] = []
        self.filtered:  List[CrashEvent] = []
        self._cancel    = threading.Event()
        self._parse_thread: Optional[threading.Thread] = None

        # throttle for live progress redraws
        self._last_prog_ms = 0.0

        self._apply_style()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ──────────────────────────────────────────
    def _apply_style(self):
        s = ttk.Style()
        s.theme_use("clam")
        bg, bg2, bg3 = C["bg"], C["bg2"], C["bg3"]
        s.configure("TFrame",          background=bg)
        s.configure("TLabel",          background=bg,  foreground=C["text"],  font=FU)
        s.configure("TCombobox",
            fieldbackground=bg3, background=bg3, foreground=C["text"],
            selectbackground=C["accent"], selectforeground=bg,
            arrowcolor=C["accent"], bordercolor=C["border"],
            lightcolor=C["border"], darkcolor=C["border"])
        s.map("TCombobox",
            fieldbackground=[("readonly", bg3)],
            background=[("readonly", bg3)],
            foreground=[("readonly", C["text"])])
        for name, fg_, bg_, hover in [
            ("Accent",  C["bg"],     C["accent"],  "#33d6ff"),
            ("Danger",  "#fff",      C["accent2"], "#ff7080"),
            ("Ghost",   C["text2"],  C["bg3"],     C["border"]),
            ("Warning", C["bg"],     C["accent3"], "#ffd966"),
        ]:
            s.configure(f"{name}.TButton",
                background=bg_, foreground=fg_,
                font=FUb, relief="flat", borderwidth=0,
                focusthickness=0, padding=(12, 6))
            s.map(f"{name}.TButton",
                background=[("active", hover), ("pressed", bg_)],
                foreground=[("active", fg_)])
        s.configure("Treeview",
            background=bg2, fieldbackground=bg2,
            foreground=C["text"], font=FMs, rowheight=26, borderwidth=0)
        s.configure("Treeview.Heading",
            background=bg3, foreground=C["text2"],
            font=("Segoe UI", 9, "bold"), relief="flat", borderwidth=0)
        s.map("Treeview",
            background=[("selected", bg3)],
            foreground=[("selected", C["accent"])])
        s.configure("TProgressbar",
            troughcolor=bg3, background=C["accent"], thickness=5, borderwidth=0)
        s.configure("TNotebook",     background=bg3, borderwidth=0)
        s.configure("TNotebook.Tab",
            background=bg3, foreground=C["text3"],
            font=("Segoe UI", 9, "bold"), padding=(14, 6))
        s.map("TNotebook.Tab",
            background=[("selected", bg),  ("active", C["border"])],
            foreground=[("selected", C["accent"]), ("active", C["text"])])

    # ──────────────────────────────────────────
    def _build_ui(self):
        self._build_topbar()
        self._build_toolbar()
        self._build_progress_row()
        self._build_stats_row()
        self._build_panes()
        self._build_statusbar()

    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=C["bg"], height=52)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        cv = tk.Canvas(bar, width=10, height=10, bg=C["bg"], highlightthickness=0)
        cv.create_oval(0, 0, 10, 10, fill=C["accent"], outline="")
        cv.place(x=18, y=21)
        tk.Label(bar, text="AUTOMOTIVE BUGREPORT ANALYZER",
                 font=("Consolas", 13, "bold"), fg=C["accent"], bg=C["bg"]
                 ).place(x=36, y=13)
        tk.Label(bar, text="IVI  ·  ANDROID AUTOMOTIVE  ·  SCALE EDITION  ·  1M+ LINES",
                 font=("Consolas", 9), fg=C["text3"], bg=C["bg"]
                 ).place(x=38, y=33)
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=C["bg2"], height=50)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        ttk.Button(bar, text="⬆  OPEN FILE",  style="Accent.TButton",
                   command=self._open_file).pack(side="left", padx=(14,4), pady=9)
        ttk.Button(bar, text="▶  ANALYZE",    style="Accent.TButton",
                   command=self._start_analysis).pack(side="left", padx=4, pady=9)
        self._btn_cancel = ttk.Button(bar, text="⏹  CANCEL", style="Warning.TButton",
                   command=self._cancel_analysis, state="disabled")
        self._btn_cancel.pack(side="left", padx=4, pady=9)
        ttk.Button(bar, text="⬇  JSON",       style="Ghost.TButton",
                   command=self._export_json).pack(side="left", padx=4, pady=9)
        ttk.Button(bar, text="⬇  TXT",        style="Ghost.TButton",
                   command=self._export_txt).pack(side="left", padx=4, pady=9)
        ttk.Button(bar, text="✕  CLEAR",      style="Danger.TButton",
                   command=self._clear).pack(side="left", padx=(8,4), pady=9)

        tk.Frame(bar, bg=C["border"], width=1, height=32
                 ).pack(side="left", padx=10, pady=9)

        tk.Label(bar, text="MODULE", bg=C["bg2"], fg=C["text3"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(4,2))
        self._mod_var = tk.StringVar(value="all")
        cb1 = ttk.Combobox(bar, textvariable=self._mod_var, width=13,
                           state="readonly",
                           values=["all"] + list(MODULES.keys()))
        cb1.pack(side="left", padx=2, pady=9)
        cb1.bind("<<ComboboxSelected>>", lambda _: self._apply_filters())

        tk.Label(bar, text="TYPE", bg=C["bg2"], fg=C["text3"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(8,2))
        self._type_var = tk.StringVar(value="all")
        cb2 = ttk.Combobox(bar, textvariable=self._type_var, width=13,
                           state="readonly",
                           values=["all", "java_crash", "anr", "native_crash",
                                   "kernel_panic", "watchdog", "system_crash",
                                   "binder_death"])
        cb2.pack(side="left", padx=2, pady=9)
        cb2.bind("<<ComboboxSelected>>", lambda _: self._apply_filters())

        tk.Label(bar, text="🔍", bg=C["bg2"], fg=C["text2"],
                 font=("Segoe UI", 11)).pack(side="left", padx=(10,2))
        self._search_var = tk.StringVar()
        ent = tk.Entry(bar, textvariable=self._search_var,
                       bg=C["bg3"], fg=C["text"], insertbackground=C["accent"],
                       relief="flat", font=FU, width=24, highlightthickness=1,
                       highlightbackground=C["border"], highlightcolor=C["accent"])
        ent.pack(side="left", padx=4, ipady=5, pady=9)
        self._search_var.trace_add("write", lambda *_: self._apply_filters())

        self._file_lbl = tk.Label(bar, text="No file loaded",
                                  bg=C["bg2"], fg=C["text3"], font=("Consolas", 9))
        self._file_lbl.pack(side="right", padx=14)

        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")

    def _build_progress_row(self):
        row = tk.Frame(self.root, bg=C["bg2"], height=28)
        row.pack(fill="x")
        row.pack_propagate(False)

        self._prog_lbl = tk.Label(row, text="", bg=C["bg2"], fg=C["text3"],
                                  font=("Consolas", 9), anchor="w")
        self._prog_lbl.pack(side="left", padx=12, fill="y")

        self._prog_var = tk.DoubleVar(value=0)
        self._prog_bar = ttk.Progressbar(row, variable=self._prog_var,
                                         maximum=100, style="TProgressbar",
                                         length=300)
        self._prog_bar.pack(side="right", padx=12, pady=6)

        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")

    def _build_stats_row(self):
        frame = tk.Frame(self.root, bg=C["bg"], height=86)
        frame.pack(fill="x", padx=12, pady=(8, 4))
        frame.pack_propagate(False)
        self._sw = {}
        defs = [
            ("total",    "TOTAL",      C["accent"]),
            ("java",     "JAVA",       C["fatal"]),
            ("anr",      "ANR",        C["anr"]),
            ("native",   "NATIVE",     C["native"]),
            ("watchdog", "WATCHDOG",   C["watchdog"]),
            ("kernel",   "KERNEL",     C["kernel"]),
            ("binder",   "BINDER",     C["accent2"]),
            ("lines",    "LOG LINES",  C["text2"]),
            ("size",     "FILE SIZE",  C["text2"]),
        ]
        for key, label, color in defs:
            card = tk.Frame(frame, bg=C["panel"],
                            highlightbackground=C["border"], highlightthickness=1)
            card.pack(side="left", fill="both", expand=True, padx=2)
            v = tk.Label(card, text="—", fg=color, bg=C["panel"], font=FST)
            v.pack(pady=(6, 0))
            tk.Label(card, text=label, fg=C["text3"], bg=C["panel"],
                     font=("Segoe UI", 7, "bold")).pack(pady=(0, 5))
            self._sw[key] = v

    def _build_panes(self):
        pw = tk.PanedWindow(self.root, orient="horizontal",
                            bg=C["border"], sashwidth=4, sashrelief="flat")
        pw.pack(fill="both", expand=True)

        # ── LEFT ──────────────────────────────────────────
        left = tk.Frame(pw, bg=C["bg"])
        pw.add(left, minsize=460, width=530)

        hdr = tk.Frame(left, bg=C["bg3"], height=30)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="CRASH EVENTS", bg=C["bg3"], fg=C["text2"],
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=10, pady=5)
        self._count_lbl = tk.Label(hdr, text="0 events", bg=C["bg3"],
                                   fg=C["text3"], font=("Consolas", 9))
        self._count_lbl.pack(side="right", padx=10)

        tf = tk.Frame(left, bg=C["bg"])
        tf.pack(fill="both", expand=True)

        cols = ("#", "TS", "TYPE", "MODULE", "ROOT CAUSE")
        self._tree = ttk.Treeview(tf, columns=cols, show="headings",
                                  selectmode="browse")
        for col, w, anc in [
            ("#",          42,  "center"),
            ("TS",        128,  "w"),
            ("TYPE",       88,  "center"),
            ("MODULE",     88,  "center"),
            ("ROOT CAUSE", 300, "w"),
        ]:
            self._tree.heading(col, text=col, anchor=anc)
            self._tree.column(col, width=w, minwidth=max(40, w-20), anchor=anc)

        vsb = _scrollbar(tf, "vertical",   self._tree.yview)
        hsb = _scrollbar(tf, "horizontal", self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        for ct, (_, color) in SEVERITY_MAP.items():
            self._tree.tag_configure(ct, foreground=color)
        self._tree.tag_configure("odd",  background=C["bg2"])
        self._tree.tag_configure("even", background=C["bg"])

        # ── RIGHT ─────────────────────────────────────────
        right = tk.Frame(pw, bg=C["bg"])
        pw.add(right, minsize=360)

        self._nb = ttk.Notebook(right)
        self._nb.pack(fill="both", expand=True)

        self._tab_stack   = self._make_text_tab("  STACK TRACE  ")
        self._tab_summary = tk.Frame(self._nb, bg=C["bg"])
        self._nb.add(self._tab_summary, text="  SUMMARY  ")
        self._build_summary_tab()
        self._tab_raw   = self._make_text_tab("  RAW LOG  ")
        self._tab_stats = tk.Frame(self._nb, bg=C["bg"])
        self._nb.add(self._tab_stats, text="  STATISTICS  ")
        self._build_stats_viz_tab()

    def _make_text_tab(self, title: str) -> tk.Text:
        frame = tk.Frame(self._nb, bg=C["bg"])
        self._nb.add(frame, text=title)
        txt = tk.Text(
            frame, bg=C["bg2"], fg=C["text"],
            insertbackground=C["accent"], font=FM,
            wrap="none", relief="flat",
            selectbackground=C["bg3"], selectforeground=C["accent"],
            padx=12, pady=10, spacing1=2, spacing3=2, highlightthickness=0)
        vsb = _scrollbar(frame, "vertical",   txt.yview)
        hsb = _scrollbar(frame, "horizontal", txt.xview)
        txt.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        txt.pack(fill="both", expand=True)
        for tag, color in [
            ("fatal",   C["fatal"]),   ("anr",     C["anr"]),
            ("native",  C["native"]),  ("error",   C["accent2"]),
            ("warn",    C["accent3"]), ("info",    C["text2"]),
            ("frame",   C["text3"]),   ("package", C["accent"]),
            ("signal",  C["native"]),  ("key",     C["accent4"]),
            ("dim",     C["text3"]),   ("ok",      C["bt"]),
        ]:
            txt.tag_configure(tag, foreground=color)
        txt.config(state="disabled")
        return txt

    def _build_summary_tab(self):
        self._sum_vars = {}
        fields = [
            ("Crash #",     "idx"),
            ("Timestamp",   "timestamp"),
            ("Crash Type",  "crash_type"),
            ("Module",      "module"),
            ("Package",     "package"),
            ("PID",         "pid"),
            ("Signal",      "signal"),
            ("Line Number", "line_number"),
            ("Byte Offset", "byte_offset"),
        ]
        for i, (lbl, key) in enumerate(fields):
            bg = C["bg2"] if i % 2 else C["bg"]
            row = tk.Frame(self._tab_summary, bg=bg, height=30)
            row.pack(fill="x")
            row.pack_propagate(False)
            tk.Label(row, text=lbl, fg=C["text2"], bg=bg,
                     font=("Segoe UI", 9, "bold"), width=16, anchor="w"
                     ).pack(side="left", padx=(12, 0))
            var = tk.StringVar(value="—")
            tk.Label(row, textvariable=var, fg=C["accent"], bg=bg,
                     font=("Consolas", 9), anchor="w"
                     ).pack(side="left", padx=6)
            self._sum_vars[key] = var
        tk.Frame(self._tab_summary, bg=C["border"], height=1).pack(fill="x", pady=6)
        tk.Label(self._tab_summary, text="ROOT CAUSE", fg=C["text2"], bg=C["bg"],
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12)
        self._rc_txt = tk.Text(
            self._tab_summary, bg=C["bg3"], fg=C["fatal"],
            font=FM, wrap="word", height=5, relief="flat",
            padx=10, pady=8, highlightthickness=0, state="disabled")
        self._rc_txt.pack(fill="x", padx=10, pady=6)

    def _build_stats_viz_tab(self):
        canvas = tk.Canvas(self._tab_stats, bg=C["bg"], highlightthickness=0)
        vsb = _scrollbar(self._tab_stats, "vertical", canvas.yview)
        vsb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)
        inner = tk.Frame(canvas, bg=C["bg"])
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        self._stats_inner = inner

    def _build_statusbar(self):
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")
        bar = tk.Frame(self.root, bg=C["bg3"], height=24)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self._status_lbl = tk.Label(bar, text="  Ready", fg=C["text3"],
                                    bg=C["bg3"], font=("Consolas", 9), anchor="w")
        self._status_lbl.pack(side="left", fill="x", expand=True)
        tk.Label(bar, text="Scale Edition v3  ·  1M+ line support",
                 fg=C["text3"], bg=C["bg3"],
                 font=("Consolas", 9)).pack(side="right", padx=12)

    # ──────────────────────────────────────────
    # FILE / ANALYSIS LIFECYCLE
    # ──────────────────────────────────────────
    def _open_file(self):
        path = filedialog.askopenfilename(
            title="Open Bugreport",
            filetypes=[("Log / Bugreport", "*.txt *.log *.bugreport *.gz"),
                       ("All files", "*.*")])
        if not path:
            return
        self.filepath = Path(path)
        sz = self.filepath.stat().st_size / (1024 * 1024)
        self._file_lbl.config(text=f"  {self.filepath.name}  ({sz:.1f} MB)",
                               fg=C["text2"])
        self._status(f"Loaded: {self.filepath.name}  ({sz:.1f} MB)")
        self._sw["size"].config(text=f"{sz:.1f}M")

    def _start_analysis(self):
        if not self.filepath:
            messagebox.showwarning("No file", "Open a bugreport file first.")
            return
        self._clear_results()
        self._cancel.clear()
        self._btn_cancel.config(state="normal")
        self._status("Parsing…  (streaming)")
        self._prog_var.set(0)
        self._parse_thread = threading.Thread(
            target=self._parse_worker, daemon=True)
        self._parse_thread.start()

    def _parse_worker(self):
        t0 = time.perf_counter()
        try:
            parser = StreamingParser(
                self.filepath,
                progress_cb  = self._progress_cb,
                cancel_event = self._cancel,
            )
            crashes = parser.parse()
            elapsed = time.perf_counter() - t0
            self.parser  = parser
            self.crashes = crashes
            self.root.after(0, lambda: self._on_parse_done(elapsed))
        except Exception as exc:
            self.root.after(0, lambda: self._status(f"ERROR: {exc}"))
            self.root.after(0, lambda: self._btn_cancel.config(state="disabled"))

    def _progress_cb(self, done_bytes: int, total_bytes: int, line_no: int):
        """Called from parser thread — throttled to _PROG_MS."""
        now = time.monotonic() * 1000
        if (now - self._last_prog_ms) < _PROG_MS:
            return
        self._last_prog_ms = now
        pct  = (done_bytes / total_bytes * 100) if total_bytes else 0
        mb   = done_bytes / (1024 * 1024)
        tmb  = total_bytes / (1024 * 1024)
        msg  = f"  Parsing…  {mb:.0f} / {tmb:.0f} MB  |  line {line_no:,}"
        self.root.after(0, lambda: self._prog_var.set(pct))
        self.root.after(0, lambda: self._prog_lbl.config(text=msg))

    def _cancel_analysis(self):
        self._cancel.set()
        self._status("Cancelling…")
        self._btn_cancel.config(state="disabled")

    def _on_parse_done(self, elapsed: float):
        self._btn_cancel.config(state="disabled")
        self._prog_var.set(100)
        self.filtered = list(self.crashes)
        n  = len(self.crashes)
        ln = getattr(self.parser, "total_lines", 0)
        self._status(
            f"Done  ·  {n} crash events  ·  {ln:,} lines  ·  "
            f"{elapsed:.1f}s  ·  "
            f"{(ln/elapsed if elapsed else 0):,.0f} lines/sec")
        self._update_stat_cards()
        self._update_stats_viz()
        # batch-insert tree rows without blocking UI
        self._batch_populate(self.filtered, 0)

    # ──────────────────────────────────────────
    # TREE POPULATION — batched to keep UI alive
    # ──────────────────────────────────────────
    def _batch_populate(self, crashes: List[CrashEvent], start: int):
        end = min(start + _BATCH, len(crashes))
        for i in range(start, end):
            c = crashes[i]
            sev, _ = c.severity
            mod = (c.module or "—").upper()
            rc  = c.root_cause[:68] + ("…" if len(c.root_cause) > 68 else "")
            self._tree.insert(
                "", "end", iid=str(c.idx),
                values=(c.idx, c.timestamp or "—", sev, mod, rc),
                tags=(c.crash_type, "odd" if i % 2 else "even"))
        self._count_lbl.config(text=f"{len(crashes)} events")
        if end < len(crashes):
            self.root.after(0, lambda: self._batch_populate(crashes, end))
        else:
            self._prog_var.set(0)
            self._prog_lbl.config(text="")

    # ──────────────────────────────────────────
    # FILTERS
    # ──────────────────────────────────────────
    def _apply_filters(self):
        if not self.crashes:
            return
        mf = self._mod_var.get()
        tf = self._type_var.get()
        q  = self._search_var.get().strip().lower()

        result = [
            c for c in self.crashes
            if (mf == "all" or (c.module or "unknown") == mf)
            and (tf == "all" or c.crash_type == tf)
            and (not q
                 or q in c.root_cause.lower()
                 or q in (c.package or "").lower()
                 or q in c.raw_block.lower())
        ]
        self.filtered = result
        for row in self._tree.get_children():
            self._tree.delete(row)
        self._batch_populate(result, 0)

    # ──────────────────────────────────────────
    # SELECTION / DETAIL
    # ──────────────────────────────────────────
    def _on_select(self, _):
        sel = self._tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        c = next((x for x in self.crashes if x.idx == idx), None)
        if c:
            self._show_detail(c)

    def _show_detail(self, c: CrashEvent):
        # stack trace tab
        txt = self._tab_stack
        txt.config(state="normal")
        txt.delete("1.0", "end")
        txt.insert("end", f"{'─'*72}\n", "dim")
        txt.insert("end",
            f"  Crash #{c.idx}  ·  {c.timestamp or 'no ts'}  "
            f"·  Line {c.line_number:,}  ·  Byte {c.byte_offset:,}\n", "key")
        txt.insert("end", f"{'─'*72}\n\n", "dim")
        for line in c.stack_trace:
            if not line:
                txt.insert("end", "\n")
                continue
            if "FATAL" in line.upper():
                tag = "fatal"
            elif "ANR" in line or "Reason:" in line:
                tag = "anr"
            elif "signal" in line.lower() or "backtrace" in line.lower():
                tag = "signal"
            elif "at com." in line or "at android." in line or "  #" in line:
                tag = "frame"
            elif "Process:" in line or "PID:" in line:
                tag = "package"
            elif "Caused by" in line or "Exception" in line or "Error" in line:
                tag = "error"
            elif any(k in line for k in ("CPU:", "Load:", "TOTAL:")):
                tag = "warn"
            else:
                tag = "info"
            txt.insert("end", f"  {line}\n", tag)
        txt.config(state="disabled")

        # raw tab
        raw = self._tab_raw
        raw.config(state="normal")
        raw.delete("1.0", "end")
        raw.insert("end", c.raw_block)
        raw.config(state="disabled")

        # summary tab
        for key, var in self._sum_vars.items():
            val = getattr(c, key, "—")
            var.set(str(val) if val is not None else "—")
        self._rc_txt.config(state="normal")
        self._rc_txt.delete("1.0", "end")
        self._rc_txt.insert("end", c.root_cause)
        self._rc_txt.config(state="disabled")

    # ──────────────────────────────────────────
    # STATS
    # ──────────────────────────────────────────
    def _update_stat_cards(self):
        if not self.parser:
            return
        stats = CrashStats(self.crashes)
        ct = stats.crash_type_stats
        ln = getattr(self.parser, "total_lines", 0)
        sz = getattr(self.parser, "file_size_mb", 0)
        self._sw["total"].config(text=str(len(self.crashes)))
        self._sw["java"].config(text=str(ct.get("java_crash", 0)))
        self._sw["anr"].config(text=str(ct.get("anr", 0)))
        self._sw["native"].config(text=str(ct.get("native_crash", 0)))
        self._sw["watchdog"].config(text=str(ct.get("watchdog", 0)))
        self._sw["kernel"].config(text=str(ct.get("kernel_panic", 0)))
        self._sw["binder"].config(text=str(ct.get("binder_death", 0)))
        self._sw["lines"].config(text=f"{ln:,}" if ln else "—")
        self._sw["size"].config(text=f"{sz:.1f}M")

    def _update_stats_viz(self):
        for w in self._stats_inner.winfo_children():
            w.destroy()
        if not self.crashes:
            return
        stats = CrashStats(self.crashes)

        def bar_section(title, data: dict, color_fn):
            tk.Label(self._stats_inner, text=title, fg=C["accent"],
                     bg=C["bg"], font=("Consolas", 10, "bold")
                     ).pack(anchor="w", padx=14, pady=(14, 6))
            if not data:
                return
            mx = max(data.values(), default=1)
            for key, cnt in sorted(data.items(), key=lambda x: -x[1]):
                row = tk.Frame(self._stats_inner, bg=C["bg"])
                row.pack(fill="x", padx=14, pady=2)
                color = color_fn(key)
                tk.Label(row, text=f"{key:<18}", fg=color, bg=C["bg"],
                         font=("Consolas", 9)).pack(side="left")
                bw = max(4, int(220 * cnt / mx))
                tk.Frame(row, bg=color, width=bw, height=14).pack(side="left", padx=4)
                tk.Label(row, text=str(cnt), fg=color, bg=C["bg"],
                         font=("Consolas", 9, "bold")).pack(side="left", padx=4)

        bar_section("MODULE BREAKDOWN",
                    dict(stats.module_stats),
                    lambda k: MODULE_COLORS.get(k, C["text3"]))
        tk.Frame(self._stats_inner, bg=C["border"], height=1
                 ).pack(fill="x", padx=14, pady=8)
        bar_section("CRASH TYPE BREAKDOWN",
                    dict(stats.crash_type_stats),
                    lambda k: SEVERITY_MAP.get(k, ("", C["text3"]))[1])

    # ──────────────────────────────────────────
    # EXPORT — streaming, no full in-memory build
    # ──────────────────────────────────────────
    def _export_json(self):
        if not self.filtered:
            messagebox.showinfo("Nothing to export", "Run analysis first.")
            return
        out = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not out:
            return
        self._status("Exporting JSON…")
        def _worker():
            with open(out, "w", encoding="utf-8") as f:
                f.write("[\n")
                for i, c in enumerate(self.filtered):
                    sep = ",\n" if i < len(self.filtered) - 1 else "\n"
                    json.dump({
                        "idx": c.idx, "timestamp": c.timestamp,
                        "line_number": c.line_number, "byte_offset": c.byte_offset,
                        "module": c.module, "crash_type": c.crash_type,
                        "root_cause": c.root_cause, "package": c.package,
                        "pid": c.pid, "signal": c.signal,
                        "stack_trace": c.stack_trace,
                    }, f)
                    f.write(sep)
                f.write("]\n")
            self.root.after(0, lambda: self._status(
                f"Exported {len(self.filtered)} events → {out}"))
        threading.Thread(target=_worker, daemon=True).start()

    def _export_txt(self):
        if not self.filtered:
            messagebox.showinfo("Nothing to export", "Run analysis first.")
            return
        out = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if not out:
            return
        self._status("Exporting TXT…")
        def _worker():
            with open(out, "w", encoding="utf-8") as f:
                f.write(f"AUTOMOTIVE BUGREPORT ANALYSIS REPORT\n")
                f.write(f"Source    : {self.filepath}\n")
                f.write(f"Crashes   : {len(self.filtered)}\n")
                f.write(f"Log lines : {getattr(self.parser,'total_lines',0):,}\n")
                f.write("=" * 80 + "\n\n")
                for c in self.filtered:
                    sev, _ = c.severity
                    f.write(f"{'='*80}\n")
                    f.write(f"Crash #{c.idx}  [{sev}]  Line {c.line_number:,}  Byte {c.byte_offset:,}\n")
                    f.write(f"Timestamp  : {c.timestamp or '—'}\n")
                    f.write(f"Module     : {c.module or '—'}\n")
                    f.write(f"Type       : {c.crash_type}\n")
                    f.write(f"Package    : {c.package or '—'}\n")
                    f.write(f"Signal     : {c.signal or '—'}\n")
                    f.write(f"Root Cause : {c.root_cause}\n")
                    f.write("Stack:\n")
                    for s in c.stack_trace:
                        f.write(f"  {s}\n")
                    f.write("\n")
            self.root.after(0, lambda: self._status(
                f"Exported {len(self.filtered)} events → {out}"))
        threading.Thread(target=_worker, daemon=True).start()

    # ──────────────────────────────────────────
    # CLEAR / CLOSE
    # ──────────────────────────────────────────
    def _clear(self):
        self._cancel_analysis()
        self._clear_results()
        self.filepath = None
        self._file_lbl.config(text="No file loaded", fg=C["text3"])
        self._status("Cleared")

    def _clear_results(self):
        self.crashes  = []
        self.filtered = []
        self.parser   = None
        for row in self._tree.get_children():
            self._tree.delete(row)
        for k in self._sw:
            self._sw[k].config(text="—")
        for txt in (self._tab_stack, self._tab_raw):
            txt.config(state="normal")
            txt.delete("1.0", "end")
            txt.config(state="disabled")
        self._rc_txt.config(state="normal")
        self._rc_txt.delete("1.0", "end")
        self._rc_txt.config(state="disabled")
        for v in self._sum_vars.values():
            v.set("—")
        for w in self._stats_inner.winfo_children():
            w.destroy()
        self._count_lbl.config(text="0 events")
        self._prog_var.set(0)
        self._prog_lbl.config(text="")

    def _on_close(self):
        self._cancel.set()
        self.root.destroy()

    def _status(self, msg: str):
        self._status_lbl.config(text=f"  {msg}")


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
