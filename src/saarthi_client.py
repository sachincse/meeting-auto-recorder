"""Client for Interview Saarthi web API.

Handles authentication, recording upload, and status polling against the
Interview Saarthi REST API. Token is persisted in user_prefs.yaml so the
recorder can auto-upload without re-authenticating every session.
"""

import logging
from pathlib import Path

import httpx

from src.config import load_user_prefs, save_user_prefs

logger = logging.getLogger(__name__)


class SaarthiClient:
    def __init__(self):
        prefs = load_user_prefs()
        self.server_url = prefs.get(
            "saarthi_server",
            "https://interview-intelligence-production-7e43.up.railway.app",
        )
        self.token = prefs.get("saarthi_token", "")
        self.auto_upload = prefs.get("saarthi_auto_upload", True)

    @property
    def is_connected(self) -> bool:
        """True if we have a token. Use verify() for a full server check."""
        return bool(self.token)

    def login(self, username: str, password: str) -> dict:
        """Login and store token. Returns {"username", "plan"} or raises."""
        r = httpx.post(
            f"{self.server_url}/api/auth/token",
            json={"username": username, "password": password},
            timeout=15,
        )
        if r.status_code != 200:
            raise Exception(r.json().get("detail", "Login failed"))
        data = r.json()
        self.token = data["token"]
        save_user_prefs(
            {
                "saarthi_server": self.server_url,
                "saarthi_token": self.token,
                "saarthi_username": data["username"],
            }
        )
        return data

    def verify(self) -> bool:
        """Verify that the stored token is still valid."""
        if not self.token:
            return False
        try:
            r = httpx.get(
                f"{self.server_url}/api/auth/verify",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10,
            )
            return r.status_code == 200 and r.json().get("valid", False)
        except Exception:
            return False

    def upload_recording(
        self, files: dict[str, Path], title: str = "Recording",
        company: str = "", round_name: str = "",
    ) -> dict:
        """Upload recording files with optional company/round metadata.

        files = {"microphone.wav": Path, "speaker.wav": Path, ...}
        """
        if not self.token:
            raise Exception("Not connected to Interview Saarthi")

        multipart = []
        for fname, fpath in files.items():
            # Determine mime type based on extension
            mime = "audio/wav" if fname.endswith(".wav") else "video/mp4"
            multipart.append(("files", (fname, fpath.read_bytes(), mime)))

        data = {"title": title}
        if company:
            data["company"] = company
        if round_name:
            data["round"] = round_name

        r = httpx.post(
            f"{self.server_url}/api/recordings/upload",
            headers={"Authorization": f"Bearer {self.token}"},
            files=multipart,
            data=data,
            timeout=300,
        )
        if r.status_code != 200:
            raise Exception(f"Upload failed: {r.text[:200]}")
        return r.json()

    def get_status(self, interview_id: int) -> dict:
        """Get the processing status of an uploaded recording."""
        r = httpx.get(
            f"{self.server_url}/api/recordings/{interview_id}/status",
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=10,
        )
        return r.json()

    def sync_meetings(self, meetings: list[dict]) -> dict:
        """Upload local meeting data to Saarthi for cross-session persistence."""
        if not self.token:
            return {}
        try:
            r = httpx.post(
                f"{self.server_url}/api/user/meetings",
                headers={"Authorization": f"Bearer {self.token}"},
                json={"meetings": meetings},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()
            logger.warning("Meeting sync failed: %s", r.text[:200])
        except Exception as e:
            logger.debug("Meeting sync request failed: %s", e)
        return {}

    def load_meetings(self) -> list[dict]:
        """Load meeting data from Saarthi (persisted across sessions)."""
        if not self.token:
            return []
        try:
            r = httpx.get(
                f"{self.server_url}/api/user/meetings",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json().get("meetings", [])
            logger.warning("Meeting load failed: %s", r.text[:200])
        except Exception as e:
            logger.debug("Meeting load request failed: %s", e)
        return []
