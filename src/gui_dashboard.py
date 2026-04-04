"""Tkinter GUI dashboard — accessible via hotkey or tray menu."""

import asyncio
import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime, timezone
from tkinter import ttk, filedialog, messagebox
from typing import Optional

logger = logging.getLogger(__name__)

_root: Optional[tk.Tk] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_scheduler = None  # APScheduler reference
_gui_thread: Optional[threading.Thread] = None


def _run_async(coro):
    """Run an async coroutine from the GUI thread and return the result."""
    if not _loop or not _loop.is_running():
        return None
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    try:
        return future.result(timeout=15)
    except Exception:
        return None


def _open_path(path: str):
    """Cross-platform open folder/file."""
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
        root.geometry("780x520")
        root.resizable(True, True)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style()
        style.theme_use("clam" if sys.platform != "darwin" else "aqua")

        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self._build_upcoming_tab(notebook)
        self._build_record_tab(notebook)
        self._build_settings_tab(notebook)
        self._build_history_tab(notebook)

        self._refresh_upcoming()
        self._refresh_history()

    # ── Tab 1: Upcoming Meetings ──────────────────────────────────────

    def _build_upcoming_tab(self, notebook):
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  Upcoming Meetings  ")

        # Stats bar
        self._stats_label = ttk.Label(frame, text="Loading...", font=("Segoe UI", 10))
        self._stats_label.pack(anchor="w", padx=10, pady=(10, 0))

        # Treeview
        cols = ("subject", "start", "duration", "status", "source")
        self._upcoming_tree = ttk.Treeview(frame, columns=cols, show="headings", height=12)
        self._upcoming_tree.heading("subject", text="Subject")
        self._upcoming_tree.heading("start", text="Start Time")
        self._upcoming_tree.heading("duration", text="Duration")
        self._upcoming_tree.heading("status", text="Status")
        self._upcoming_tree.heading("source", text="Source")
        self._upcoming_tree.column("subject", width=250)
        self._upcoming_tree.column("start", width=170)
        self._upcoming_tree.column("duration", width=80)
        self._upcoming_tree.column("status", width=90)
        self._upcoming_tree.column("source", width=80)
        self._upcoming_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="Refresh", command=self._refresh_upcoming).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Scan Emails Now", command=self._scan_now).pack(side=tk.LEFT, padx=5)

        # Active recording indicator
        self._active_label = ttk.Label(frame, text="", foreground="red", font=("Segoe UI", 10, "bold"))
        self._active_label.pack(anchor="w", padx=10)

        self.root.after(30000, self._auto_refresh)

    def _refresh_upcoming(self):
        from src.meeting_scheduler import get_upcoming_meetings, get_meeting_stats
        meetings = _run_async(get_upcoming_meetings()) or []
        stats = _run_async(get_meeting_stats()) or {}

        self._stats_label.config(
            text=f"Total: {stats.get('total', 0)}  |  "
                 f"Scheduled: {stats.get('scheduled', 0)}  |  "
                 f"Recorded: {stats.get('recorded', 0)}  |  "
                 f"Failed: {stats.get('failed', 0)}"
        )

        self._upcoming_tree.delete(*self._upcoming_tree.get_children())
        for m in meetings:
            dur = f"{(m.get('duration_seconds', 0) or 0) // 60} min"
            self._upcoming_tree.insert("", tk.END, values=(
                m.get("subject", "?"),
                m.get("start_time", "?"),
                dur,
                m.get("status", "?"),
                m.get("source", "?"),
            ))

        # Active recording
        from src.meeting_recorder import get_active_recorder
        rec = get_active_recorder()
        if rec and rec.is_recording:
            self._active_label.config(text=f"RECORDING: {rec.subject}")
        else:
            self._active_label.config(text="")

    def _scan_now(self):
        if not _scheduler:
            messagebox.showwarning("Not Running", "Scheduler not running. Start with --tray or --schedule.")
            return
        from src.meeting_scheduler import scan_emails_and_schedule
        count = _run_async(scan_emails_and_schedule(_scheduler))
        self._refresh_upcoming()
        messagebox.showinfo("Scan Complete", f"Found {count or 0} new meeting(s).")

    def _auto_refresh(self):
        self._refresh_upcoming()
        self.root.after(30000, self._auto_refresh)

    # ── Tab 2: Record Now / Schedule ──────────────────────────────────

    def _build_record_tab(self, notebook):
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  Record / Schedule  ")

        form = ttk.LabelFrame(frame, text="Schedule a Recording")
        form.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(form, text="Meeting URL:").grid(row=0, column=0, sticky="w", padx=5, pady=3)
        self._rec_url = ttk.Entry(form, width=50)
        self._rec_url.grid(row=0, column=1, columnspan=2, padx=5, pady=3, sticky="ew")

        ttk.Label(form, text="Subject:").grid(row=1, column=0, sticky="w", padx=5, pady=3)
        self._rec_subject = ttk.Entry(form, width=50)
        self._rec_subject.insert(0, "Meeting")
        self._rec_subject.grid(row=1, column=1, columnspan=2, padx=5, pady=3, sticky="ew")

        ttk.Label(form, text="Date (YYYY-MM-DD):").grid(row=2, column=0, sticky="w", padx=5, pady=3)
        self._rec_date = ttk.Entry(form, width=15)
        self._rec_date.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self._rec_date.grid(row=2, column=1, padx=5, pady=3, sticky="w")

        ttk.Label(form, text="Time (HH:MM):").grid(row=3, column=0, sticky="w", padx=5, pady=3)
        self._rec_time = ttk.Entry(form, width=10)
        self._rec_time.insert(0, datetime.now().strftime("%H:%M"))
        self._rec_time.grid(row=3, column=1, padx=5, pady=3, sticky="w")

        ttk.Label(form, text="Duration (min):").grid(row=4, column=0, sticky="w", padx=5, pady=3)
        self._rec_dur = ttk.Spinbox(form, from_=5, to=240, width=8, increment=5)
        self._rec_dur.set(45)
        self._rec_dur.grid(row=4, column=1, padx=5, pady=3, sticky="w")

        form.columnconfigure(1, weight=1)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(btn_frame, text="Schedule Recording", command=self._schedule_meeting).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Record Now", command=self._record_now).pack(side=tk.LEFT, padx=10)

        # Stop button
        self._stop_btn = ttk.Button(btn_frame, text="Stop Current Recording", command=self._stop_recording)
        self._stop_btn.pack(side=tk.RIGHT)

    def _schedule_meeting(self):
        if not _scheduler:
            messagebox.showwarning("Not Running", "Scheduler not running.")
            return
        url = self._rec_url.get().strip()
        subject = self._rec_subject.get().strip() or "Meeting"
        if not url:
            messagebox.showwarning("Missing URL", "Please enter a meeting URL.")
            return
        try:
            dt_str = f"{self._rec_date.get().strip()} {self._rec_time.get().strip()}"
            start = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            start = start.replace(tzinfo=timezone.utc).astimezone()
        except ValueError:
            messagebox.showerror("Invalid Date/Time", "Use YYYY-MM-DD and HH:MM format.")
            return
        dur = int(self._rec_dur.get())

        from src.meeting_scheduler import schedule_manual_meeting
        mid = _run_async(schedule_manual_meeting(_scheduler, url, subject, start, dur))
        self._refresh_upcoming()
        messagebox.showinfo("Scheduled", f"Meeting scheduled (#{mid}). Recording will start automatically.")

    def _record_now(self):
        url = self._rec_url.get().strip()
        subject = self._rec_subject.get().strip() or "Meeting"
        dur = int(self._rec_dur.get()) * 60
        if not url:
            messagebox.showwarning("Missing URL", "Please enter a meeting URL.")
            return
        from src.meeting_recorder import record_meeting_now
        if _loop:
            asyncio.run_coroutine_threadsafe(record_meeting_now(url, subject, dur), _loop)
            messagebox.showinfo("Recording", f"Recording started for {dur // 60} min.")

    def _stop_recording(self):
        from src.meeting_recorder import get_active_recorder
        rec = get_active_recorder()
        if rec and rec.is_recording:
            rec.stop_recording()
            messagebox.showinfo("Stopped", "Recording stopped.")
            self._refresh_upcoming()
        else:
            messagebox.showinfo("No Recording", "No active recording.")

    # ── Tab 3: Settings ───────────────────────────────────────────────

    def _build_settings_tab(self, notebook):
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  Settings  ")

        # Audio devices
        dev_frame = ttk.LabelFrame(frame, text="Audio Devices")
        dev_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(dev_frame, text="Microphone:").grid(row=0, column=0, sticky="w", padx=5, pady=3)
        self._mic_combo = ttk.Combobox(dev_frame, state="readonly", width=50)
        self._mic_combo.grid(row=0, column=1, padx=5, pady=3, sticky="ew")

        ttk.Label(dev_frame, text="Speaker:").grid(row=1, column=0, sticky="w", padx=5, pady=3)
        self._spk_combo = ttk.Combobox(dev_frame, state="readonly", width=50)
        self._spk_combo.grid(row=1, column=1, padx=5, pady=3, sticky="ew")

        dev_btn_frame = ttk.Frame(dev_frame)
        dev_btn_frame.grid(row=2, column=0, columnspan=2, pady=5)
        ttk.Button(dev_btn_frame, text="Refresh Devices", command=self._refresh_devices).pack(side=tk.LEFT, padx=5)
        ttk.Button(dev_btn_frame, text="Reset to Auto-Detect", command=self._reset_devices).pack(side=tk.LEFT, padx=5)

        dev_frame.columnconfigure(1, weight=1)

        # Output path
        path_frame = ttk.LabelFrame(frame, text="Recording Output")
        path_frame.pack(fill=tk.X, padx=10, pady=5)

        from src.config import get_recording_config
        self._output_path_var = tk.StringVar(value=get_recording_config()["output_dir"])
        ttk.Entry(path_frame, textvariable=self._output_path_var, width=60).pack(side=tk.LEFT, padx=5, pady=5, fill=tk.X, expand=True)
        ttk.Button(path_frame, text="Browse", command=self._browse_output).pack(side=tk.LEFT, padx=5, pady=5)

        # Save
        ttk.Button(frame, text="Save Settings", command=self._save_settings).pack(padx=10, pady=10, anchor="w")

        self._refresh_devices()

    def _refresh_devices(self):
        from src.meeting_recorder import list_audio_devices
        devices = list_audio_devices()
        mics = devices.get("microphones", [])
        spks = devices.get("speakers", [])

        self._mic_devices = mics
        self._spk_devices = spks

        mic_names = ["Auto-Detect"] + [f"[{d['index']}] {d['name']}" for d in mics]
        spk_names = ["Auto-Detect (WASAPI Loopback)"] + [f"[{d['index']}] {d['name']}" for d in spks]

        self._mic_combo["values"] = mic_names
        self._spk_combo["values"] = spk_names
        self._mic_combo.current(0)
        self._spk_combo.current(0)

        # Select current device from config
        from src.config import get_device_config
        dev = get_device_config()
        if dev.get("mic_index") is not None:
            for i, m in enumerate(mics):
                if m["index"] == dev["mic_index"]:
                    self._mic_combo.current(i + 1)
                    break
        if dev.get("speaker_index") is not None:
            for i, s in enumerate(spks):
                if s["index"] == dev["speaker_index"]:
                    self._spk_combo.current(i + 1)
                    break

    def _reset_devices(self):
        self._mic_combo.current(0)
        self._spk_combo.current(0)

    def _browse_output(self):
        path = filedialog.askdirectory(initialdir=self._output_path_var.get())
        if path:
            self._output_path_var.set(path)

    def _save_settings(self):
        from src.config import save_user_prefs
        prefs = {}

        # Devices
        mic_sel = self._mic_combo.current()
        spk_sel = self._spk_combo.current()
        devices = {}
        if mic_sel > 0:
            devices["mic_index"] = self._mic_devices[mic_sel - 1]["index"]
        else:
            devices["mic_index"] = None
        if spk_sel > 0:
            devices["speaker_index"] = self._spk_devices[spk_sel - 1]["index"]
        else:
            devices["speaker_index"] = None
        prefs["devices"] = devices

        # Output path
        prefs["recording"] = {"output_dir": self._output_path_var.get()}

        save_user_prefs(prefs)
        messagebox.showinfo("Saved", "Settings saved. Changes apply to next recording.")

    # ── Tab 4: History ────────────────────────────────────────────────

    def _build_history_tab(self, notebook):
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="  History  ")

        cols = ("subject", "start", "duration", "status", "path")
        self._history_tree = ttk.Treeview(frame, columns=cols, show="headings", height=14)
        self._history_tree.heading("subject", text="Subject")
        self._history_tree.heading("start", text="Start Time")
        self._history_tree.heading("duration", text="Duration")
        self._history_tree.heading("status", text="Status")
        self._history_tree.heading("path", text="Recording Path")
        self._history_tree.column("subject", width=200)
        self._history_tree.column("start", width=160)
        self._history_tree.column("duration", width=70)
        self._history_tree.column("status", width=80)
        self._history_tree.column("path", width=220)
        self._history_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))
        self._history_tree.bind("<Double-1>", self._open_recording)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="Refresh", command=self._refresh_history).pack(side=tk.LEFT)
        ttk.Label(btn_frame, text="  Double-click to open recording folder", foreground="gray").pack(side=tk.LEFT, padx=10)

    def _refresh_history(self):
        from src.meeting_scheduler import get_meeting_history
        history = _run_async(get_meeting_history(100)) or []

        self._history_tree.delete(*self._history_tree.get_children())
        for m in history:
            dur = f"{(m.get('duration_seconds', 0) or 0) // 60} min"
            self._history_tree.insert("", tk.END, values=(
                m.get("subject", "?"),
                m.get("start_time", "?"),
                dur,
                m.get("status", "?"),
                m.get("recording_path", ""),
            ))

    def _open_recording(self, event):
        sel = self._history_tree.selection()
        if not sel:
            return
        values = self._history_tree.item(sel[0], "values")
        path = values[4] if len(values) > 4 else ""
        if path and os.path.isdir(path):
            _open_path(path)

    # ── Window Management ─────────────────────────────────────────────

    def _on_close(self):
        self.root.withdraw()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self._refresh_upcoming()

    def hide(self):
        self.root.withdraw()

    def toggle(self):
        if self.root.winfo_viewable():
            self.hide()
        else:
            self.show()


# ── Module-level API ──────────────────────────────────────────────────

_app: Optional[DashboardApp] = None


def _gui_thread_main():
    global _root, _app
    _root = tk.Tk()
    _root.withdraw()  # Start hidden
    _app = DashboardApp(_root)
    _root.mainloop()


def init_dashboard(event_loop: asyncio.AbstractEventLoop, scheduler=None):
    """Initialize the dashboard in a background thread."""
    global _loop, _scheduler, _gui_thread
    _loop = event_loop
    _scheduler = scheduler

    _gui_thread = threading.Thread(target=_gui_thread_main, daemon=True)
    _gui_thread.start()


def toggle_dashboard():
    """Show/hide the dashboard window. Safe to call from any thread."""
    if _root and _app:
        _root.after(0, _app.toggle)


def show_dashboard():
    if _root and _app:
        _root.after(0, _app.show)
