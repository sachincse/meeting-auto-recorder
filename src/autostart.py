"""Windows auto-start management — adds/removes from Startup via registry + VBS."""

import logging
import os
import sys
import winreg
from pathlib import Path

from src.config import BASE_DIR

logger = logging.getLogger(__name__)

APP_NAME = "MeetingAutoRecorder"
STARTUP_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"


def _get_pythonw_path() -> str:
    """Get path to pythonw.exe (windowless Python) next to current python.exe."""
    python_dir = Path(sys.executable).parent
    pythonw = python_dir / "pythonw.exe"
    if pythonw.exists():
        return str(pythonw)
    return sys.executable


def _get_vbs_path() -> Path:
    """Path to the VBS launcher script that starts the app hidden."""
    return BASE_DIR / "start_hidden.vbs"


def _create_vbs_launcher():
    """Create a VBS script that launches the app with no visible window."""
    vbs_path = _get_vbs_path()
    pythonw = _get_pythonw_path()
    main_py = str(BASE_DIR / "main.py")

    vbs_content = f'''Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """{pythonw}"" ""{main_py}"" --tray", 0, False
'''
    vbs_path.write_text(vbs_content)
    logger.info(f"Created VBS launcher: {vbs_path}")
    return str(vbs_path)


def enable_autostart():
    """Add Meeting Auto-Recorder to Windows startup (runs hidden)."""
    vbs_path = _create_vbs_launcher()

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'wscript.exe "{vbs_path}"')
        winreg.CloseKey(key)
        logger.info(f"Auto-start enabled: {APP_NAME}")
        return True
    except Exception as e:
        logger.error(f"Failed to enable auto-start: {e}")
        return False


def disable_autostart():
    """Remove Meeting Auto-Recorder from Windows startup."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, APP_NAME)
        winreg.CloseKey(key)
        logger.info(f"Auto-start disabled: {APP_NAME}")

        vbs_path = _get_vbs_path()
        if vbs_path.exists():
            vbs_path.unlink()

        return True
    except FileNotFoundError:
        logger.info("Auto-start was not enabled")
        return True
    except Exception as e:
        logger.error(f"Failed to disable auto-start: {e}")
        return False


def is_autostart_enabled() -> bool:
    """Check if auto-start is currently enabled."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False
