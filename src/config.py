"""Central configuration loader — reads config.yaml + user_prefs.yaml."""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "data" / "config.yaml"
USER_PREFS_PATH = BASE_DIR / "data" / "user_prefs.yaml"
DB_PATH = BASE_DIR / "data" / "meetings.db"
LOG_PATH = BASE_DIR / "data" / "recorder.log"

(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load config.yaml as the base configuration."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def load_user_prefs() -> dict:
    """Load user_prefs.yaml (GUI-writable overrides)."""
    if USER_PREFS_PATH.exists():
        with open(USER_PREFS_PATH, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_user_prefs(prefs: dict):
    """Save user_prefs.yaml (GUI-writable overrides). Merges with existing."""
    existing = load_user_prefs()
    existing.update(prefs)
    with open(USER_PREFS_PATH, "w") as f:
        yaml.safe_dump(existing, f, default_flow_style=False)


def get_email_accounts() -> list[dict]:
    cfg = load_config()
    accounts = cfg.get("email_accounts", [])
    return [a for a in accounts if a.get("enabled", True)]


def get_recording_config() -> dict:
    cfg = load_config()
    prefs = load_user_prefs()
    rec = cfg.get("recording", {})
    # User prefs override config.yaml
    rec_prefs = prefs.get("recording", {})
    return {
        "output_dir": rec_prefs.get("output_dir", rec.get("output_dir", str(BASE_DIR / "data" / "recordings"))),
        "record_mic": rec.get("record_mic", True),
        "record_speaker": rec.get("record_speaker", True),
        "record_screen": rec.get("record_screen", True),
        "video_fps": rec.get("video_fps", 10),
        "auto_open_meeting": rec.get("auto_open_meeting", False),
    }


def get_device_config() -> dict:
    """Return audio device overrides. None means auto-detect."""
    cfg = load_config()
    prefs = load_user_prefs()
    dev = cfg.get("devices", {})
    dev_prefs = prefs.get("devices", {})
    return {
        "mic_index": dev_prefs.get("mic_index", dev.get("mic_index")),
        "speaker_index": dev_prefs.get("speaker_index", dev.get("speaker_index")),
    }


def get_scheduler_config() -> dict:
    cfg = load_config()
    sched = cfg.get("scheduler", {})
    return {
        "timezone": sched.get("timezone", "UTC"),
        "scan_cron": sched.get("scan_cron", "*/15 * * * *"),
        "pre_meeting_buffer_min": sched.get("pre_meeting_buffer_min", 1),
        "default_duration_min": sched.get("default_duration_min", 90),
        "max_emails_to_scan": sched.get("max_emails_to_scan", 100),
    }


def get_tray_config() -> dict:
    cfg = load_config()
    tray = cfg.get("tray", {})
    return {
        "hotkey_toggle_dashboard": tray.get("hotkey_toggle_dashboard", "<ctrl>+<shift>+m"),
        "hotkey_stop_recording": tray.get("hotkey_stop_recording", "<ctrl>+<shift>+s"),
        "show_notifications": tray.get("show_notifications", True),
    }
