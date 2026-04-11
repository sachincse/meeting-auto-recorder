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

_SAARTHI_SERVER = "https://interview-intelligence-production-7e43.up.railway.app"

# ── Color palette ─────────────────────────────────────────────────────
BG = "#f8fafc"
CARD_BG = "#ffffff"
PRIMARY = "#4f46e5"
PRIMARY_HOVER = "#4338ca"
SUCCESS = "#059669"
WARNING = "#d97706"
DANGER = "#dc2626"
TEXT = "#1e293b"
TEXT_SEC = "#64748b"
BORDER = "#e2e8f0"
ACCENT_BG = "#eef2ff"
RECORDING_RED = "#dc2626"


def _run_async_bg(coro, callback=None):
    """Run async coroutine in background, call callback(result) on GUI thread when done."""
    def _worker():
        if not _loop or not _loop.is_running():
            return
        future = asyncio.run_coroutine_threadsafe(coro, _loop)
        try:
            result = future.result(timeout=30)
        except Exception:
            result = None
        if callback and _root:
            _root.after(0, lambda: callback(result))
    threading.Thread(target=_worker, daemon=True).start()


def _run_async(coro):
    """Run async coroutine from GUI thread (short timeout). Use _run_async_bg when possible."""
    if not _loop or not _loop.is_running():
        return None
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    try:
        return future.result(timeout=3)
    except Exception:
        return None


def _open_path(path: str):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ── Badge colors for meeting statuses ─────────────────────────────────
_STATUS_COLORS = {
    "scheduled": "#3b82f6",   # blue
    "recording": "#dc2626",   # red
    "recorded":  "#059669",   # green
    "synced":    "#059669",   # green
    "uploaded":  "#059669",   # green
    "missed":    "#94a3b8",   # gray
    "failed":    "#dc2626",   # red
}


