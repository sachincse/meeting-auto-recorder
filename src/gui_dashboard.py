"""Tkinter GUI dashboard — accessible via hotkey or tray menu."""

import asyncio
import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime, timezone
from tkinter import ttk, filedialog
from typing import Optional

logger = logging.getLogger(__name__)

_root: Optional[tk.Tk] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_scheduler = None
_gui_thread: Optional[threading.Thread] = None


def _run_async(coro):
    if not _loop or not _loop.is_running():
        return None
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    try:
        return future.result(timeout=15)
    except Exception:
        return None


def _open_path(path: str):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class DashboardApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Meeting Auto-Recorder")
        root.geometry("960x620")
        root.minsize(750, 500)
        root.resizable(True, True)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style()
        style.theme_use("clam" if sys.platform != "darwin" else "aqua")
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 9))
        style.configure("TLabelframe.Label", font=("Segoe UI", 9, "bold"))
        style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Record.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Stop.TButton", font=("Segoe UI", 10, "bold"))

        # ── Top control bar ───────────────────────────────────────────
        top = ttk.Frame(root, padding=(12, 8))
        top.pack(fill=tk.X)

        self._status_label = ttk.Label(top, text="Idle — monitoring emails",
                                        style="Status.TLabel", foreground="#2d8a4e")
        self._status_label.pack(side=tk.LEFT)

        # Single Start/Stop button (context-aware)
        self._action_btn = ttk.Button(top, text="Start Recording",
                                       style="Record.TButton", command=self._toggle_recording)
        self._action_btn.pack(side=tk.RIGHT, padx=(10, 0))

        ttk.Separator(root, orient=tk.HORIZONTAL).pack(fill=tk.X)

        # ── Notebook ──────────────────────────────────────────────────
        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 10))
        notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)

        self._build_upcoming_tab(notebook)
        self._build_schedule_tab(notebook)
        self._build_settings_tab(notebook)
        self._build_history_tab(notebook)

        # Initial data load in background (non-blocking)
        self.root.after(500, self._refresh_upcoming)
        self.root.after(600, self._refresh_history)
        self._poll_status()

    # ── Recording toggle (single button) ──────────────────────────────

    def _toggle_recording(self):
        from src.meeting_recorder import get_active_recorder
        rec = get_active_recorder()
        if rec and rec.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        from src.meeting_recorder import MeetingRecorder, set_active_recorder, get_active_recorder
        if get_active_recorder() and get_active_recorder().is_recording:
            return
        recorder = MeetingRecorder(meeting_url="", subject="Manual Recording")
        set_active_recorder(recorder)
        recorder.start_recording()
        try:
            from src.tray_app import update_tray_icon
            update_tray_icon(recording=True)
        except Exception:
            pass
        logger.info("Manual recording started from GUI")
        self._update_status_ui()

    def _stop_recording(self):
        from src.meeting_recorder import get_active_recorder, set_active_recorder
        rec = get_active_recorder()
        if rec and rec.is_recording:
            result = rec.stop_recording()
            set_active_recorder(None)
            logger.info(f"Recording stopped: {result.get('session_folder', '?')}")
            try:
                from src.tray_app import update_tray_icon
                update_tray_icon(recording=False)
            except Exception:
                pass
        self._update_status_ui()
        self._refresh_history()

    def _poll_status(self):
        self._update_status_ui()
        self.root.after(3000, self._poll_status)

    def _update_status_ui(self):
        from src.meeting_recorder import get_active_recorder
        rec = get_active_recorder()
        if rec and rec.is_recording:
            self._status_label.config(text=f"RECORDING: {rec.subject}", foreground="#c0392b")
            self._action_btn.config(text="Stop Recording", style="Stop.TButton")
        else:
            self._status_label.config(text="Idle — monitoring emails", foreground="#2d8a4e")
            self._action_btn.config(text="Start Recording", style="Record.TButton")

    # ── Tab switch handler ────────────────────────────────────────────

    def _on_tab_change(self, event):
        tab_name = event.widget.tab(event.widget.select(), "text").strip()
        if "Upcoming" in tab_name:
            self.root.after(100, self._refresh_upcoming)
        elif "History" in tab_name:
            self.root.after(100, self._refresh_history)

    # ── Tab 1: Upcoming Meetings ──────────────────────────────────────

    def _build_upcoming_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=5)
        notebook.add(frame, text="  Upcoming Meetings  ")

        self._stats_label = ttk.Label(frame, text="", font=("Segoe UI", 9))
        self._stats_label.pack(anchor="w", pady=(0, 4))

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("subject", "start", "duration", "status", "source")
        self._upcoming_tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
        for col, w in [("subject", 260), ("start", 170), ("duration", 80), ("status", 90), ("source", 80)]:
            self._upcoming_tree.heading(col, text=col.title())
            self._upcoming_tree.column(col, width=w, minwidth=60)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._upcoming_tree.yview)
        self._upcoming_tree.configure(yscrollcommand=vsb.set)
        self._upcoming_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        btn = ttk.Frame(frame)
        btn.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn, text="Refresh", command=self._refresh_upcoming).pack(side=tk.LEFT)
        ttk.Button(btn, text="Scan Emails Now", command=self._scan_now).pack(side=tk.LEFT, padx=8)

        self.root.after(60000, self._auto_refresh)

    def _refresh_upcoming(self):
        from src.meeting_scheduler import get_upcoming_meetings, get_meeting_stats
        meetings = _run_async(get_upcoming_meetings()) or []
        stats = _run_async(get_meeting_stats()) or {}
        self._stats_label.config(
            text=f"Total: {stats.get('total', 0)}    Scheduled: {stats.get('scheduled', 0)}    "
                 f"Recorded: {stats.get('recorded', 0)}    Failed: {stats.get('failed', 0)}"
        )
        self._upcoming_tree.delete(*self._upcoming_tree.get_children())
        for m in meetings:
            dur = f"{(m.get('duration_seconds', 0) or 0) // 60} min"
            self._upcoming_tree.insert("", tk.END, values=(
                m.get("subject", "?"), m.get("start_time", "?"),
                dur, m.get("status", "?"), m.get("source", "?"),
            ))

    def _scan_now(self):
        if not _scheduler:
            return
        from src.meeting_scheduler import scan_emails_and_schedule
        _run_async(scan_emails_and_schedule(_scheduler))
        self._refresh_upcoming()

    def _auto_refresh(self):
        self._refresh_upcoming()
        self.root.after(60000, self._auto_refresh)

    # ── Tab 2: Schedule ───────────────────────────────────────────────

    def _build_schedule_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="  Schedule  ")

        form = ttk.LabelFrame(frame, text="Schedule a Future Recording", padding=10)
        form.pack(fill=tk.X)

        labels = ["Subject:", "Date (YYYY-MM-DD):", "Time (HH:MM):", "Duration (min):"]
        for i, lbl in enumerate(labels):
            ttk.Label(form, text=lbl).grid(row=i, column=0, sticky="w", padx=(0, 8), pady=4)

        self._sched_subject = ttk.Entry(form, width=40)
        self._sched_subject.insert(0, "Meeting")
        self._sched_subject.grid(row=0, column=1, sticky="ew", pady=4)

        self._sched_date = ttk.Entry(form, width=14)
        self._sched_date.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self._sched_date.grid(row=1, column=1, sticky="w", pady=4)

        self._sched_time = ttk.Entry(form, width=8)
        self._sched_time.insert(0, datetime.now().strftime("%H:%M"))
        self._sched_time.grid(row=2, column=1, sticky="w", pady=4)

        self._sched_dur = ttk.Spinbox(form, from_=5, to=240, width=6, increment=5)
        self._sched_dur.set(45)
        self._sched_dur.grid(row=3, column=1, sticky="w", pady=4)

        form.columnconfigure(1, weight=1)

        ttk.Button(frame, text="Schedule Recording", command=self._do_schedule).pack(anchor="w", pady=(10, 0))

        ttk.Label(frame, text="Tip: Use the Start Recording button in the top bar for immediate recording.",
                  foreground="gray", font=("Segoe UI", 8)).pack(anchor="w", pady=(20, 0))

    def _do_schedule(self):
        if not _scheduler:
            return
        subject = self._sched_subject.get().strip() or "Meeting"
        try:
            dt = f"{self._sched_date.get().strip()} {self._sched_time.get().strip()}"
            start = datetime.strptime(dt, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).astimezone()
        except ValueError:
            return
        dur = int(self._sched_dur.get())
        from src.meeting_scheduler import schedule_manual_meeting
        _run_async(schedule_manual_meeting(_scheduler, "", subject, start, dur))
        self._refresh_upcoming()

    # ── Tab 3: Settings ───────────────────────────────────────────────

    def _build_settings_tab(self, notebook):
        outer = ttk.Frame(notebook)
        notebook.add(outer, text="  Settings  ")

        # Scrollable canvas
        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas, padding=10)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw", tags="inner")
        canvas.configure(yscrollcommand=vsb.set)

        # Make inner frame stretch to canvas width
        def _resize_inner(event):
            canvas.itemconfig("inner", width=event.width)
        canvas.bind("<Configure>", _resize_inner)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # ── Audio Devices ──
        dev = ttk.LabelFrame(inner, text="Audio Devices", padding=10)
        dev.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(dev, text="Microphone:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        self._mic_combo = ttk.Combobox(dev, state="readonly")
        self._mic_combo.grid(row=0, column=1, sticky="ew", pady=3)

        ttk.Label(dev, text="Speaker:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        self._spk_combo = ttk.Combobox(dev, state="readonly")
        self._spk_combo.grid(row=1, column=1, sticky="ew", pady=3)

        dev.columnconfigure(1, weight=1)

        dbtn = ttk.Frame(dev)
        dbtn.grid(row=2, column=0, columnspan=2, pady=(6, 0))
        ttk.Button(dbtn, text="Refresh Devices", command=self._refresh_devices).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(dbtn, text="Reset to Auto-Detect", command=self._reset_devices).pack(side=tk.LEFT)

        # ── Output Path ──
        pathf = ttk.LabelFrame(inner, text="Recording Output", padding=10)
        pathf.pack(fill=tk.X, pady=(0, 10))

        from src.config import get_recording_config
        self._output_var = tk.StringVar(value=get_recording_config()["output_dir"])

        prow = ttk.Frame(pathf)
        prow.pack(fill=tk.X)
        ttk.Entry(prow, textvariable=self._output_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(prow, text="Browse", command=self._browse_output).pack(side=tk.LEFT)

        # ── Notifications ──
        notf = ttk.LabelFrame(inner, text="Notifications", padding=10)
        notf.pack(fill=tk.X, pady=(0, 10))

        from src.config import load_user_prefs
        nprefs = load_user_prefs().get("notifications", {})

        self._notif_enabled = tk.BooleanVar(value=nprefs.get("enabled", True))
        self._notif_on_start = tk.BooleanVar(value=nprefs.get("on_start", False))
        self._notif_on_stop = tk.BooleanVar(value=nprefs.get("on_stop", False))

        ttk.Checkbutton(notf, text="Enable desktop notifications",
                        variable=self._notif_enabled).pack(anchor="w", pady=2)
        ttk.Checkbutton(notf, text="Notify when recording starts (may interrupt screenshare — off by default)",
                        variable=self._notif_on_start).pack(anchor="w", pady=2)
        ttk.Checkbutton(notf, text="Notify when recording stops (may interrupt screenshare — off by default)",
                        variable=self._notif_on_stop).pack(anchor="w", pady=2)

        ttk.Label(notf, text="Start/stop notifications are disabled by default so they don't appear during meetings.",
                  foreground="gray", font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 0))

        # ── Save ──
        ttk.Button(inner, text="Save Settings", command=self._save_settings).pack(anchor="w", pady=(6, 0))

        self._refresh_devices()

    def _refresh_devices(self):
        from src.meeting_recorder import list_audio_devices
        devices = list_audio_devices()
        self._mic_devices = devices.get("microphones", [])
        self._spk_devices = devices.get("speakers", [])

        self._mic_combo["values"] = ["Auto-Detect"] + [f"[{d['index']}] {d['name']}" for d in self._mic_devices]
        self._spk_combo["values"] = ["Auto-Detect (WASAPI Loopback)"] + [f"[{d['index']}] {d['name']}" for d in self._spk_devices]
        self._mic_combo.current(0)
        self._spk_combo.current(0)

        from src.config import get_device_config
        dev = get_device_config()
        if dev.get("mic_index") is not None:
            for i, m in enumerate(self._mic_devices):
                if m["index"] == dev["mic_index"]:
                    self._mic_combo.current(i + 1)
                    break
        if dev.get("speaker_index") is not None:
            for i, s in enumerate(self._spk_devices):
                if s["index"] == dev["speaker_index"]:
                    self._spk_combo.current(i + 1)
                    break

    def _reset_devices(self):
        self._mic_combo.current(0)
        self._spk_combo.current(0)

    def _browse_output(self):
        path = filedialog.askdirectory(initialdir=self._output_var.get())
        if path:
            self._output_var.set(path)

    def _save_settings(self):
        from src.config import save_user_prefs
        mic_sel = self._mic_combo.current()
        spk_sel = self._spk_combo.current()
        prefs = {
            "devices": {
                "mic_index": self._mic_devices[mic_sel - 1]["index"] if mic_sel > 0 else None,
                "speaker_index": self._spk_devices[spk_sel - 1]["index"] if spk_sel > 0 else None,
            },
            "recording": {"output_dir": self._output_var.get()},
            "notifications": {
                "enabled": self._notif_enabled.get(),
                "on_start": self._notif_on_start.get(),
                "on_stop": self._notif_on_stop.get(),
            },
        }
        save_user_prefs(prefs)
        logger.info("Settings saved from GUI")

    # ── Tab 4: History ────────────────────────────────────────────────

    def _build_history_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=5)
        notebook.add(frame, text="  History  ")

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("subject", "start", "duration", "status", "path")
        self._history_tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
        for col, w in [("subject", 220), ("start", 160), ("duration", 70), ("status", 80), ("path", 280)]:
            self._history_tree.heading(col, text=col.replace("path", "Recording Path").title())
            self._history_tree.column(col, width=w, minwidth=50)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._history_tree.yview)
        self._history_tree.configure(yscrollcommand=vsb.set)
        self._history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._history_tree.bind("<Double-1>", self._open_recording)

        ttk.Label(frame, text="Double-click a row to open the recording folder.",
                  foreground="gray", font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 0))

    def _refresh_history(self):
        from src.meeting_scheduler import get_meeting_history
        history = _run_async(get_meeting_history(100)) or []
        self._history_tree.delete(*self._history_tree.get_children())
        for m in history:
            dur = f"{(m.get('duration_seconds', 0) or 0) // 60} min"
            self._history_tree.insert("", tk.END, values=(
                m.get("subject", "?"), m.get("start_time", "?"),
                dur, m.get("status", "?"), m.get("recording_path", ""),
            ))

    def _open_recording(self, event):
        sel = self._history_tree.selection()
        if not sel:
            return
        values = self._history_tree.item(sel[0], "values")
        path = values[4] if len(values) > 4 else ""
        if path and os.path.isdir(path):
            _open_path(path)

    # ── Window ────────────────────────────────────────────────────────

    def _on_close(self):
        self.root.withdraw()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self):
        self.root.withdraw()

    def toggle(self):
        if self.root.winfo_viewable():
            self.hide()
        else:
            self.show()


# ── Module API ────────────────────────────────────────────────────────

_app: Optional[DashboardApp] = None


def _gui_thread_main():
    global _root, _app
    _root = tk.Tk()
    _root.withdraw()
    _app = DashboardApp(_root)
    _root.mainloop()


def init_dashboard(event_loop: asyncio.AbstractEventLoop, scheduler=None):
    global _loop, _scheduler, _gui_thread
    _loop = event_loop
    _scheduler = scheduler
    _gui_thread = threading.Thread(target=_gui_thread_main, daemon=True)
    _gui_thread.start()


def toggle_dashboard():
    if _root and _app:
        _root.after(0, _app.toggle)


def show_dashboard():
    if _root and _app:
        _root.after(0, _app.show)
