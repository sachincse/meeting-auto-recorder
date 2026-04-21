# PyInstaller spec for Meeting Auto-Recorder (Interview Saarthi Recorder) — macOS
# Build with: pyinstaller build_installer_macos.spec

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
        'pystray._darwin',
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
        'pynput.keyboard._darwin',
        'pynput.mouse._darwin',
        'httpx',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='InterviewSaarthiRecorder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='InterviewSaarthiRecorder',
)

app = BUNDLE(
    coll,
    name='InterviewSaarthiRecorder.app',
    icon=None,
    bundle_identifier='com.interviewsaarthi.recorder',
)
