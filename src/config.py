"""Central configuration loader — reads config.yaml (single source of truth)."""

import os
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "data" / "config.yaml"
DB_PATH = BASE_DIR / "data" / "meetings.db"
LOG_PATH = BASE_DIR / "data" / "recorder.log"

# Ensure data directory exists
(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load config.yaml. This is the single source of truth for all settings."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def get_email_accounts() -> list[dict]:
    """Return list of enabled email accounts from config."""
    cfg = load_config()
    accounts = cfg.get("email_accounts", [])
    return [a for a in accounts if a.get("enabled", True)]


def get_recording_config() -> dict:
    """Return recording settings with defaults."""
    cfg = load_config()
    rec = cfg.get("recording", {})
    return {
        "output_dir": rec.get("output_dir", str(BASE_DIR / "data" / "recordings")),
        "record_mic": rec.get("record_mic", True),
        "record_speaker": rec.get("record_speaker", True),
        "record_screen": rec.get("record_screen", True),
        "video_fps": rec.get("video_fps", 10),
        "auto_open_meeting": rec.get("auto_open_meeting", True),
    }


def get_scheduler_config() -> dict:
    """Return scheduler settings with defaults."""
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
    """Return tray/hotkey settings with defaults."""
    cfg = load_config()
    tray = cfg.get("tray", {})
    return {
        "hotkey_toggle_dashboard": tray.get("hotkey_toggle_dashboard", "ctrl+shift+m"),
        "hotkey_stop_recording": tray.get("hotkey_stop_recording", "ctrl+shift+s"),
        "show_notifications": tray.get("show_notifications", True),
    }
