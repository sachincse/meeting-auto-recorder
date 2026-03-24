"""Meeting recorder — uses recordmymeeting to capture mic, speaker, and screen."""

import asyncio
import logging
import webbrowser
from datetime import datetime
from typing import Optional

from recordmymeeting.core import RecordMyMeeting

from src.config import BASE_DIR, env_bool, RECORDING_FPS

logger = logging.getLogger(__name__)

RECORDINGS_DIR = BASE_DIR / "data" / "recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_filename(name: str) -> str:
    """Remove characters that are invalid in filenames."""
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()[:80]


class MeetingRecorder:
    """Records mic + speaker + screen during a meeting.

    recordmymeeting captures the actual system audio devices and screen,
    so the user joins the meeting in their normal browser/app. This recorder
    just starts/stops the capture around the scheduled time.
    """

    def __init__(
        self,
        meeting_url: str,
        subject: str = "meeting",
        record_mic: bool = True,
        record_speaker: bool = True,
        record_screen: bool = True,
        output_dir: Optional[str] = None,
    ):
        self.meeting_url = meeting_url
        self.subject = subject

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_name = f"{timestamp}_{_sanitize_filename(subject)}"
        self.output_dir = output_dir or str(RECORDINGS_DIR)

        self.recorder = RecordMyMeeting(
            output_dir=self.output_dir,
            record_mic=record_mic,
            record_speaker=record_speaker,
            record_screen=record_screen,
            video_fps=RECORDING_FPS,
            session_name=session_name,
        )
        self._recording = False

    def open_meeting_in_browser(self):
        """Open the meeting URL in the user's default browser."""
        auto_open = env_bool("AUTO_OPEN_MEETING", True)
        if auto_open and self.meeting_url:
            logger.info(f"Opening meeting in browser: {self.meeting_url}")
            webbrowser.open(self.meeting_url)

    def start_recording(self):
        """Start recording mic, speaker, and screen."""
        if self._recording:
            logger.warning("Already recording")
            return
        logger.info(f"Starting recording for: {self.subject}")
        self.recorder.start()
        self._recording = True
        logger.info("Recording started (mic + speaker + screen)")

    def stop_recording(self) -> dict:
        """Stop recording and return file paths."""
        if not self._recording:
            logger.warning("Not recording")
            return {}
        logger.info("Stopping recording...")
        self.recorder.stop(save_output=True)
        self._recording = False
        status = self.recorder.get_status()
        logger.info(f"Recording saved: {status}")
        return status

    async def record_meeting(self, duration_seconds: Optional[int] = None) -> dict:
        """
        Full flow: open meeting URL, start recording, wait for duration, stop.

        The meeting URL is opened in the user's default browser so they can
        join normally. Recording captures system mic/speaker/screen in background.

        Args:
            duration_seconds: How long to record. If None, records indefinitely
                              until Ctrl+C.
        """
        try:
            self.open_meeting_in_browser()
            self.start_recording()

            if duration_seconds:
                logger.info(f"Recording for {duration_seconds}s ({duration_seconds // 60} min)...")
                await asyncio.sleep(duration_seconds)
            else:
                logger.info("Recording indefinitely. Stop with Ctrl+C.")
                try:
                    while self._recording:
                        await asyncio.sleep(10)
                except asyncio.CancelledError:
                    pass

        finally:
            result = self.stop_recording()
            return result


async def record_meeting_now(
    meeting_url: str,
    subject: str = "meeting",
    duration_seconds: Optional[int] = None,
) -> dict:
    """Convenience function to record a meeting immediately."""
    recorder = MeetingRecorder(
        meeting_url=meeting_url,
        subject=subject,
    )
    return await recorder.record_meeting(duration_seconds=duration_seconds)
