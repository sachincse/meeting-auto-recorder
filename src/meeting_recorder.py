"""Meeting recorder — uses recordmymeeting to capture audio/screen during meetings."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from recordmymeeting.core import RecordMyMeeting

from src.config import BASE_DIR, env, env_bool, RECORDING_FPS

logger = logging.getLogger(__name__)

RECORDINGS_DIR = BASE_DIR / "data" / "recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_filename(name: str) -> str:
    """Remove characters that are invalid in filenames."""
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()[:80]


class MeetingRecorder:
    """Joins a meeting URL via browser and records audio + screen."""

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
        self.record_mic = record_mic
        self.record_speaker = record_speaker
        self.record_screen = record_screen

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
        self._browser_page = None
        self._recording = False

    async def join_meeting(self, headless: bool = True):
        """Open the meeting URL in a browser."""
        logger.info(f"Joining meeting: {self.meeting_url}")
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=headless,
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--disable-web-security",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        self._context = await self._browser.new_context(
            permissions=["microphone", "camera"],
            viewport={"width": 1920, "height": 1080},
        )
        self._browser_page = await self._context.new_page()
        await self._browser_page.goto(self.meeting_url, wait_until="domcontentloaded")
        await asyncio.sleep(5)
        logger.info("Meeting page loaded")

    def start_recording(self):
        """Start recording audio and screen."""
        if self._recording:
            logger.warning("Already recording")
            return
        logger.info(f"Starting recording: mic={self.record_mic}, speaker={self.record_speaker}, screen={self.record_screen}")
        self.recorder.start()
        self._recording = True
        logger.info("Recording started")

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

    async def leave_meeting(self):
        """Close the browser."""
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._browser_page = None
        logger.info("Left meeting")

    async def record_meeting(self, duration_seconds: Optional[int] = None):
        """
        Full flow: join meeting, record for duration, stop, leave.

        Args:
            duration_seconds: How long to record. If None, records until
                              the meeting end time (caller must stop manually).
        """
        headless = env_bool("MEETING_HEADLESS", True)
        try:
            await self.join_meeting(headless=headless)
            self.start_recording()

            if duration_seconds:
                logger.info(f"Recording for {duration_seconds} seconds...")
                await asyncio.sleep(duration_seconds)
            else:
                logger.info("Recording indefinitely. Stop with Ctrl+C or call stop_recording()")
                try:
                    while self._recording:
                        await asyncio.sleep(10)
                except asyncio.CancelledError:
                    pass

        finally:
            result = self.stop_recording()
            await self.leave_meeting()
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
