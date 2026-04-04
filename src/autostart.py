"""Cross-platform auto-start management (Windows registry + macOS launchd)."""

import logging
import os
import sys
from pathlib import Path

from src.config import BASE_DIR

logger = logging.getLogger(__name__)

APP_NAME = "MeetingAutoRecorder"
_IS_WIN = sys.platform == "win32"
_IS_MAC = sys.platform == "darwin"


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

def _win_get_pythonw() -> str:
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    return str(pythonw) if pythonw.exists() else sys.executable


def _win_vbs_path() -> Path:
    return BASE_DIR / "start_hidden.vbs"


def _win_create_vbs():
    vbs = _win_vbs_path()
    pythonw = _win_get_pythonw()
    main_py = str(BASE_DIR / "main.py")
    vbs.write_text(
        f'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.Run """{pythonw}"" ""{main_py}"" --tray", 0, False\n'
    )
    return str(vbs)


def _win_enable():
    import winreg
    vbs = _win_create_vbs()
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                         0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'wscript.exe "{vbs}"')
    winreg.CloseKey(key)
    return True


def _win_disable():
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, APP_NAME)
        winreg.CloseKey(key)
    except FileNotFoundError:
        pass
    vbs = _win_vbs_path()
    if vbs.exists():
        vbs.unlink()
    return True


def _win_is_enabled() -> bool:
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except (FileNotFoundError, OSError):
        return False


# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------

_PLIST_NAME = "com.meetingrecorder.autostart"


def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_PLIST_NAME}.plist"


def _mac_enable():
    python = sys.executable
    main_py = str(BASE_DIR / "main.py")
    log_path = str(BASE_DIR / "data" / "launchd.log")
    plist = _mac_plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{main_py}</string>
        <string>--tray</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
</dict>
</plist>
""")
    os.system(f"launchctl load '{plist}'")
    return True


def _mac_disable():
    plist = _mac_plist_path()
    if plist.exists():
        os.system(f"launchctl unload '{plist}'")
        plist.unlink()
    return True


def _mac_is_enabled() -> bool:
    return _mac_plist_path().exists()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enable_autostart() -> bool:
    try:
        if _IS_WIN:
            return _win_enable()
        elif _IS_MAC:
            return _mac_enable()
        else:
            logger.warning("Auto-start not supported on this platform")
            return False
    except Exception as e:
        logger.error(f"Failed to enable auto-start: {e}")
        return False


def disable_autostart() -> bool:
    try:
        if _IS_WIN:
            return _win_disable()
        elif _IS_MAC:
            return _mac_disable()
        else:
            return False
    except Exception as e:
        logger.error(f"Failed to disable auto-start: {e}")
        return False


def is_autostart_enabled() -> bool:
    try:
        if _IS_WIN:
            return _win_is_enabled()
        elif _IS_MAC:
            return _mac_is_enabled()
        else:
            return False
    except Exception:
        return False
