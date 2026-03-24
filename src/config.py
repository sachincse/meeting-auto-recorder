"""Central configuration loader — reads .env and config.yaml."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def load_config() -> dict:
    config_path = BASE_DIR / "data" / "config.yaml"
    if config_path.exists():
        with open(config_path, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


# IMAP (email reading for meeting invites)
IMAP_HOST = env("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = env("IMAP_PORT", "993")
IMAP_USER = env("IMAP_USER")
IMAP_PASS = env("IMAP_PASS")
IMAP_FOLDER = env("IMAP_FOLDER", "INBOX")

# Recording settings
RECORDING_FPS = int(env("RECORDING_FPS", "10"))
MEETING_HEADLESS = env_bool("MEETING_HEADLESS", True)

# Database
DB_PATH = BASE_DIR / "data" / "meetings.db"
