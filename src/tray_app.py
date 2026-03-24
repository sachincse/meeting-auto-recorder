"""System tray application — runs hidden, provides hotkeys and status dashboard."""

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path

import pystray
from PIL import Image, ImageDraw
from pystray import MenuItem, Menu

from src.config import BASE_DIR, get_tray_config, get_recording_config, CONFIG_PATH

logger = logging.getLogger(__name__)

# Global references
_tray_icon: pystray.Icon = None
_event_loop: asyncio.AbstractEventLoop = None
_dashboard_visible = False


def _create_icon_image(recording: bool = False) -> Image.Image:
    """Create a simple tray icon — green circle when idle, red when recording."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = (220, 40, 40) if recording else (60, 160, 60)
    draw.ellipse([8, 8, 56, 56], fill=color)
    # White inner circle
    draw.ellipse([20, 20, 44, 44], fill=(255, 255, 255))
    if recording:
        # Red dot in center when recording
        draw.ellipse([26, 26, 38, 38], fill=(220, 40, 40))
    return img


def update_tray_icon(recording: bool = False):
    """Update the tray icon to reflect recording state."""
    global _tray_icon
    if _tray_icon:
        _tray_icon.icon = _create_icon_image(recording)
        status = "Recording..." if recording else "Idle — monitoring emails"
        _tray_icon.title = f"Meeting Recorder — {status}"


def show_notification(title: str, message: str):
    """Show a Windows toast notification via the tray icon."""
    cfg = get_tray_config()
    if not cfg["show_notifications"]:
        return
    if _tray_icon:
        try:
            _tray_icon.notify(message, title)
        except Exception as e:
            logger.debug(f"Notification failed: {e}")


def _on_show_dashboard(icon, item):
    """Show status in a console window."""
    _show_dashboard()


def _show_dashboard():
    """Print status dashboard to a popup console."""
    from src.meeting_recorder import get_active_recorder

    recorder = get_active_recorder()
    rec_cfg = get_recording_config()

    lines = [
        "=" * 50,
        "  MEETING AUTO-RECORDER STATUS",
        "=" * 50,
        "",
        f"  Recording:    {'YES' if (recorder and recorder.is_recording) else 'No'}",
        f"  Output Dir:   {rec_cfg['output_dir']}",
        f"  Config File:  {CONFIG_PATH}",
        "",
    ]

    if recorder and recorder.is_recording:
        lines.append(f"  Current:      {recorder.subject}")
        lines.append(f"  Meeting URL:  {recorder.meeting_url}")

    lines.extend([
        "",
        "  Hotkeys:",
        f"    Toggle Dashboard:  {get_tray_config()['hotkey_toggle_dashboard']}",
        f"    Stop Recording:    {get_tray_config()['hotkey_stop_recording']}",
        "",
        "=" * 50,
    ])

    print("\n".join(lines))


def _on_open_recordings(icon, item):
    rec_cfg = get_recording_config()
    output_dir = rec_cfg["output_dir"]
    if os.path.isdir(output_dir):
        os.startfile(output_dir)


def _on_open_config(icon, item):
    os.startfile(str(CONFIG_PATH))


def _on_reload_config(icon, item):
    show_notification("Config Reloaded", "Configuration has been reloaded from config.yaml")
    logger.info("Configuration reloaded")


def _on_stop_recording(icon, item):
    from src.meeting_recorder import get_active_recorder
    recorder = get_active_recorder()
    if recorder and recorder.is_recording:
        recorder.stop_recording()
        update_tray_icon(recording=False)
        show_notification("Recording Stopped", "Meeting recording stopped manually.")
        logger.info("Recording stopped via tray menu")
    else:
        show_notification("No Active Recording", "No meeting is being recorded right now.")


def _on_quit(icon, item):
    logger.info("Quit requested from tray")
    icon.stop()
    # Signal the event loop to stop
    if _event_loop and _event_loop.is_running():
        _event_loop.call_soon_threadsafe(_event_loop.stop)


def _setup_hotkeys():
    """Register global hotkeys in a background thread."""
    try:
        import keyboard
    except ImportError:
        logger.warning("'keyboard' package not installed — hotkeys disabled")
        return

    cfg = get_tray_config()

    def _toggle_dashboard():
        _show_dashboard()

    def _emergency_stop():
        _on_stop_recording(None, None)

    try:
        keyboard.add_hotkey(cfg["hotkey_toggle_dashboard"], _toggle_dashboard)
        keyboard.add_hotkey(cfg["hotkey_stop_recording"], _emergency_stop)
        logger.info(
            f"Hotkeys registered: dashboard={cfg['hotkey_toggle_dashboard']}, "
            f"stop={cfg['hotkey_stop_recording']}"
        )
    except Exception as e:
        logger.warning(f"Failed to register hotkeys: {e}")


def create_tray_menu() -> Menu:
    return Menu(
        MenuItem("Status Dashboard", _on_show_dashboard),
        Menu.SEPARATOR,
        MenuItem("Stop Current Recording", _on_stop_recording),
        Menu.SEPARATOR,
        MenuItem("Open Recordings Folder", _on_open_recordings),
        MenuItem("Edit Config", _on_open_config),
        MenuItem("Reload Config", _on_reload_config),
        Menu.SEPARATOR,
        MenuItem("Quit", _on_quit),
    )


def start_tray(event_loop: asyncio.AbstractEventLoop):
    """Start the system tray icon. Call from the main thread."""
    global _tray_icon, _event_loop
    _event_loop = event_loop

    _setup_hotkeys()

    _tray_icon = pystray.Icon(
        name="MeetingRecorder",
        icon=_create_icon_image(recording=False),
        title="Meeting Recorder — Idle",
        menu=create_tray_menu(),
    )

    logger.info("System tray started")
    _tray_icon.run()
