"""Meeting recorder — wraps recordmymeeting with config-driven settings.

recordmymeeting handles audio device hot-swap detection internally
(checks every 2 seconds). This module reads config for device overrides,
output path, and recording preferences.
"""

import asyncio
import logging
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

from recordmymeeting.core import RecordMyMeeting

from src.config import get_recording_config, get_device_config

logger = logging.getLogger(__name__)


def _sanitize_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()[:80]


def _get_output_dir() -> str:
    cfg = get_recording_config()
    out = cfg["output_dir"]
    Path(out).mkdir(parents=True, exist_ok=True)
    return out


def list_audio_devices() -> dict:
    """List available audio devices for the GUI device selector."""
    try:
        from recordmymeeting.device_manager import list_audio_devices as _list
        return _list()
    except Exception as e:
        logger.error(f"Failed to list audio devices: {e}")
        return {"microphones": [], "speakers": []}


class MeetingRecorder:
    """Records mic + speaker + screen during a meeting.

    - Uses recordmymeeting for system audio/screen capture
    - Auto-detects device changes (headphone <-> speaker swap) every 2s
    - Reads settings from config.yaml + user_prefs.yaml
    - Accepts manual device overrides via config
    """

    def __init__(
        self,
        meeting_url: str,
        subject: str = "meeting",
        output_dir: Optional[str] = None,
        mic_index: Optional[int] = None,
        speaker_index: Optional[int] = None,
    ):
        self.meeting_url = meeting_url
        self.subject = subject
        cfg = get_recording_config()
        dev_cfg = get_device_config()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_name = f"{timestamp}_{_sanitize_filename(subject)}"
        self.output_dir = output_dir or _get_output_dir()
        self._auto_open = cfg["auto_open_meeting"]

        # Device indices: explicit arg > user_prefs > config.yaml > auto-detect (None)
        mic = mic_index if mic_index is not None else dev_cfg.get("mic_index")
        spk = speaker_index if speaker_index is not None else dev_cfg.get("speaker_index")

        self.recorder = RecordMyMeeting(
            output_dir=self.output_dir,
            mic_index=mic,
            speaker_index=spk,
            record_mic=cfg["record_mic"],
            record_speaker=cfg["record_speaker"],
            record_screen=cfg["record_screen"],
            video_fps=cfg["video_fps"],
            session_name=session_name,
        )
        self._recording = False

    def open_meeting_in_browser(self):
        if self._auto_open and self.meeting_url:
            logger.info(f"Opening meeting in browser: {self.meeting_url}")
            webbrowser.open(self.meeting_url)

    def start_recording(self):
        if self._recording:
            logger.warning("Already recording")
            return
        logger.info(f"Recording started: {self.subject}")
        self.recorder.start()
        self._recording = True

    def stop_recording(self) -> dict:
        if not self._recording:
            return {}
        logger.info("Stopping recording...")
        self.recorder.stop(save_output=True)
        self._recording = False
        status = self.recorder.get_status()
        logger.info(f"Recording saved: {status.get('session_folder', 'unknown')}")
        return status

    @property
    def is_recording(self) -> bool:
        return self._recording

    async def record_meeting(self, duration_seconds: Optional[int] = None) -> dict:
        """Full flow: open meeting URL, record for duration, stop."""
        try:
            self.open_meeting_in_browser()
            self.start_recording()

            if duration_seconds:
                logger.info(f"Recording for {duration_seconds // 60} min...")
                await asyncio.sleep(duration_seconds)
            else:
                logger.info("Recording indefinitely. Stop via hotkey or tray.")
                try:
                    while self._recording:
                        await asyncio.sleep(10)
                except asyncio.CancelledError:
                    pass
        finally:
            result = self.stop_recording()
            return result


# Global reference to current recorder (for hotkey stop / GUI)
_active_recorder: Optional[MeetingRecorder] = None


def get_active_recorder() -> Optional[MeetingRecorder]:
    return _active_recorder


def set_active_recorder(recorder: Optional[MeetingRecorder]):
    global _active_recorder
    _active_recorder = recorder


async def record_meeting_now(
    meeting_url: str,
    subject: str = "meeting",
    duration_seconds: Optional[int] = None,
) -> dict:
    recorder = MeetingRecorder(meeting_url=meeting_url, subject=subject)
    set_active_recorder(recorder)
    try:
        return await recorder.record_meeting(duration_seconds=duration_seconds)
    finally:
        set_active_recorder(None)
