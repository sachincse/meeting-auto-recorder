# PyInstaller spec for Meeting Auto-Recorder (Interview Saarthi Recorder)
# Build with: pyinstaller build_installer.spec

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('data/config.yaml', 'data'),
        ('src', 'src'),
    ],
    hiddenimports=[
        'pystray._win32',
        'PIL._tkinter_finder',
        'engineio.async_drivers.threading',
        'recordmymeeting',
        'recordmymeeting.core',
        'recordmymeeting.device_manager',
        'icalendar',
        'pyaudio',
        'mss',
        'cv2',
        'numpy',
        'yaml',
        'apscheduler',
        'apscheduler.schedulers.asyncio',
        'apscheduler.triggers.cron',
        'apscheduler.triggers.date',
        'pynput',
        'pynput.keyboard',
        'keyboard',
        'httpx',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='InterviewSaarthiRecorder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window — runs in tray
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add icon later
)
