"""System tray application — runs hidden, provides hotkeys and launches dashboard."""

import asyncio
import logging
import os
import subprocess
import sys
import threading

import pystray
from PIL import Image, ImageDraw
from pystray import MenuItem, Menu

from src.config import BASE_DIR, get_tray_config, get_recording_config, CONFIG_PATH
from src.notifier import set_tray_icon, notify
from src.meeting_scheduler import pause_scanning, resume_scanning, is_scanning_paused

logger = logging.getLogger(__name__)

_tray_icon: pystray.Icon = None
_event_loop: asyncio.AbstractEventLoop = None


def _create_icon_image(recording: bool = False) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = (220, 40, 40) if recording else (60, 160, 60)
    draw.ellipse([8, 8, 56, 56], fill=color)
    draw.ellipse([20, 20, 44, 44], fill=(255, 255, 255))
    if recording:
        draw.ellipse([26, 26, 38, 38], fill=(220, 40, 40))
    return img


def update_tray_icon(recording: bool = False):
    if _tray_icon:
        _tray_icon.icon = _create_icon_image(recording)
        status = "Recording..." if recording else "Idle"
        _tray_icon.title = f"Meeting Recorder — {status}"


def _open_path(path: str):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ── Menu Callbacks ────────────────────────────────────────────────────

def _on_show_dashboard(icon, item):
    from src.gui_dashboard import toggle_dashboard
    toggle_dashboard()


def _on_pause_resume(icon, item):
    if is_scanning_paused():
        resume_scanning()
        notify("Scanning Resumed", "Email scanning is active again.")
    else:
        pause_scanning()
        notify("Scanning Paused", "Email scanning is paused.")


def _on_stop_recording(icon, item):
    from src.meeting_recorder import get_active_recorder
    recorder = get_active_recorder()
    if recorder and recorder.is_recording:
        recorder.stop_recording()
        update_tray_icon(recording=False)
        notify("Recording Stopped", "Meeting recording stopped manually.")
    else:
        notify("No Recording", "No meeting is being recorded right now.")


def _on_open_recordings(icon, item):
    path = get_recording_config()["output_dir"]
    if os.path.isdir(path):
        _open_path(path)


def _on_open_config(icon, item):
    _open_path(str(CONFIG_PATH))


def _on_reload_config(icon, item):
    notify("Config Reloaded", "Configuration reloaded from config.yaml")


def _on_quit(icon, item):
    logger.info("Quit requested from tray")
    icon.stop()
    if _event_loop and _event_loop.is_running():
        _event_loop.call_soon_threadsafe(_event_loop.stop)


def _pause_label(item):
    return "Resume Scanning" if is_scanning_paused() else "Pause Scanning"


def create_tray_menu() -> Menu:
    return Menu(
        MenuItem("Show Dashboard", _on_show_dashboard, default=True),
        Menu.SEPARATOR,
        MenuItem(_pause_label, _on_pause_resume),
        MenuItem("Stop Current Recording", _on_stop_recording),
        Menu.SEPARATOR,
        MenuItem("Open Recordings Folder", _on_open_recordings),
        MenuItem("Edit Config", _on_open_config),
        MenuItem("Reload Config", _on_reload_config),
        Menu.SEPARATOR,
        MenuItem("Quit", _on_quit),
    )


# ── Hotkeys ───────────────────────────────────────────────────────────

def _pynput_to_keyboard_fmt(hotkey: str) -> str:
    """Convert pynput format '<ctrl>+<shift>+m' to keyboard format 'ctrl+shift+m'."""
    return hotkey.replace("<", "").replace(">", "")


def _setup_hotkeys():
    """Register global hotkeys. Tries 'keyboard' lib first (Windows), falls back to pynput."""
    cfg = get_tray_config()

    from src.gui_dashboard import toggle_dashboard
    dashboard_key = _pynput_to_keyboard_fmt(cfg["hotkey_toggle_dashboard"])
    stop_key = _pynput_to_keyboard_fmt(cfg["hotkey_stop_recording"])

    # Strategy 1: keyboard library (works best on Windows)
    try:
        import keyboard as kb_lib

        kb_lib.add_hotkey(dashboard_key, toggle_dashboard)
        kb_lib.add_hotkey(stop_key, lambda: _on_stop_recording(None, None))
        logger.info(f"Hotkeys registered (keyboard lib): dashboard={dashboard_key}, stop={stop_key}")
        return
    except ImportError:
        logger.debug("'keyboard' library not available, trying pynput")
    except Exception as e:
        logger.warning(f"keyboard lib hotkey registration failed: {e}")

    # Strategy 2: pynput (cross-platform fallback)
    try:
        from pynput import keyboard as pynput_kb

        hotkeys = {
            cfg["hotkey_toggle_dashboard"]: toggle_dashboard,
            cfg["hotkey_stop_recording"]: lambda: _on_stop_recording(None, None),
        }
        listener = pynput_kb.GlobalHotKeys(hotkeys)
        listener.daemon = True
        listener.start()
        logger.info(f"Hotkeys registered (pynput): {list(hotkeys.keys())}")
    except ImportError:
        logger.warning("No hotkey library available. Install 'keyboard' or 'pynput'.")
    except Exception as e:
        logger.warning(f"pynput hotkey registration failed: {e}")


# ── Entry Point ───────────────────────────────────────────────────────

def start_tray(event_loop: asyncio.AbstractEventLoop, scheduler=None):
    """Start the system tray icon. Call from the main thread."""
    global _tray_icon, _event_loop
    _event_loop = event_loop

    # Initialize GUI dashboard in background thread
    from src.gui_dashboard import init_dashboard
    init_dashboard(event_loop, scheduler)

    _setup_hotkeys()

    _tray_icon = pystray.Icon(
        name="MeetingRecorder",
        icon=_create_icon_image(recording=False),
        title="Meeting Recorder — Idle",
        menu=create_tray_menu(),
    )
    set_tray_icon(_tray_icon)

    logger.info("System tray started")
    _tray_icon.run()
