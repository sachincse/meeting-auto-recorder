"""Cross-platform desktop notifications with user preference controls.

Notifications are SILENT by default to avoid interrupting meetings/screenshare.
Users can opt-in to start/stop notifications in Settings.
"""

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

_IS_WIN = sys.platform == "win32"
_IS_MAC = sys.platform == "darwin"
_tray_icon = None


def set_tray_icon(icon):
    global _tray_icon
    _tray_icon = icon


def _get_notification_prefs() -> dict:
    """Load notification preferences. Returns defaults if not configured."""
    try:
        from src.config import load_user_prefs
        prefs = load_user_prefs()
        return prefs.get("notifications", {})
    except Exception:
        return {}


def notify(title: str, message: str, event: str = "general"):
    """Show a desktop notification if the user has opted in.

    Args:
        title: Notification title
        message: Notification body
        event: "start" (recording started), "stop" (recording stopped), "general" (other)
    """
    prefs = _get_notification_prefs()

    # Check if notifications are globally disabled
    if not prefs.get("enabled", True):
        logger.debug(f"[Notification suppressed] {title}: {message}")
        return

    # Check event-specific preferences (default: off for start/stop to avoid interruption)
    if event == "start" and not prefs.get("on_start", False):
        logger.debug(f"[Start notification suppressed] {title}: {message}")
        return
    if event == "stop" and not prefs.get("on_stop", False):
        logger.debug(f"[Stop notification suppressed] {title}: {message}")
        return

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
