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

# Hardcoded server URL — users never see this
_SAARTHI_SERVER = "https://interview-intelligence-production-7e43.up.railway.app"

# ── Color palette ─────────────────────────────────────────────────────
BG = "#f8fafc"           # slate-50
CARD_BG = "#ffffff"
PRIMARY = "#4f46e5"      # indigo-600
PRIMARY_HOVER = "#4338ca" # indigo-700
SUCCESS = "#059669"      # emerald-600
WARNING = "#d97706"      # amber-600
DANGER = "#dc2626"       # red-600
TEXT = "#1e293b"         # slate-800
TEXT_SEC = "#64748b"     # slate-500
BORDER = "#e2e8f0"       # slate-200
ACCENT_BG = "#eef2ff"    # indigo-50
RECORDING_RED = "#dc2626"


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
        root.title("Interview Saarthi Recorder")
        root.geometry("960x620")
        root.minsize(750, 500)
        root.resizable(True, True)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.configure(bg=BG)

        self._apply_styles()

        # ── Top control bar ───────────────────────────────────────────
        top = ttk.Frame(root, padding=(16, 12))
        top.pack(fill=tk.X)

        self._status_label = ttk.Label(
            top, text="Idle — monitoring emails",
            style="Status.TLabel", foreground=SUCCESS,
        )
        self._status_label.pack(side=tk.LEFT)

        self._action_btn = ttk.Button(
            top, text="Start Recording",
            style="Primary.TButton", command=self._toggle_recording,
        )
        self._action_btn.pack(side=tk.RIGHT, padx=(10, 0))

        sep = ttk.Separator(root, orient=tk.HORIZONTAL)
        sep.pack(fill=tk.X)

        # ── Notebook ──────────────────────────────────────────────────
        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=(8, 12))
        notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)

        self._build_account_tab(notebook)
        self._build_upcoming_tab(notebook)
        self._build_schedule_tab(notebook)
        self._build_settings_tab(notebook)
        self._build_history_tab(notebook)

        # Initial data load in background (non-blocking)
        self.root.after(500, self._refresh_upcoming)
        self.root.after(600, self._refresh_history)
        self._poll_status()

    # ── Styling ──────────────────────────────────────────────────────

    def _apply_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 9))
        style.configure("TNotebook", background=BG)
        style.configure("TNotebook.Tab", padding=[14, 7], font=("Segoe UI", 9, "bold"))
        style.map("TNotebook.Tab",
                  background=[("selected", CARD_BG), ("!selected", BG)],
                  foreground=[("selected", PRIMARY), ("!selected", TEXT_SEC)])
        style.configure("TFrame", background=BG)
        style.configure("TLabelframe", background=CARD_BG, foreground=TEXT, relief="flat", borderwidth=1)
        style.configure("TLabelframe.Label", background=BG, foreground=TEXT, font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Card.TLabel", background=CARD_BG, foreground=TEXT)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("TButton", font=("Segoe UI", 9), padding=[10, 5])
        style.configure("Primary.TButton", foreground="white", background=PRIMARY, font=("Segoe UI", 9, "bold"))
        style.map("Primary.TButton",
                  background=[("active", PRIMARY_HOVER), ("!active", PRIMARY)])
        style.configure("Success.TButton", foreground="white", background=SUCCESS)
        style.map("Success.TButton",
                  background=[("active", "#047857"), ("!active", SUCCESS)])
        style.configure("Danger.TButton", foreground="white", background=DANGER)
        style.map("Danger.TButton",
                  background=[("active", "#b91c1c"), ("!active", DANGER)])
        style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"), foreground=TEXT)
        style.configure("Status.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("SubText.TLabel", foreground=TEXT_SEC, font=("Segoe UI", 8))
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 9),
                        background="white", fieldbackground="white", foreground=TEXT)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                        background=BG, foreground=TEXT)
        style.map("Treeview", background=[("selected", ACCENT_BG)],
                  foreground=[("selected", PRIMARY)])
        style.configure("TEntry", padding=[6, 4])
        style.configure("TCombobox", padding=[6, 4])
        style.configure("TCheckbutton", background=CARD_BG, foreground=TEXT, font=("Segoe UI", 9))
        style.configure("TRadiobutton", background=CARD_BG, foreground=TEXT, font=("Segoe UI", 9))
        style.configure("TSpinbox", padding=[6, 4])

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
            subject = rec.subject
            set_active_recorder(None)
            logger.info(f"Recording stopped: {result.get('session_folder', '?')}")
            try:
                from src.tray_app import update_tray_icon
                update_tray_icon(recording=False)
            except Exception:
                pass

            # Auto-upload to Saarthi if connected
            session_folder = result.get('session_folder', '')
            if session_folder:
                self._try_saarthi_upload(session_folder, subject)

        self._update_status_ui()
        self._refresh_history()

    def _try_saarthi_upload(self, session_folder: str, subject: str):
        """Attempt auto-upload to Interview Saarthi in a background thread, respecting upload mode."""
        from src.config import load_user_prefs
        prefs = load_user_prefs()
        upload_mode = prefs.get("saarthi_upload_mode", "approve")

        if upload_mode == "off":
            logger.info("Upload mode is off, recording saved locally only")
            return

        from src.interview_detector import detect_interview_info
        info = detect_interview_info(subject)

        if upload_mode == "approve":
            logger.info(f"Recording pending approval for upload: {subject}")
            if self.root:
                self.root.after(0, lambda: self._status_label.config(
                    text=f"Recording saved — pending upload approval",
                    foreground=WARNING,
                ))
            return

        # upload_mode == "auto"
        def _upload():
            try:
                from src.saarthi_client import SaarthiClient
                client = SaarthiClient()
                if not client.is_connected:
                    return

                from pathlib import Path
                recording_dir = Path(session_folder)
                files = {}
                for fname in ['microphone.wav', 'speaker.wav', 'screen.mp4']:
                    fpath = recording_dir / fname
                    if fpath.exists() and fpath.stat().st_size > 0:
                        files[fname] = fpath

                if not files:
                    return

                result = client.upload_recording(
                    files, title=subject,
                    company=info["company"], round_name=info["round"],
                )
                saarthi_id = result.get('interview_id')
                logger.info(f"GUI auto-uploaded to Saarthi: interview #{saarthi_id}")

                if self.root:
                    self.root.after(0, lambda: self._status_label.config(
                        text=f"Uploaded to Saarthi (interview #{saarthi_id})",
                        foreground="#2563eb",
                    ))
            except Exception as e:
                logger.warning(f"GUI auto-upload to Saarthi failed: {e}")
                if self.root:
                    self.root.after(0, lambda: self._status_label.config(
                        text=f"Saarthi upload failed: {e}",
                        foreground=WARNING,
                    ))

        thread = threading.Thread(target=_upload, daemon=True)
        thread.start()

    def _poll_status(self):
        self._update_status_ui()
        self.root.after(3000, self._poll_status)

    def _update_status_ui(self):
        from src.meeting_recorder import get_active_recorder
        rec = get_active_recorder()
        if rec and rec.is_recording:
            self._status_label.config(text=f"RECORDING: {rec.subject}", foreground=RECORDING_RED)
            self._action_btn.config(text="Stop Recording", style="Danger.TButton")
        else:
            self._status_label.config(text="Idle — monitoring emails", foreground=SUCCESS)
            self._action_btn.config(text="Start Recording", style="Primary.TButton")

    # ── Tab switch handler ────────────────────────────────────────────

    def _on_tab_change(self, event):
        tab_name = event.widget.tab(event.widget.select(), "text").strip()
        if "Upcoming" in tab_name:
            self.root.after(100, self._refresh_upcoming)
        elif "History" in tab_name:
            self.root.after(100, self._refresh_history)

    # ── Tab: Account ──────────────────────────────────────────────────

    def _build_account_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=16)
        notebook.add(frame, text="  Account  ")

        # Container that holds either login form or connected card
        self._account_container = frame
        self._login_frame = None
        self._connected_frame = None

        # Load existing prefs
        from src.config import get_saarthi_config
        saarthi_cfg = get_saarthi_config()

        if saarthi_cfg["token"]:
            # Show connected state, verify in background
            self._build_connected_view(frame, saarthi_cfg["username"])
            self.root.after(1000, self._saarthi_verify_async)
        else:
            self._build_login_view(frame)

        # ── Upload Settings (always visible) ──
        self._upload_frame = ttk.LabelFrame(frame, text="Upload Settings", padding=16)
        self._upload_frame.pack(fill=tk.X, pady=(16, 0))

        from src.config import load_user_prefs as _load_prefs
        _uprefs = _load_prefs()
        current_mode = _uprefs.get("saarthi_upload_mode", "approve")

        self._upload_mode_var = tk.StringVar(value=current_mode)

        mode_header = ttk.Label(self._upload_frame, text="Upload Mode",
                                font=("Segoe UI", 9, "bold"), background=CARD_BG)
        mode_header.pack(anchor="w", pady=(0, 8))

        modes = [
            ("auto", "Auto — Send all recordings to Interview Saarthi automatically"),
            ("approve", "Approve Each — Ask before uploading each recording"),
            ("off", "Local Only — Keep recordings on this computer only"),
        ]
        for val, label in modes:
            ttk.Radiobutton(
                self._upload_frame, text=label,
                variable=self._upload_mode_var, value=val,
            ).pack(anchor="w", padx=(8, 0), pady=2)

        self._auto_organize_var = tk.BooleanVar(value=_uprefs.get("auto_organize_folders", True))
        ttk.Checkbutton(
            self._upload_frame, text="Auto-organize folders by company/round",
            variable=self._auto_organize_var,
        ).pack(anchor="w", padx=(8, 0), pady=(10, 0))

        ttk.Button(
            self._upload_frame, text="Save Upload Settings",
            command=self._save_upload_settings,
        ).pack(anchor="w", pady=(12, 0))

    def _build_login_view(self, parent):
        """Build the login form for unauthenticated users."""
        if self._connected_frame:
            self._connected_frame.pack_forget()
            self._connected_frame.destroy()
            self._connected_frame = None

        self._login_frame = ttk.LabelFrame(parent, text="Sign In to Interview Saarthi", padding=20)
        self._login_frame.pack(fill=tk.X, pady=(0, 0))

        # Username
        ttk.Label(self._login_frame, text="Username", font=("Segoe UI", 9, "bold"),
                  background=CARD_BG).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._saarthi_user_var = tk.StringVar()
        user_entry = ttk.Entry(self._login_frame, textvariable=self._saarthi_user_var, width=35)
        user_entry.grid(row=1, column=0, sticky="ew", pady=(0, 12))

        # Password
        ttk.Label(self._login_frame, text="Password", font=("Segoe UI", 9, "bold"),
                  background=CARD_BG).grid(row=2, column=0, sticky="w", pady=(0, 4))
        self._saarthi_pass_var = tk.StringVar()
        pass_entry = ttk.Entry(self._login_frame, textvariable=self._saarthi_pass_var, show="\u2022", width=35)
        pass_entry.grid(row=3, column=0, sticky="ew", pady=(0, 16))

        # Sign In button
        ttk.Button(
            self._login_frame, text="Sign In",
            style="Primary.TButton", command=self._saarthi_connect,
        ).grid(row=4, column=0, sticky="w", pady=(0, 12))

        # Status label for errors
        self._saarthi_status_label = ttk.Label(
            self._login_frame, text="", foreground=DANGER,
            background=CARD_BG, font=("Segoe UI", 9),
        )
        self._saarthi_status_label.grid(row=5, column=0, sticky="w", pady=(0, 8))

        # Register hint
        ttk.Label(
            self._login_frame,
            text="Don't have an account? Register at interviewsaarthi.com",
            foreground=TEXT_SEC, background=CARD_BG, font=("Segoe UI", 8),
        ).grid(row=6, column=0, sticky="w")

        self._login_frame.columnconfigure(0, weight=1)

    def _build_connected_view(self, parent, username: str):
        """Build the connected card for authenticated users."""
        if self._login_frame:
            self._login_frame.pack_forget()
            self._login_frame.destroy()
            self._login_frame = None

        self._connected_frame = ttk.LabelFrame(parent, text="Account", padding=20)
        self._connected_frame.pack(fill=tk.X, pady=(0, 0))

        # Status row with green dot
        status_row = ttk.Frame(self._connected_frame, style="Card.TFrame")
        status_row.pack(fill=tk.X, pady=(0, 12))

        # Green circle indicator (using a canvas)
        dot_canvas = tk.Canvas(status_row, width=12, height=12, bg=CARD_BG,
                               highlightthickness=0)
        dot_canvas.create_oval(2, 2, 10, 10, fill=SUCCESS, outline=SUCCESS)
        dot_canvas.pack(side=tk.LEFT, padx=(0, 8))

        self._connected_label = ttk.Label(
            status_row, text=f"Connected as {username}",
            font=("Segoe UI", 11, "bold"), foreground=SUCCESS, background=CARD_BG,
        )
        self._connected_label.pack(side=tk.LEFT)

        # Plan info (loaded from prefs if available)
        from src.config import load_user_prefs
        prefs = load_user_prefs()
        plan = prefs.get("saarthi_plan", "free")
        plan_label = ttk.Label(
            self._connected_frame,
            text=f"Plan: {plan.capitalize()}",
            foreground=TEXT_SEC, background=CARD_BG, font=("Segoe UI", 9),
        )
        plan_label.pack(anchor="w", pady=(0, 16))

        # Sign Out button
        ttk.Button(
            self._connected_frame, text="Sign Out",
            style="Danger.TButton", command=self._saarthi_disconnect,
        ).pack(anchor="w")

        # Hidden status label for verify errors
        self._saarthi_status_label = ttk.Label(
            self._connected_frame, text="", background=CARD_BG, font=("Segoe UI", 9),
        )
        self._saarthi_status_label.pack(anchor="w", pady=(8, 0))

    def _saarthi_connect(self):
        """Handle Sign In button click — runs login in a thread."""
        username = self._saarthi_user_var.get().strip()
        password = self._saarthi_pass_var.get().strip()
        if not username or not password:
            self._saarthi_status_label.config(text="Enter username and password", foreground=DANGER)
            return

        self._saarthi_status_label.config(text="Signing in...", foreground=WARNING)

        def _do_login():
            try:
                from src.saarthi_client import SaarthiClient
                client = SaarthiClient()
                client.server_url = _SAARTHI_SERVER
                data = client.login(username, password)
                logged_user = data.get('username', username)
                plan = data.get('plan', 'free')

                # Save plan info
                from src.config import save_user_prefs
                save_user_prefs({"saarthi_plan": plan})

                logger.info(f"Saarthi login successful: {logged_user}")

                # Switch to connected view on main thread
                self.root.after(0, lambda: self._build_connected_view(
                    self._account_container, logged_user))
                # Re-pack upload frame to keep it below
                self.root.after(50, lambda: self._repack_upload_frame())
            except Exception as e:
                self.root.after(0, lambda: self._saarthi_status_label.config(
                    text=f"Login failed: {e}", foreground=DANGER,
                ))
                logger.warning(f"Saarthi login failed: {e}")

        threading.Thread(target=_do_login, daemon=True).start()

    def _saarthi_disconnect(self):
        """Sign out from Saarthi."""
        from src.config import save_user_prefs
        save_user_prefs({
            "saarthi_token": "",
            "saarthi_username": "",
            "saarthi_plan": "",
        })
        logger.info("Signed out from Saarthi")
        self._build_login_view(self._account_container)
        self._repack_upload_frame()

    def _repack_upload_frame(self):
        """Ensure the upload settings frame stays at the bottom of the Account tab."""
        self._upload_frame.pack_forget()
        self._upload_frame.pack(fill=tk.X, pady=(16, 0))

    def _saarthi_verify_async(self):
        """Verify the stored Saarthi token in a background thread."""
        def _do_verify():
            try:
                from src.saarthi_client import SaarthiClient
                client = SaarthiClient()
                if not client.verify():
                    self.root.after(0, lambda: self._show_token_expired())
            except Exception:
                self.root.after(0, lambda: self._show_token_expired())

        threading.Thread(target=_do_verify, daemon=True).start()

    def _show_token_expired(self):
        """Token expired — switch back to login view."""
        self._build_login_view(self._account_container)
        self._repack_upload_frame()
        self._saarthi_status_label.config(
            text="Session expired — please sign in again", foreground=WARNING,
        )

    def _save_upload_settings(self):
        """Save upload mode and auto-organize preference to user_prefs.yaml."""
        from src.config import save_user_prefs
        save_user_prefs({
            "saarthi_upload_mode": self._upload_mode_var.get(),
            "auto_organize_folders": self._auto_organize_var.get(),
        })
        logger.info(f"Upload settings saved: mode={self._upload_mode_var.get()}, "
                     f"auto_organize={self._auto_organize_var.get()}")

    # ── Tab: Upcoming Meetings ────────────────────────────────────────

    def _build_upcoming_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=16)
        notebook.add(frame, text="  Upcoming Meetings  ")

        # Header row
        header_row = ttk.Frame(frame)
        header_row.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(header_row, text="Upcoming Meetings", style="Header.TLabel").pack(side=tk.LEFT)

        self._stats_label = ttk.Label(header_row, text="", foreground=TEXT_SEC, font=("Segoe UI", 9))
        self._stats_label.pack(side=tk.RIGHT)

        # Treeview
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

        # Button row
        btn = ttk.Frame(frame)
        btn.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn, text="Refresh", command=self._refresh_upcoming).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn, text="Scan Emails Now", style="Primary.TButton",
                   command=self._scan_now).pack(side=tk.LEFT)

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

    # ── Tab: Schedule ─────────────────────────────────────────────────

    def _build_schedule_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=16)
        notebook.add(frame, text="  Schedule  ")

        ttk.Label(frame, text="Schedule a Future Recording", style="Header.TLabel").pack(
            anchor="w", pady=(0, 12))

        form = ttk.LabelFrame(frame, text="Recording Details", padding=16)
        form.pack(fill=tk.X)

        labels = ["Subject:", "Date (YYYY-MM-DD):", "Time (HH:MM):", "Duration (min):"]
        for i, lbl in enumerate(labels):
            ttk.Label(form, text=lbl, background=CARD_BG).grid(
                row=i, column=0, sticky="w", padx=(0, 12), pady=6)

        self._sched_subject = ttk.Entry(form, width=40)
        self._sched_subject.insert(0, "Meeting")
        self._sched_subject.grid(row=0, column=1, sticky="ew", pady=6)

        self._sched_date = ttk.Entry(form, width=14)
        self._sched_date.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self._sched_date.grid(row=1, column=1, sticky="w", pady=6)

        self._sched_time = ttk.Entry(form, width=10)
        self._sched_time.insert(0, datetime.now().strftime("%H:%M"))
        self._sched_time.grid(row=2, column=1, sticky="w", pady=6)

        self._sched_dur = ttk.Spinbox(form, from_=5, to=240, width=8, increment=5)
        self._sched_dur.set(45)
        self._sched_dur.grid(row=3, column=1, sticky="w", pady=6)

        form.columnconfigure(1, weight=1)

        ttk.Button(
            frame, text="Schedule Recording",
            style="Primary.TButton", command=self._do_schedule,
        ).pack(anchor="w", pady=(14, 0))

        ttk.Label(
            frame,
            text="Tip: Use the Start Recording button in the top bar for immediate recording.",
            foreground=TEXT_SEC, font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(24, 0))

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

    # ── Tab: Settings ─────────────────────────────────────────────────

    def _build_settings_tab(self, notebook):
        outer = ttk.Frame(notebook)
        notebook.add(outer, text="  Settings  ")

        # Scrollable canvas
        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0, bg=BG)
        vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas, padding=16)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw", tags="inner")
        canvas.configure(yscrollcommand=vsb.set)

        def _resize_inner(event):
            canvas.itemconfig("inner", width=event.width)
        canvas.bind("<Configure>", _resize_inner)

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # ── Audio Devices ──
        dev = ttk.LabelFrame(inner, text="Audio Devices", padding=16)
        dev.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(dev, text="Microphone:", background=CARD_BG).grid(
            row=0, column=0, sticky="w", padx=(0, 12), pady=6)
        self._mic_combo = ttk.Combobox(dev, state="readonly")
        self._mic_combo.grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(dev, text="Speaker:", background=CARD_BG).grid(
            row=1, column=0, sticky="w", padx=(0, 12), pady=6)
        self._spk_combo = ttk.Combobox(dev, state="readonly")
        self._spk_combo.grid(row=1, column=1, sticky="ew", pady=6)

        dev.columnconfigure(1, weight=1)

        dbtn = ttk.Frame(dev, style="Card.TFrame")
        dbtn.grid(row=2, column=0, columnspan=2, pady=(8, 0), sticky="w")
        ttk.Button(dbtn, text="Refresh Devices", command=self._refresh_devices).pack(
            side=tk.LEFT, padx=(0, 8))
        ttk.Button(dbtn, text="Reset to Auto-Detect", command=self._reset_devices).pack(side=tk.LEFT)

        # ── Audio Tests ──
        testf = ttk.LabelFrame(inner, text="Audio Device Tests", padding=16)
        testf.pack(fill=tk.X, pady=(0, 12))

        mic_test_row = ttk.Frame(testf, style="Card.TFrame")
        mic_test_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(mic_test_row, text="Test Microphone", command=self._test_mic).pack(
            side=tk.LEFT, padx=(0, 12))
        self._mic_test_label = ttk.Label(mic_test_row, text="", font=("Segoe UI", 9),
                                          background=CARD_BG)
        self._mic_test_label.pack(side=tk.LEFT)

        spk_test_row = ttk.Frame(testf, style="Card.TFrame")
        spk_test_row.pack(fill=tk.X)
        ttk.Button(spk_test_row, text="Test Speaker Capture", command=self._test_speaker).pack(
            side=tk.LEFT, padx=(0, 12))
        self._spk_test_label = ttk.Label(spk_test_row, text="", font=("Segoe UI", 9),
                                          background=CARD_BG)
        self._spk_test_label.pack(side=tk.LEFT)

        ttk.Label(
            testf,
            text="Mic test records 3 seconds. Speaker test plays a beep and captures via WASAPI loopback.",
            foreground=TEXT_SEC, background=CARD_BG, font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(10, 0))

        # ── Output Path ──
        pathf = ttk.LabelFrame(inner, text="Recording Output", padding=16)
        pathf.pack(fill=tk.X, pady=(0, 12))

        from src.config import get_recording_config
        self._output_var = tk.StringVar(value=get_recording_config()["output_dir"])

        prow = ttk.Frame(pathf, style="Card.TFrame")
        prow.pack(fill=tk.X)
        ttk.Entry(prow, textvariable=self._output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(prow, text="Browse", command=self._browse_output).pack(side=tk.LEFT)

        # ── Notifications ──
        notf = ttk.LabelFrame(inner, text="Notifications", padding=16)
        notf.pack(fill=tk.X, pady=(0, 12))

        from src.config import load_user_prefs
        nprefs = load_user_prefs().get("notifications", {})

        self._notif_enabled = tk.BooleanVar(value=nprefs.get("enabled", True))
        self._notif_on_start = tk.BooleanVar(value=nprefs.get("on_start", False))
        self._notif_on_stop = tk.BooleanVar(value=nprefs.get("on_stop", False))

        ttk.Checkbutton(notf, text="Enable desktop notifications",
                        variable=self._notif_enabled).pack(anchor="w", pady=3)
        ttk.Checkbutton(notf, text="Notify when recording starts (may interrupt screenshare — off by default)",
                        variable=self._notif_on_start).pack(anchor="w", pady=3)
        ttk.Checkbutton(notf, text="Notify when recording stops (may interrupt screenshare — off by default)",
                        variable=self._notif_on_stop).pack(anchor="w", pady=3)

        ttk.Label(
            notf,
            text="Start/stop notifications are disabled by default so they don't appear during meetings.",
            foreground=TEXT_SEC, background=CARD_BG, font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(6, 0))

        # ── Hotkeys ──
        hkf = ttk.LabelFrame(inner, text="Custom Hotkeys", padding=16)
        hkf.pack(fill=tk.X, pady=(0, 12))

        from src.config import get_tray_config
        tray_cfg = get_tray_config()

        ttk.Label(hkf, text="Dashboard Hotkey:", background=CARD_BG).grid(
            row=0, column=0, sticky="w", padx=(0, 12), pady=6)
        self._hotkey_dashboard_var = tk.StringVar(value=tray_cfg["hotkey_toggle_dashboard"])
        ttk.Entry(hkf, textvariable=self._hotkey_dashboard_var, width=25).grid(
            row=0, column=1, sticky="w", pady=6)

        ttk.Label(hkf, text="Stop Recording Hotkey:", background=CARD_BG).grid(
            row=1, column=0, sticky="w", padx=(0, 12), pady=6)
        self._hotkey_stop_var = tk.StringVar(value=tray_cfg["hotkey_stop_recording"])
        ttk.Entry(hkf, textvariable=self._hotkey_stop_var, width=25).grid(
            row=1, column=1, sticky="w", pady=6)

        ttk.Label(
            hkf,
            text="Use format like ctrl+shift+m. Changes take effect after restart.",
            foreground=TEXT_SEC, background=CARD_BG, font=("Segoe UI", 8),
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        hkf.columnconfigure(1, weight=1)

        # ── Save ──
        ttk.Button(
            inner, text="Save Settings",
            style="Primary.TButton", command=self._save_settings,
        ).pack(anchor="w", pady=(8, 0))

        self._refresh_devices()

    def _refresh_devices(self):
        from src.meeting_recorder import list_audio_devices
        devices = list_audio_devices()
        self._mic_devices = devices.get("microphones", [])
        self._spk_devices = devices.get("speakers", [])

        self._mic_combo["values"] = ["Auto-Detect"] + [
            f"[{d['index']}] {d['name']}" for d in self._mic_devices]
        self._spk_combo["values"] = ["Auto-Detect (WASAPI Loopback)"] + [
            f"[{d['index']}] {d['name']}" for d in self._spk_devices]
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

    def _test_mic(self):
        self._mic_test_label.config(text="Recording 3s...", foreground="orange")

        def _run():
            try:
                import pyaudio
                import numpy as np
                p = pyaudio.PyAudio()
                kwargs = dict(format=pyaudio.paInt16, channels=1, rate=44100,
                              input=True, frames_per_buffer=1024)
                mic_sel = self._mic_combo.current()
                if mic_sel > 0:
                    kwargs["input_device_index"] = self._mic_devices[mic_sel - 1]["index"]
                stream = p.open(**kwargs)
                frames = []
                for _ in range(int(44100 / 1024 * 3)):
                    frames.append(stream.read(1024, exception_on_overflow=False))
                stream.stop_stream()
                stream.close()
                p.terminate()
                audio = np.frombuffer(b''.join(frames), dtype=np.int16)
                rms = int(np.sqrt(np.mean(audio.astype(float)**2)))
                if rms > 50:
                    self.root.after(0, lambda: self._mic_test_label.config(
                        text=f"Mic working! Audio detected (RMS: {rms})", foreground="#2d8a4e"))
                else:
                    self.root.after(0, lambda: self._mic_test_label.config(
                        text=f"Mic connected (RMS: {rms}). Speak louder to verify.", foreground="#2d8a4e"))
            except Exception as e:
                err = str(e)[:60]
                self.root.after(0, lambda: self._mic_test_label.config(
                    text=f"Mic error: {err}", foreground="red"))

        threading.Thread(target=_run, daemon=True).start()

    def _test_speaker(self):
        self._spk_test_label.config(text="Playing tone & capturing...", foreground="orange")

        def _run():
            try:
                import pyaudiowpatch as pyaudio_wp
                import numpy as np
                import winsound
                import threading as thr
                import time

                p = pyaudio_wp.PyAudio()

                # Find loopback device for default speakers
                wasapi = p.get_host_api_info_by_type(pyaudio_wp.paWASAPI)
                default_spk = p.get_device_info_by_index(wasapi['defaultOutputDevice'])

                loopback = None
                for lb in p.get_loopback_device_info_generator():
                    if default_spk['name'] in lb['name']:
                        loopback = lb
                        break

                if not loopback:
                    p.terminate()
                    self.root.after(0, lambda: self._spk_test_label.config(
                        text="No loopback device found", foreground="red"))
                    return

                ch = loopback['maxInputChannels']
                sr = int(loopback['defaultSampleRate'])

                frames = []

                def callback(in_data, frame_count, time_info, status):
                    if in_data:
                        frames.append(in_data)
                    return (None, pyaudio_wp.paContinue)

                stream = p.open(
                    format=pyaudio_wp.paInt16, channels=ch, rate=sr,
                    input=True, input_device_index=loopback['index'],
                    frames_per_buffer=512, stream_callback=callback,
                )

                # Play a beep in background
                beep_thread = thr.Thread(target=lambda: winsound.Beep(440, 2000), daemon=True)
                beep_thread.start()

                time.sleep(3)
                stream.stop_stream()
                stream.close()
                p.terminate()

                if frames:
                    audio = np.frombuffer(b''.join(frames), dtype=np.int16)
                    rms = int(np.sqrt(np.mean(audio.astype(float)**2)))
                    if rms > 100:
                        self.root.after(0, lambda: self._spk_test_label.config(
                            text=f"OK (RMS: {rms})", foreground="#2d8a4e"))
                    else:
                        self.root.after(0, lambda: self._spk_test_label.config(
                            text=f"Silent (RMS: {rms})", foreground="orange"))
                else:
                    self.root.after(0, lambda: self._spk_test_label.config(
                        text="No audio captured", foreground="red"))
            except ImportError:
                self.root.after(0, lambda: self._spk_test_label.config(
                    text="Install pyaudiowpatch for speaker test", foreground="red"))
            except Exception as e:
                self.root.after(0, lambda: self._spk_test_label.config(
                    text=f"Failed: {str(e)[:50]}", foreground="red"))

        threading.Thread(target=_run, daemon=True).start()

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
            "hotkeys": {
                "dashboard": self._hotkey_dashboard_var.get().strip(),
                "stop_recording": self._hotkey_stop_var.get().strip(),
            },
        }
        save_user_prefs(prefs)
        logger.info("Settings saved from GUI")

    # ── Tab: History ──────────────────────────────────────────────────

    def _build_history_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=16)
        notebook.add(frame, text="  History  ")

        # Header
        ttk.Label(frame, text="Recording History", style="Header.TLabel").pack(
            anchor="w", pady=(0, 10))

        # Pending uploads section
        self._pending_frame = ttk.LabelFrame(frame, text="Pending Uploads", padding=12)
        self._pending_inner = ttk.Frame(self._pending_frame, style="Card.TFrame")
        self._pending_inner.pack(fill=tk.X)

        # Treeview
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("subject", "start", "duration", "status", "path")
        self._history_tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
        for col, w in [("subject", 220), ("start", 160), ("duration", 70), ("status", 80), ("path", 280)]:
            self._history_tree.heading(col, text=col.replace("path", "Recording Path").title())
            self._history_tree.column(col, width=w, minwidth=50)

        self._history_tree.tag_configure("pending", foreground=WARNING, font=("Segoe UI", 9, "bold"))

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._history_tree.yview)
        self._history_tree.configure(yscrollcommand=vsb.set)
        self._history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._history_tree.bind("<Double-1>", self._open_recording)

        # Bottom bar with action buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn_frame, text="Upload Selected", style="Primary.TButton",
                   command=self._upload_selected).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_frame, text="Skip Upload",
                   command=self._skip_upload_selected).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_frame, text="Refresh", command=self._refresh_history).pack(side=tk.RIGHT)

        ttk.Label(
            frame,
            text="Double-click a row to open the recording folder. Select pending items to Upload or Skip.",
            foreground=TEXT_SEC, font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(6, 0))

    def _refresh_history(self):
        from src.meeting_scheduler import get_meeting_history
        history = _run_async(get_meeting_history(100)) or []
        self._history_tree.delete(*self._history_tree.get_children())

        pending_count = 0
        for m in history:
            dur = f"{(m.get('duration_seconds', 0) or 0) // 60} min"
            status = m.get("status", "?")
            tags = ("pending",) if status == "pending_upload" else ()
            self._history_tree.insert("", tk.END, values=(
                m.get("subject", "?"), m.get("start_time", "?"),
                dur, status, m.get("recording_path", ""),
            ), tags=tags)
            if status == "pending_upload":
                pending_count += 1

        # Show/hide pending uploads banner
        if pending_count > 0:
            self._pending_frame.pack(fill=tk.X, pady=(0, 8),
                                     before=self._pending_frame.master.winfo_children()[1])
            for w in self._pending_inner.winfo_children():
                w.destroy()
            ttk.Label(
                self._pending_inner,
                text=f"{pending_count} recording(s) waiting for upload approval. "
                     f"Select and click 'Upload Selected'.",
                foreground=WARNING, background=CARD_BG, font=("Segoe UI", 9),
            ).pack(anchor="w")
        else:
            self._pending_frame.pack_forget()

    def _open_recording(self, event):
        sel = self._history_tree.selection()
        if not sel:
            return
        values = self._history_tree.item(sel[0], "values")
        path = values[4] if len(values) > 4 else ""
        if path and os.path.isdir(path):
            _open_path(path)

    def _upload_selected(self):
        """Upload selected pending_upload recordings to Saarthi."""
        sel = self._history_tree.selection()
        if not sel:
            return
        for item_id in sel:
            values = self._history_tree.item(item_id, "values")
            tags = self._history_tree.item(item_id, "tags")
            if "pending" not in tags:
                continue
            subject = values[0]
            recording_path = values[4] if len(values) > 4 else ""
            if not recording_path or not os.path.isdir(recording_path):
                continue
            self._do_upload_recording(recording_path, subject)
        self.root.after(2000, self._refresh_history)

    def _skip_upload_selected(self):
        """Mark selected pending_upload recordings as recorded (skip upload)."""
        sel = self._history_tree.selection()
        if not sel:
            return
        for item_id in sel:
            values = self._history_tree.item(item_id, "values")
            tags = self._history_tree.item(item_id, "tags")
            if "pending" not in tags:
                continue
            recording_path = values[4] if len(values) > 4 else ""

            def _mark_skipped(path=recording_path):
                try:
                    from src import db as _db
                    import asyncio as _aio

                    async def _update():
                        conn = await _db.get_db()
                        await conn.execute(
                            "UPDATE meetings SET status = 'recorded' "
                            "WHERE recording_path = ? AND status = 'pending_upload'",
                            (path,),
                        )
                        await conn.commit()
                        await conn.close()

                    if _loop and _loop.is_running():
                        _aio.run_coroutine_threadsafe(_update(), _loop).result(timeout=10)
                except Exception as e:
                    logger.warning(f"Failed to skip upload: {e}")

            threading.Thread(target=_mark_skipped, daemon=True).start()

        self.root.after(1000, self._refresh_history)

    def _do_upload_recording(self, recording_path: str, subject: str):
        """Upload a single recording to Saarthi in a background thread."""
        from src.interview_detector import detect_interview_info
        info = detect_interview_info(subject)

        def _upload():
            try:
                from src.saarthi_client import SaarthiClient
                client = SaarthiClient()
                if not client.is_connected:
                    logger.warning("Cannot upload: not connected to Saarthi")
                    return

                from pathlib import Path
                recording_dir = Path(recording_path)
                files = {}
                for fname in ['microphone.wav', 'speaker.wav', 'screen.mp4']:
                    fpath = recording_dir / fname
                    if fpath.exists() and fpath.stat().st_size > 0:
                        files[fname] = fpath

                if not files:
                    logger.warning(f"No files to upload in {recording_path}")
                    return

                result = client.upload_recording(
                    files, title=subject,
                    company=info["company"], round_name=info["round"],
                )
                saarthi_id = result.get('interview_id')
                logger.info(f"Uploaded to Saarthi: interview #{saarthi_id}")

                # Update DB
                import asyncio as _aio
                from src import db as _db

                async def _update_db():
                    conn = await _db.get_db()
                    await conn.execute(
                        "UPDATE meetings SET status = 'uploaded', recording_path = ? "
                        "WHERE recording_path = ?",
                        (f"saarthi:{saarthi_id}", recording_path),
                    )
                    await conn.commit()
                    await conn.close()

                if _loop and _loop.is_running():
                    _aio.run_coroutine_threadsafe(_update_db(), _loop).result(timeout=15)

                if self.root:
                    self.root.after(0, lambda: self._status_label.config(
                        text=f"Uploaded to Saarthi (interview #{saarthi_id})",
                        foreground="#2563eb",
                    ))
            except Exception as e:
                logger.warning(f"Upload failed for {subject}: {e}")
                if self.root:
                    self.root.after(0, lambda: self._status_label.config(
                        text=f"Upload failed: {e}",
                        foreground=WARNING,
                    ))

        threading.Thread(target=_upload, daemon=True).start()

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
