"""Read emails via IMAP to find meeting invitations with ICS calendar data."""

import email
import email.message
import imaplib
import logging
import re
from datetime import datetime, timezone
from email.header import decode_header
from typing import Optional

from icalendar import Calendar

from src.config import (
    IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASS, IMAP_FOLDER,
)

logger = logging.getLogger(__name__)

# Patterns to extract meeting URLs from text
MEETING_URL_PATTERNS = [
    re.compile(r'https?://[\w.-]*zoom\.us/j/\S+', re.IGNORECASE),
    re.compile(r'https?://teams\.microsoft\.com/l/meetup-join/\S+', re.IGNORECASE),
    re.compile(r'https?://meet\.google\.com/[\w-]+', re.IGNORECASE),
    re.compile(r'https?://[\w.-]*webex\.com/\S+', re.IGNORECASE),
    re.compile(r'https?://[\w.-]*gotomeeting\.com/\S+', re.IGNORECASE),
]


def _decode_header_value(value: str) -> str:
    """Decode MIME-encoded header value."""
    decoded_parts = decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)


def _extract_meeting_url(text: str) -> Optional[str]:
    """Find a meeting URL (Zoom, Teams, Meet, etc.) in text."""
    for pattern in MEETING_URL_PATTERNS:
        match = pattern.search(text)
        if match:
            url = match.group(0).rstrip(">.),;\"'")
            return url
    return None


def _parse_ics(ics_data: str) -> list[dict]:
    """Parse ICS calendar data and return meeting events."""
    meetings = []
    try:
        cal = Calendar.from_ical(ics_data)
    except Exception as e:
        logger.warning(f"Failed to parse ICS: {e}")
        return meetings

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        dtstart = component.get("dtstart")
        dtend = component.get("dtend")
        summary = str(component.get("summary", "Untitled Meeting"))
        description = str(component.get("description", ""))
        location = str(component.get("location", ""))
        organizer = str(component.get("organizer", ""))

        if not dtstart:
            continue

        start_dt = dtstart.dt
        end_dt = dtend.dt if dtend else None

        # Ensure timezone-aware
        if hasattr(start_dt, "hour"):
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if end_dt and end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        else:
            # All-day event, skip
            continue

        # Extract meeting URL from description or location
        meeting_url = (
            _extract_meeting_url(description)
            or _extract_meeting_url(location)
            or _extract_meeting_url(summary)
        )

        meetings.append({
            "subject": summary,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat() if end_dt else None,
            "meeting_url": meeting_url,
            "location": location,
            "description": description,
            "organizer": organizer,
        })

    return meetings


def _get_email_body(msg: email.message.Message) -> str:
    """Extract the plain-text or HTML body from an email."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode("utf-8", errors="replace")
            elif ctype == "text/html" and not body:
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode("utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="replace")
    return body


def fetch_meeting_invites(since_date: Optional[str] = None, max_emails: int = 50) -> list[dict]:
    """
    Connect to IMAP and find meeting invitations.

    Args:
        since_date: IMAP date string like '20-Mar-2026'. If None, searches last 7 days.
        max_emails: Max emails to scan.

    Returns:
        List of meeting dicts with subject, start_time, end_time, meeting_url, etc.
    """
    if not all([IMAP_HOST, IMAP_USER, IMAP_PASS]):
        logger.error("IMAP credentials not configured. Set IMAP_HOST, IMAP_USER, IMAP_PASS in .env")
        return []

    if since_date is None:
        from datetime import timedelta
        d = datetime.now() - timedelta(days=7)
        since_date = d.strftime("%d-%b-%Y")

    meetings = []
    seen = set()  # (meeting_url, start_time) dedup

    try:
        logger.info(f"Connecting to {IMAP_HOST}:{IMAP_PORT}...")
        mail = imaplib.IMAP4_SSL(IMAP_HOST, int(IMAP_PORT))
        mail.login(IMAP_USER, IMAP_PASS)
        mail.select(IMAP_FOLDER)

        # Search for emails since the given date
        status, msg_ids = mail.search(None, f'(SINCE "{since_date}")')
        if status != "OK":
            logger.warning("IMAP search failed")
            mail.logout()
            return []

        all_ids = msg_ids[0].split()
        # Take the most recent ones
        ids_to_check = all_ids[-max_emails:]

        logger.info(f"Scanning {len(ids_to_check)} emails for meeting invites...")

        for msg_id in ids_to_check:
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = _decode_header_value(msg.get("Subject", ""))

            # Method 1: Look for ICS attachments (calendar invites)
            if msg.is_multipart():
                for part in msg.walk():
                    ctype = part.get_content_type()
                    if ctype in ("text/calendar", "application/ics"):
                        payload = part.get_payload(decode=True)
                        if payload:
                            ics_text = payload.decode("utf-8", errors="replace")
                            parsed = _parse_ics(ics_text)
                            for m in parsed:
                                key = (m.get("meeting_url"), m.get("start_time"))
                                if key in seen:
                                    continue
                                seen.add(key)
                                m["email_subject"] = subject
                                m["source"] = "ics_attachment"
                                meetings.append(m)

            # Method 2: Look for meeting URLs in the email body
            body = _get_email_body(msg)
            meeting_url = _extract_meeting_url(body)
            if meeting_url and not any(m.get("meeting_url") == meeting_url for m in meetings):
                # Try to extract time from subject or body
                meetings.append({
                    "subject": subject,
                    "start_time": None,  # Will need manual/AI parsing
                    "end_time": None,
                    "meeting_url": meeting_url,
                    "location": "",
                    "description": body[:500],
                    "organizer": msg.get("From", ""),
                    "email_subject": subject,
                    "source": "email_body_url",
                })

        mail.logout()
        logger.info(f"Found {len(meetings)} meeting invitations")

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP error: {e}")
    except Exception as e:
        logger.error(f"Email reading error: {e}")

    return meetings
