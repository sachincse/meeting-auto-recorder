"""Cross-platform desktop notifications."""

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

_IS_WIN = sys.platform == "win32"
_IS_MAC = sys.platform == "darwin"

# Tray icon reference (set by tray_app.py)
_tray_icon = None


def set_tray_icon(icon):
    global _tray_icon
    _tray_icon = icon


def notify(title: str, message: str):
    """Show a desktop notification. Uses tray icon on Windows, osascript on macOS."""
    try:
        if _IS_WIN and _tray_icon:
            _tray_icon.notify(message, title)
        elif _IS_MAC:
            subprocess.Popen([
                "osascript", "-e",
                f'display notification "{message}" with title "{title}"'
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            logger.info(f"[Notification] {title}: {message}")
    except Exception as e:
        logger.debug(f"Notification failed: {e}")