class DashboardApp:
    """Main GUI application with 4 tabs: Dashboard, Meetings, Settings, About."""

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Interview Saarthi Recorder")
        root.geometry("960x620")
        root.minsize(750, 500)
        root.resizable(True, True)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.configure(bg=BG)

        self._apply_styles()

        # ── Top control bar ───────────────────────────────────────
        top = ttk.Frame(root, padding=(16, 12))
        top.pack(fill=tk.X)

        self._status_label = ttk.Label(
            top, text="Idle — monitoring emails",
            style="Status.TLabel", foreground=SUCCESS,
        )
        self._status_label.pack(side=tk.LEFT)

        ttk.Button(top, text="Restart", command=self._restart_app).pack(side=tk.RIGHT, padx=(4, 0))

        self._action_btn = ttk.Button(
            top, text="Start Recording",
            style="Primary.TButton", command=self._toggle_recording,
        )
        self._action_btn.pack(side=tk.RIGHT, padx=(10, 0))

        ttk.Separator(root, orient=tk.HORIZONTAL).pack(fill=tk.X)

        # ── Notebook (4 tabs) ─────────────────────────────────────
        self._notebook = ttk.Notebook(root)
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=(8, 12))
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)

        self._build_dashboard_tab(self._notebook)
        self._build_meetings_tab(self._notebook)
        self._build_settings_tab(self._notebook)
        self._build_about_tab(self._notebook)

        # Deferred data loading (non-blocking)
        self.root.after(500, self._load_initial_data)
        self._poll_status()

    # ── Styling ───────────────────────────────────────────────────

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
        style.map("Primary.TButton", background=[("active", PRIMARY_HOVER), ("!active", PRIMARY)])
        style.configure("Success.TButton", foreground="white", background=SUCCESS)
        style.map("Success.TButton", background=[("active", "#047857"), ("!active", SUCCESS)])
        style.configure("Danger.TButton", foreground="white", background=DANGER)
        style.map("Danger.TButton", background=[("active", "#b91c1c"), ("!active", DANGER)])
        style.configure("Small.TButton", font=("Segoe UI", 8), padding=[6, 3])
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
        style.configure("TSpinbox", padding=[6, 4])

    # ── Initial data load ─────────────────────────────────────────

    def _load_initial_data(self):
        self._refresh_meetings()

    # ── Recording toggle ──────────────────────────────────────────

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
            session_folder = result.get('session_folder', '')
            if session_folder:
                self._try_saarthi_upload(session_folder, subject)
        self._update_status_ui()
        self._refresh_meetings()

    def _try_saarthi_upload(self, session_folder: str, subject: str):
        """Auto-upload to Interview Saarthi in background, respecting upload mode."""
        from src.config import load_user_prefs
        prefs = load_user_prefs()
        upload_mode = prefs.get("saarthi_upload_mode", "auto")
        if upload_mode == "off":
            logger.info("Upload mode is off, recording saved locally only")
            return
        if upload_mode == "manual":
            logger.info(f"Upload mode is manual, skipping auto-upload for: {subject}")
            return

        from src.interview_detector import detect_interview_info
        info = detect_interview_info(subject)

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
                logger.info(f"Auto-uploaded to Saarthi: interview #{saarthi_id}")
                if self.root:
                    self.root.after(0, lambda: self._status_label.config(
                        text=f"Synced to Saarthi (#{saarthi_id})", foreground="#2563eb"))
            except Exception as e:
                logger.warning(f"Auto-upload failed: {e}")
                if self.root:
                    self.root.after(0, lambda: self._status_label.config(
                        text=f"Sync failed: {e}", foreground=WARNING))
        threading.Thread(target=_upload, daemon=True).start()

    # ── Status polling ────────────────────────────────────────────

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

    # ── Tab change handler ────────────────────────────────────────

    def _on_tab_change(self, event):
        tab_name = event.widget.tab(event.widget.select(), "text").strip()
        if tab_name == "Meetings":
            self.root.after(100, self._refresh_meetings)

    # ══════════════════════════════════════════════════════════════
    # TAB 1: Dashboard (login / connected status)
    # ══════════════════════════════════════════════════════════════

    def _build_dashboard_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=16)
        notebook.add(frame, text="  Dashboard  ")
        self._dash_container = frame
        self._login_frame = None
        self._connected_frame = None

        from src.config import get_saarthi_config
        cfg = get_saarthi_config()
        if cfg["token"]:
            self._build_connected_view(cfg["username"])
            self.root.after(1000, self._verify_token_async)
        else:
            self._build_login_view()

    def _build_login_view(self):
        """Show clean login form."""
        if self._connected_frame:
            self._connected_frame.destroy()
            self._connected_frame = None

        self._login_frame = ttk.LabelFrame(self._dash_container, text="Sign In", padding=24)
        self._login_frame.pack(fill=tk.X, pady=(0, 0))

        ttk.Label(self._login_frame, text="Username", font=("Segoe UI", 9, "bold"),
                  background=CARD_BG).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._user_var = tk.StringVar()
        ttk.Entry(self._login_frame, textvariable=self._user_var, width=35).grid(
            row=1, column=0, sticky="ew", pady=(0, 12))

        ttk.Label(self._login_frame, text="Password", font=("Segoe UI", 9, "bold"),
                  background=CARD_BG).grid(row=2, column=0, sticky="w", pady=(0, 4))
        self._pass_var = tk.StringVar()
        ttk.Entry(self._login_frame, textvariable=self._pass_var, show="\u2022", width=35).grid(
            row=3, column=0, sticky="ew", pady=(0, 16))

        ttk.Button(self._login_frame, text="Sign In", style="Primary.TButton",
                   command=self._do_login).grid(row=4, column=0, sticky="w", pady=(0, 12))

        self._login_status = ttk.Label(self._login_frame, text="", foreground=DANGER,
                                       background=CARD_BG, font=("Segoe UI", 9))
        self._login_status.grid(row=5, column=0, sticky="w", pady=(0, 8))

        ttk.Label(self._login_frame,
                  text="Don't have an account? Register at interview-intelligence-production-7e43.up.railway.app",
                  foreground=TEXT_SEC, background=CARD_BG, font=("Segoe UI", 8)).grid(
            row=6, column=0, sticky="w")

        self._login_frame.columnconfigure(0, weight=1)

    def _build_connected_view(self, username: str):
        """Show connected status card with stats."""
        if self._login_frame:
            self._login_frame.destroy()
            self._login_frame = None

        self._connected_frame = ttk.LabelFrame(self._dash_container, text="Account", padding=20)
        self._connected_frame.pack(fill=tk.X, pady=(0, 0))

        # Green status indicator
        status_row = ttk.Frame(self._connected_frame, style="Card.TFrame")
        status_row.pack(fill=tk.X, pady=(0, 8))

        dot = tk.Canvas(status_row, width=12, height=12, bg=CARD_BG, highlightthickness=0)
        dot.create_oval(2, 2, 10, 10, fill=SUCCESS, outline=SUCCESS)
        dot.pack(side=tk.LEFT, padx=(0, 8))

        from src.config import load_user_prefs
        plan = load_user_prefs().get("saarthi_plan", "free")

        ttk.Label(status_row, text=f"Connected as {username}  \u2022  {plan.capitalize()} plan",
                  font=("Segoe UI", 11, "bold"), foreground=SUCCESS,
                  background=CARD_BG).pack(side=tk.LEFT)

        # Stats row (populated async)
        self._stats_label = ttk.Label(self._connected_frame, text="Loading stats...",
                                      foreground=TEXT_SEC, background=CARD_BG, font=("Segoe UI", 9))
        self._stats_label.pack(anchor="w", pady=(4, 16))
        self.root.after(200, self._load_stats)

        # Sign Out (small, at bottom)
        ttk.Button(self._connected_frame, text="Sign Out", style="Small.TButton",
                   command=self._do_logout).pack(anchor="w")

        self._dash_status = ttk.Label(self._connected_frame, text="", background=CARD_BG,
                                      font=("Segoe UI", 9))
        self._dash_status.pack(anchor="w", pady=(8, 0))

    def _load_stats(self):
        """Load meeting stats in background and update the dashboard card."""
        from src.meeting_scheduler import get_meeting_stats

        def _update(stats):
            if not stats or not self._connected_frame:
                return
            total = stats.get('total', 0)
            recorded = stats.get('recorded', 0)
            synced = stats.get('uploaded', 0)
            self._stats_label.config(
                text=f"{total} meetings detected  \u2022  {recorded} recorded  \u2022  {synced} synced to web")

        _run_async_bg(get_meeting_stats(), _update)

    def _do_login(self):
        """Handle Sign In — runs in background thread."""
        username = self._user_var.get().strip()
        password = self._pass_var.get().strip()
        if not username or not password:
            self._login_status.config(text="Enter username and password", foreground=DANGER)
            return
        self._login_status.config(text="Signing in...", foreground=WARNING)

        def _login_thread():
            try:
                from src.saarthi_client import SaarthiClient
                client = SaarthiClient()
                client.server_url = _SAARTHI_SERVER
                data = client.login(username, password)
                logged_user = data.get('username', username)
                plan = data.get('plan', 'free')

                from src.config import save_user_prefs
                save_user_prefs({"saarthi_plan": plan})
                logger.info(f"Saarthi login successful: {logged_user}")

                self._load_meetings_from_saarthi(client)

                self.root.after(0, lambda: self._build_connected_view(logged_user))
                self.root.after(200, self._refresh_meetings)
            except Exception as e:
                self.root.after(0, lambda: self._login_status.config(
                    text=f"Login failed: {e}", foreground=DANGER))
                logger.warning(f"Saarthi login failed: {e}")

        threading.Thread(target=_login_thread, daemon=True).start()

    def _do_logout(self):
        """Sign out from Saarthi."""
        from src.config import save_user_prefs
        save_user_prefs({"saarthi_token": "", "saarthi_username": "", "saarthi_plan": ""})
        logger.info("Signed out from Saarthi")
        self._build_login_view()

    def _verify_token_async(self):
        """Verify stored token in background. Show login if expired."""
        def _verify():
            try:
                from src.saarthi_client import SaarthiClient
                client = SaarthiClient()
                if not client.verify():
                    self.root.after(0, self._show_expired)
            except Exception:
                self.root.after(0, self._show_expired)
        threading.Thread(target=_verify, daemon=True).start()

    def _show_expired(self):
        self._build_login_view()
        if hasattr(self, '_login_status'):
            self._login_status.config(text="Session expired — please sign in again", foreground=WARNING)

    def _load_meetings_from_saarthi(self, client):
        """Sync meetings from Saarthi web into local DB. Called from login thread."""
        try:
            meetings = client.load_meetings()
            if not meetings:
                return
            import asyncio as _aio

            async def _insert():
                from src import db as _db
                conn = await _db.get_db()
                inserted = 0
                for m in meetings:
                    meeting_url = m.get("meeting_url", "")
                    start_time = m.get("start_time", "")
                    if not meeting_url or not start_time:
                        continue
                    cursor = await conn.execute(
                        "SELECT id FROM meetings WHERE meeting_url = ? AND start_time = ?",
                        (meeting_url, start_time))
                    if await cursor.fetchone():
                        continue
                    await conn.execute(
                        """INSERT INTO meetings
                           (subject, meeting_url, start_time, end_time,
                            duration_seconds, organizer, source, status)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (m.get("subject", ""), meeting_url, start_time,
                         m.get("end_time"), m.get("duration_seconds", 0),
                         m.get("organizer", ""), m.get("source", "synced"),
                         m.get("status", "scheduled")))
                    inserted += 1
                await conn.commit()
                await conn.close()
                return inserted

            if _loop and _loop.is_running():
                future = _aio.run_coroutine_threadsafe(_insert(), _loop)
                count = future.result(timeout=10)
            else:
                count = _aio.run(_insert())
            logger.info(f"Loaded {count} meetings from Saarthi into local DB")
        except Exception as e:
            logger.debug(f"Failed to load meetings from Saarthi: {e}")

    # ══════════════════════════════════════════════════════════════
    # TAB 2: Meetings (upcoming + past in one view)
    # ══════════════════════════════════════════════════════════════

    def _build_meetings_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=16)
        notebook.add(frame, text="  Meetings  ")

        # Loading indicator
        self._meetings_loading = ttk.Label(frame, text="Loading meetings...",
                                           foreground=TEXT_SEC, font=("Segoe UI", 9))
        self._meetings_loading.pack(anchor="w", pady=(0, 4))

        # ── Upcoming section ──
        ttk.Label(frame, text="Upcoming", style="Header.TLabel").pack(anchor="w", pady=(0, 6))

        up_frame = ttk.Frame(frame)
        up_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        cols = ("subject", "date", "duration", "status")
        self._upcoming_tree = ttk.Treeview(up_frame, columns=cols, show="headings", height=5)
        for col, w, label in [("subject", 300, "Subject"), ("date", 170, "Date"),
                               ("duration", 80, "Duration"), ("status", 100, "Status")]:
            self._upcoming_tree.heading(col, text=label)
            self._upcoming_tree.column(col, width=w, minwidth=50)
        vsb1 = ttk.Scrollbar(up_frame, orient=tk.VERTICAL, command=self._upcoming_tree.yview)
        self._upcoming_tree.configure(yscrollcommand=vsb1.set)
        self._upcoming_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb1.pack(side=tk.RIGHT, fill=tk.Y)

        # ── Past section ──
        ttk.Label(frame, text="Past", style="Header.TLabel").pack(anchor="w", pady=(4, 6))

        past_frame = ttk.Frame(frame)
        past_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        self._past_tree = ttk.Treeview(past_frame, columns=cols, show="headings", height=8)
        for col, w, label in [("subject", 300, "Subject"), ("date", 170, "Date"),
                               ("duration", 80, "Duration"), ("status", 100, "Status")]:
            self._past_tree.heading(col, text=label)
            self._past_tree.column(col, width=w, minwidth=50)
        vsb2 = ttk.Scrollbar(past_frame, orient=tk.VERTICAL, command=self._past_tree.yview)
        self._past_tree.configure(yscrollcommand=vsb2.set)
        self._past_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb2.pack(side=tk.RIGHT, fill=tk.Y)
        self._past_tree.bind("<Double-1>", self._open_recording)

        # Configure status tag colors
        for tree in (self._upcoming_tree, self._past_tree):
            for status, color in _STATUS_COLORS.items():
                tree.tag_configure(status, foreground=color)

        # Button row
        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(btn_row, text="Scan Emails Now", style="Primary.TButton",
                   command=self._scan_now).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Refresh", command=self._refresh_meetings).pack(side=tk.LEFT)

        # Auto-refresh every 60s
        self.root.after(60000, self._auto_refresh_meetings)

    def _refresh_meetings(self):
        """Load upcoming + past meetings in background."""
        from src.meeting_scheduler import get_upcoming_meetings, get_meeting_history

        async def _fetch():
            upcoming = await get_upcoming_meetings()
            history = await get_meeting_history(100)
            return (upcoming or [], history or [])

        def _update(data):
            if not data:
                self._meetings_loading.config(text="")
                return
            upcoming, history = data
            self._meetings_loading.config(text="")

            # Populate upcoming
            self._upcoming_tree.delete(*self._upcoming_tree.get_children())
            for m in upcoming:
                status = m.get("status", "scheduled")
                dur = f"{(m.get('duration_seconds', 0) or 0) // 60} min"
                self._upcoming_tree.insert("", tk.END, values=(
                    m.get("subject", ""), m.get("start_time", ""),
                    dur, status), tags=(status,))

            # Populate past
            self._past_tree.delete(*self._past_tree.get_children())
            for m in history:
                status = m.get("status", "")
                # Normalize pending_upload to recorded (upload is silent)
                if status == "pending_upload":
                    status = "recorded"
                dur = f"{(m.get('duration_seconds', 0) or 0) // 60} min"
                self._past_tree.insert("", tk.END, values=(
                    m.get("subject", ""), m.get("start_time", ""),
                    dur, status), tags=(status,))

        _run_async_bg(_fetch(), _update)

    def _scan_now(self):
        if not _scheduler:
            return
        from src.meeting_scheduler import scan_emails_and_schedule
        self._meetings_loading.config(text="Scanning emails...")
        _run_async_bg(scan_emails_and_schedule(_scheduler), lambda _: self._refresh_meetings())

    def _auto_refresh_meetings(self):
        self._refresh_meetings()
        self.root.after(60000, self._auto_refresh_meetings)

    def _open_recording(self, event):
        sel = self._past_tree.selection()
        if not sel:
            return
        # For past meetings, we need the recording path from db
        # The tree doesn't store paths visually, so we re-fetch
        values = self._past_tree.item(sel[0], "values")
        subject = values[0] if values else ""
        start_time = values[1] if len(values) > 1 else ""
        if subject and start_time:
            self._open_recording_folder(subject, start_time)

    def _open_recording_folder(self, subject: str, start_time: str):
        """Look up recording path from DB and open it."""
        async def _lookup():
            from src import db as _db
            conn = await _db.get_db()
            cursor = await conn.execute(
                "SELECT recording_path FROM meetings WHERE subject = ? AND start_time = ? LIMIT 1",
                (subject, start_time))
            row = await cursor.fetchone()
            await conn.close()
            return row[0] if row else None

        def _open(path):
            if path and os.path.isdir(path):
                _open_path(path)

        _run_async_bg(_lookup(), _open)

    # ══════════════════════════════════════════════════════════════
    # TAB 3: Settings
    # ══════════════════════════════════════════════════════════════

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
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
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
        testf = ttk.LabelFrame(inner, text="Audio Tests", padding=16)
        testf.pack(fill=tk.X, pady=(0, 12))

        mic_row = ttk.Frame(testf, style="Card.TFrame")
        mic_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(mic_row, text="Test Microphone", command=self._test_mic).pack(
            side=tk.LEFT, padx=(0, 12))
        self._mic_test_label = ttk.Label(mic_row, text="", font=("Segoe UI", 9), background=CARD_BG)
        self._mic_test_label.pack(side=tk.LEFT)

        spk_row = ttk.Frame(testf, style="Card.TFrame")
        spk_row.pack(fill=tk.X)
        ttk.Button(spk_row, text="Test Speaker", command=self._test_speaker).pack(
            side=tk.LEFT, padx=(0, 12))
        self._spk_test_label = ttk.Label(spk_row, text="", font=("Segoe UI", 9), background=CARD_BG)
        self._spk_test_label.pack(side=tk.LEFT)

        ttk.Label(testf,
                  text="Mic test scans devices for 1 second each. Speaker test plays a beep via WASAPI loopback.",
                  foreground=TEXT_SEC, background=CARD_BG, font=("Segoe UI", 8)).pack(
            anchor="w", pady=(10, 0))

        # ── Recording Output ──
        pathf = ttk.LabelFrame(inner, text="Recording Output", padding=16)
        pathf.pack(fill=tk.X, pady=(0, 12))

        from src.config import get_recording_config
        self._output_var = tk.StringVar(value=get_recording_config()["output_dir"])

        prow = ttk.Frame(pathf, style="Card.TFrame")
        prow.pack(fill=tk.X)
        ttk.Entry(prow, textvariable=self._output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(prow, text="Browse", command=self._browse_output).pack(side=tk.LEFT)

        # ── Hotkeys ──
        hkf = ttk.LabelFrame(inner, text="Hotkeys", padding=16)
        hkf.pack(fill=tk.X, pady=(0, 12))

        from src.config import get_tray_config
        tray_cfg = get_tray_config()

        ttk.Label(hkf, text="Dashboard:", background=CARD_BG).grid(
            row=0, column=0, sticky="w", padx=(0, 12), pady=6)
        self._hotkey_dashboard_var = tk.StringVar(value=tray_cfg["hotkey_toggle_dashboard"])
        ttk.Entry(hkf, textvariable=self._hotkey_dashboard_var, width=25).grid(
            row=0, column=1, sticky="w", pady=6)

        ttk.Label(hkf, text="Stop Recording:", background=CARD_BG).grid(
            row=1, column=0, sticky="w", padx=(0, 12), pady=6)
        self._hotkey_stop_var = tk.StringVar(value=tray_cfg["hotkey_stop_recording"])
        ttk.Entry(hkf, textvariable=self._hotkey_stop_var, width=25).grid(
            row=1, column=1, sticky="w", pady=6)

        ttk.Label(hkf, text="Format: ctrl+shift+m",
                  foreground=TEXT_SEC, background=CARD_BG, font=("Segoe UI", 8)).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        hkf.columnconfigure(1, weight=1)

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
        ttk.Checkbutton(notf, text="Notify when recording starts",
                        variable=self._notif_on_start).pack(anchor="w", pady=3)
        ttk.Checkbutton(notf, text="Notify when recording stops",
                        variable=self._notif_on_stop).pack(anchor="w", pady=3)

        # ── Upload Mode ──
        upf = ttk.LabelFrame(inner, text="Upload Mode", padding=16)
        upf.pack(fill=tk.X, pady=(0, 12))

        uprefs = load_user_prefs()
        current_mode = uprefs.get("saarthi_upload_mode", "auto")
        mode_map = {"auto": "Automatic", "manual": "Manual", "off": "Off"}
        self._upload_mode_var = tk.StringVar(value=mode_map.get(current_mode, "Automatic"))

        ttk.Label(upf, text="After recording, sync to Interview Saarthi:",
                  background=CARD_BG).pack(anchor="w", pady=(0, 6))
        upload_combo = ttk.Combobox(upf, textvariable=self._upload_mode_var,
                                    values=["Automatic", "Manual", "Off"],
                                    state="readonly", width=20)
        upload_combo.pack(anchor="w")

        self._auto_organize_var = tk.BooleanVar(value=uprefs.get("auto_organize_folders", True))
        ttk.Checkbutton(upf, text="Auto-organize folders by company/round",
                        variable=self._auto_organize_var).pack(anchor="w", pady=(10, 0))

        # ── Save ──
        ttk.Button(inner, text="Save Settings", style="Primary.TButton",
                   command=self._save_settings).pack(anchor="w", pady=(8, 0))

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
        """Smart mic test: scan all MME devices, find the one with audio, auto-select it."""
        self._mic_test_label.config(text="Testing microphone...", foreground="orange")

        def _run():
            try:
                import pyaudio
                import numpy as np
                p = pyaudio.PyAudio()
                mic_sel = self._mic_combo.current()

                if mic_sel > 0:
                    devices_to_try = [self._mic_devices[mic_sel - 1]["index"]]
                else:
                    devices_to_try = []
                    for i in range(p.get_device_count()):
                        info = p.get_device_info_by_index(i)
                        api = p.get_host_api_info_by_index(info['hostApi'])['name']
                        if info['maxInputChannels'] > 0 and 'MME' in api:
                            devices_to_try.append(i)

                best_rms, best_device, best_name = 0, None, ""

                for dev_idx in devices_to_try:
                    try:
                        info = p.get_device_info_by_index(dev_idx)
                        stream = p.open(format=pyaudio.paInt16, channels=1, rate=44100,
                                       input=True, input_device_index=dev_idx, frames_per_buffer=1024)
                        frames = []
                        for _ in range(int(44100 / 1024 * 1)):
                            frames.append(stream.read(1024, exception_on_overflow=False))
                        stream.stop_stream()
                        stream.close()
                        audio = np.frombuffer(b''.join(frames), dtype=np.int16)
                        rms = int(np.sqrt(np.mean(audio.astype(float)**2)))
                        if rms > best_rms:
                            best_rms, best_device, best_name = rms, dev_idx, info['name']
                    except Exception:
                        continue

                p.terminate()

                if best_rms > 10:
                    msg = f"Working! [{best_device}] {best_name} (RMS: {best_rms})"
                    self.root.after(0, lambda: self._mic_test_label.config(text=msg, foreground=SUCCESS))
                    if mic_sel == 0 and best_device is not None:
                        for i, d in enumerate(self._mic_devices):
                            if d["index"] == best_device:
                                self.root.after(0, lambda idx=i+1: self._mic_combo.current(idx))
                                break
                elif devices_to_try:
                    self.root.after(0, lambda: self._mic_test_label.config(
                        text="All mics silent — speak while testing", foreground="orange"))
                else:
                    self.root.after(0, lambda: self._mic_test_label.config(
                        text="No microphone devices found", foreground=DANGER))
            except Exception as e:
                err = str(e)[:60]
                self.root.after(0, lambda: self._mic_test_label.config(
                    text=f"Error: {err}", foreground=DANGER))

        threading.Thread(target=_run, daemon=True).start()

    def _test_speaker(self):
        """Speaker test using pyaudiowpatch WASAPI loopback."""
        self._spk_test_label.config(text="Playing tone & capturing...", foreground="orange")

        def _run():
            try:
                import pyaudiowpatch as pyaudio_wp
                import numpy as np
                import winsound
                import time

                p = pyaudio_wp.PyAudio()
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
                        text="No loopback device found", foreground=DANGER))
                    return

                ch = loopback['maxInputChannels']
                sr = int(loopback['defaultSampleRate'])
                frames = []

                def callback(in_data, frame_count, time_info, status):
                    if in_data:
                        frames.append(in_data)
                    return (None, pyaudio_wp.paContinue)

                stream = p.open(format=pyaudio_wp.paInt16, channels=ch, rate=sr,
                               input=True, input_device_index=loopback['index'],
                               frames_per_buffer=512, stream_callback=callback)

                beep_thread = threading.Thread(target=lambda: winsound.Beep(440, 2000), daemon=True)
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
                            text=f"OK (RMS: {rms})", foreground=SUCCESS))
                    else:
                        self.root.after(0, lambda: self._spk_test_label.config(
                            text=f"Silent (RMS: {rms})", foreground="orange"))
                else:
                    self.root.after(0, lambda: self._spk_test_label.config(
                        text="No audio captured", foreground=DANGER))
            except ImportError:
                self.root.after(0, lambda: self._spk_test_label.config(
                    text="Install pyaudiowpatch for speaker test", foreground=DANGER))
            except Exception as e:
                self.root.after(0, lambda: self._spk_test_label.config(
                    text=f"Failed: {str(e)[:50]}", foreground=DANGER))

        threading.Thread(target=_run, daemon=True).start()

    def _browse_output(self):
        path = filedialog.askdirectory(initialdir=self._output_var.get())
        if path:
            self._output_var.set(path)

    def _save_settings(self):
        from src.config import save_user_prefs
        mic_sel = self._mic_combo.current()
        spk_sel = self._spk_combo.current()

        # Map upload dropdown back to internal key
        mode_rmap = {"Automatic": "auto", "Manual": "manual", "Off": "off"}
        upload_mode = mode_rmap.get(self._upload_mode_var.get(), "auto")

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
            "saarthi_upload_mode": upload_mode,
            "auto_organize_folders": self._auto_organize_var.get(),
        }
        save_user_prefs(prefs)
        logger.info(f"Settings saved: upload_mode={upload_mode}")

        # Re-register hotkeys immediately
        try:
            import keyboard as kb_lib
            kb_lib.unhook_all()
            from src.gui_dashboard import toggle_dashboard
            from src.tray_app import _on_stop_recording
            dk = prefs["hotkeys"]["dashboard"]
            sk = prefs["hotkeys"]["stop_recording"]
            if dk:
                kb_lib.add_hotkey(dk, toggle_dashboard)
            if sk:
                kb_lib.add_hotkey(sk, lambda: _on_stop_recording(None, None))
            logger.info(f"Hotkeys reloaded: dashboard={dk}, stop={sk}")
        except Exception as e:
            logger.warning(f"Could not reload hotkeys: {e}")

    # ══════════════════════════════════════════════════════════════
    # TAB 4: About
    # ══════════════════════════════════════════════════════════════

    def _build_about_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=24)
        notebook.add(frame, text="  About  ")

        ttk.Label(frame, text="Interview Saarthi Recorder",
                  font=("Segoe UI", 16, "bold"), foreground=PRIMARY).pack(anchor="w", pady=(0, 4))
        ttk.Label(frame, text="v2.1.0",
                  foreground=TEXT_SEC, font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 16))

        ttk.Label(frame, text="Record your interviews automatically. Mic + speaker + screen.",
                  font=("Segoe UI", 10), foreground=TEXT).pack(anchor="w", pady=(0, 24))

        link_btn = ttk.Button(frame, text="Open Interview Saarthi website",
                              command=lambda: _open_path("https://interview-intelligence-production-7e43.up.railway.app"))
        link_btn.pack(anchor="w", pady=(0, 12))

        btn_row = ttk.Frame(frame)
        btn_row.pack(anchor="w", pady=(8, 0))

        ttk.Button(btn_row, text="Restart", command=self._restart_app).pack(
            side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Check for Updates",
                   command=lambda: _open_path("https://interview-intelligence-production-7e43.up.railway.app/download")).pack(
            side=tk.LEFT)

    # ── Window management ─────────────────────────────────────────

    def _restart_app(self):
        self.root.destroy()
        os.execv(sys.executable, [sys.executable] + sys.argv)

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
