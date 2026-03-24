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

from src.config import get_email_accounts, get_scheduler_config

logger = logging.getLogger(__name__)

MEETING_URL_PATTERNS = [
    re.compile(r'https?://[\w.-]*zoom\.us/j/\S+', re.IGNORECASE),
    re.compile(r'https?://teams\.microsoft\.com/l/meetup-join/\S+', re.IGNORECASE),
    re.compile(r'https?://meet\.google\.com/[\w-]+', re.IGNORECASE),
    re.compile(r'https?://[\w.-]*webex\.com/\S+', re.IGNORECASE),
    re.compile(r'https?://[\w.-]*gotomeeting\.com/\S+', re.IGNORECASE),
]


def _decode_header_value(value: str) -> str:
    decoded_parts = decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)


def _extract_meeting_url(text: str) -> Optional[str]:
    for pattern in MEETING_URL_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0).rstrip(">.),;\"'")
    return None


def _parse_ics(ics_data: str) -> list[dict]:
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

        if hasattr(start_dt, "hour"):
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if end_dt and end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        else:
            continue

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


def _scan_single_account(account: dict, since_date: str, max_emails: int) -> list[dict]:
    """Scan a single IMAP account for meeting invites."""
    host = account.get("imap_host", "")
    port = account.get("imap_port", 993)
    user = account.get("imap_user", "")
    password = account.get("imap_pass", "")
    folder = account.get("imap_folder", "INBOX")
    name = account.get("name", user)

    if not all([host, user, password]):
        logger.warning(f"Skipping account '{name}' — missing credentials")
        return []

    meetings = []
    seen = set()

    try:
        logger.info(f"[{name}] Connecting to {host}:{port}...")
        mail = imaplib.IMAP4_SSL(host, int(port))
        mail.login(user, password)
        mail.select(folder)

        status, msg_ids = mail.search(None, f'(SINCE "{since_date}")')
        if status != "OK":
            logger.warning(f"[{name}] IMAP search failed")
            mail.logout()
            return []

        all_ids = msg_ids[0].split()
        ids_to_check = all_ids[-max_emails:]
        logger.info(f"[{name}] Scanning {len(ids_to_check)} emails...")

        for msg_id in ids_to_check:
          try:
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = _decode_header_value(msg.get("Subject", ""))

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
                                m["account"] = name
                                meetings.append(m)

            body = _get_email_body(msg)
            meeting_url = _extract_meeting_url(body)
            if meeting_url and not any(m.get("meeting_url") == meeting_url for m in meetings):
                meetings.append({
                    "subject": subject,
                    "start_time": None,
                    "end_time": None,
                    "meeting_url": meeting_url,
                    "location": "",
                    "description": body[:500],
                    "organizer": msg.get("From", ""),
                    "email_subject": subject,
                    "source": "email_body_url",
                    "account": name,
                })
          except Exception as e:
            logger.debug(f"[{name}] Skipping email {msg_id}: {e}")
            continue

        mail.logout()
        logger.info(f"[{name}] Found {len(meetings)} meeting invitations")

    except imaplib.IMAP4.error as e:
        logger.error(f"[{name}] IMAP error: {e}")
    except Exception as e:
        logger.error(f"[{name}] Email reading error: {e}")

    return meetings


def fetch_meeting_invites(since_date: Optional[str] = None) -> list[dict]:
    """Scan ALL configured email accounts for meeting invitations."""
    accounts = get_email_accounts()
    sched_cfg = get_scheduler_config()
    max_emails = sched_cfg.get("max_emails_to_scan", 100)

    if not accounts:
        logger.error("No email accounts configured in config.yaml")
        return []

    if since_date is None:
        from datetime import timedelta
        d = datetime.now() - timedelta(days=7)
        since_date = d.strftime("%d-%b-%Y")

    all_meetings = []
    seen_global = set()

    for account in accounts:
        meetings = _scan_single_account(account, since_date, max_emails)
        for m in meetings:
            key = (m.get("meeting_url"), m.get("start_time"))
            if key not in seen_global:
                seen_global.add(key)
                all_meetings.append(m)

    logger.info(f"Total meetings found across {len(accounts)} account(s): {len(all_meetings)}")
    return all_meetings
