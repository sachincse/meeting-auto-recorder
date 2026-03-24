"""Meeting scheduler — reads emails, finds meetings, schedules recordings automatically."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from src import db
from src.config import load_config
from src.email_reader import fetch_meeting_invites
from src.meeting_recorder import MeetingRecorder

logger = logging.getLogger(__name__)

# Buffer: start recording N minutes before meeting
PRE_MEETING_BUFFER_MINUTES = 1
# Default recording duration if no end time (90 minutes)
DEFAULT_DURATION_MINUTES = 90


async def _log_meeting_event(meeting_id: int, event: str, details: str = ""):
    """Log a meeting event to the DB."""
    conn = await db.get_db()
    await conn.execute(
        "UPDATE meetings SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (event, meeting_id),
    )
    await conn.commit()
    await conn.close()


async def _record_meeting_task(meeting_id: int, meeting_url: str, subject: str, duration_seconds: int):
    """Task that actually records a meeting. Called by APScheduler at the scheduled time."""
    logger.info(f"Auto-recording starting for meeting #{meeting_id}: {subject}")
    await _log_meeting_event(meeting_id, "recording")

    try:
        recorder = MeetingRecorder(
            meeting_url=meeting_url,
            subject=subject,
        )
        result = await recorder.record_meeting(duration_seconds=duration_seconds)

        # Update DB with recording path
        conn = await db.get_db()
        recording_path = result.get("session_dir", "") if result else ""
        await conn.execute(
            "UPDATE meetings SET status = 'recorded', recording_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (recording_path, meeting_id),
        )
        await conn.commit()
        await conn.close()
        logger.info(f"Meeting #{meeting_id} recorded successfully: {recording_path}")

    except Exception as e:
        logger.error(f"Failed to record meeting #{meeting_id}: {e}")
        await _log_meeting_event(meeting_id, "failed")


async def scan_emails_and_schedule(scheduler: AsyncIOScheduler):
    """
    Scan emails for meeting invites, store in DB, and schedule recordings.

    This is the main orchestration function called periodically.
    """
    logger.info("Scanning emails for meeting invitations...")
    meetings = fetch_meeting_invites()

    if not meetings:
        logger.info("No new meeting invitations found")
        return

    now = datetime.now(timezone.utc)
    scheduled_count = 0

    for meeting in meetings:
        meeting_url = meeting.get("meeting_url")
        start_time_str = meeting.get("start_time")
        subject = meeting.get("subject", "Untitled Meeting")

        if not meeting_url:
            logger.debug(f"Skipping meeting '{subject}' — no meeting URL found")
            continue

        if not start_time_str:
            logger.warning(f"Skipping meeting '{subject}' — no start time (found URL: {meeting_url})")
            continue

        start_time = datetime.fromisoformat(start_time_str)
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        # Skip past meetings
        if start_time < now - timedelta(minutes=5):
            logger.debug(f"Skipping past meeting '{subject}' at {start_time}")
            continue

        # Calculate duration
        end_time_str = meeting.get("end_time")
        if end_time_str:
            end_time = datetime.fromisoformat(end_time_str)
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
            duration_seconds = int((end_time - start_time).total_seconds())
        else:
            duration_seconds = DEFAULT_DURATION_MINUTES * 60

        # Ensure reasonable duration (min 5 min, max 4 hours)
        duration_seconds = max(300, min(duration_seconds, 4 * 3600))

        # Check if already in DB
        conn = await db.get_db()
        cursor = await conn.execute(
            "SELECT id FROM meetings WHERE meeting_url = ? AND start_time = ?",
            (meeting_url, start_time.isoformat()),
        )
        existing = await cursor.fetchone()

        if existing:
            await conn.close()
            logger.debug(f"Meeting already tracked: '{subject}'")
            continue

        # Insert into DB
        cursor = await conn.execute(
            """INSERT INTO meetings
               (subject, meeting_url, start_time, end_time, duration_seconds,
                organizer, source, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'scheduled')""",
            (
                subject,
                meeting_url,
                start_time.isoformat(),
                end_time_str,
                duration_seconds,
                meeting.get("organizer", ""),
                meeting.get("source", "email"),
            ),
        )
        meeting_id = cursor.lastrowid
        await conn.commit()
        await conn.close()

        # Schedule the recording
        record_at = start_time - timedelta(minutes=PRE_MEETING_BUFFER_MINUTES)
        if record_at < now:
            record_at = now + timedelta(seconds=10)  # Start ASAP

        job_id = f"meeting_record_{meeting_id}"
        scheduler.add_job(
            _record_meeting_task,
            trigger=DateTrigger(run_date=record_at),
            args=[meeting_id, meeting_url, subject, duration_seconds],
            id=job_id,
            name=f"Record: {subject[:50]}",
            replace_existing=True,
        )

        logger.info(
            f"Scheduled recording for '{subject}' at {record_at.isoformat()} "
            f"(duration: {duration_seconds // 60} min) [meeting #{meeting_id}]"
        )
        scheduled_count += 1

    logger.info(f"Scheduled {scheduled_count} new meeting recordings")


async def get_upcoming_meetings() -> list[dict]:
    """Get all upcoming scheduled meetings from DB."""
    conn = await db.get_db()
    cursor = await conn.execute(
        """SELECT * FROM meetings
           WHERE status IN ('scheduled', 'recording')
             AND start_time > datetime('now', '-1 hour')
           ORDER BY start_time ASC"""
    )
    rows = await cursor.fetchall()
    await conn.close()
    return [dict(r) for r in rows]


async def get_meeting_stats() -> dict:
    """Get meeting recording stats."""
    conn = await db.get_db()
    stats = {}
    for key, query in {
        "total_meetings": "SELECT COUNT(*) FROM meetings",
        "scheduled": "SELECT COUNT(*) FROM meetings WHERE status = 'scheduled'",
        "recorded": "SELECT COUNT(*) FROM meetings WHERE status = 'recorded'",
        "failed": "SELECT COUNT(*) FROM meetings WHERE status = 'failed'",
    }.items():
        cursor = await conn.execute(query)
        row = await cursor.fetchone()
        stats[key] = row[0] if row else 0
    await conn.close()
    return stats
