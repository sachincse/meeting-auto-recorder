"""Meeting scheduler — reads emails, finds meetings, schedules recordings automatically."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from src import db
from src.config import get_scheduler_config
from src.email_reader import fetch_meeting_invites
from src.meeting_recorder import MeetingRecorder, set_active_recorder

logger = logging.getLogger(__name__)

# Pause flag
_scanning_paused = False


def pause_scanning():
    global _scanning_paused
    _scanning_paused = True
    logger.info("Email scanning paused")


def resume_scanning():
    global _scanning_paused
    _scanning_paused = False
    logger.info("Email scanning resumed")


def is_scanning_paused() -> bool:
    return _scanning_paused


async def _log_meeting_event(meeting_id: int, event: str):
    conn = await db.get_db()
    await conn.execute(
        "UPDATE meetings SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (event, meeting_id),
    )
    await conn.commit()
    await conn.close()


async def _record_meeting_task(meeting_id: int, meeting_url: str, subject: str, duration_seconds: int):
    """Task that records a meeting. Called by APScheduler at the scheduled time."""
    logger.info(f"Auto-recording starting for meeting #{meeting_id}: {subject}")
    await _log_meeting_event(meeting_id, "recording")

    try:
        from src.notifier import notify
        notify("Recording Started", f"{subject}")

        from src.tray_app import update_tray_icon
        update_tray_icon(recording=True)
    except Exception:
        pass

    try:
        recorder = MeetingRecorder(meeting_url=meeting_url, subject=subject)
        set_active_recorder(recorder)
        result = await recorder.record_meeting(duration_seconds=duration_seconds)

        conn = await db.get_db()
        recording_path = result.get("session_folder", "") if result else ""
        await conn.execute(
            "UPDATE meetings SET status = 'recorded', recording_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (recording_path, meeting_id),
        )
        await conn.commit()
        await conn.close()
        logger.info(f"Meeting #{meeting_id} recorded: {recording_path}")

    except Exception as e:
        logger.error(f"Failed to record meeting #{meeting_id}: {e}")
        await _log_meeting_event(meeting_id, "failed")
    finally:
        set_active_recorder(None)
        try:
            from src.tray_app import update_tray_icon
            update_tray_icon(recording=False)
            from src.notifier import notify
            notify("Recording Finished", f"{subject}")
        except Exception:
            pass


async def scan_emails_and_schedule(scheduler: AsyncIOScheduler) -> int:
    """Scan all email accounts for meeting invites, store in DB, schedule recordings."""
    if _scanning_paused:
        logger.info("Scanning is paused, skipping")
        return 0

    logger.info("Scanning emails for meeting invitations...")
    sched_cfg = get_scheduler_config()
    meetings = fetch_meeting_invites()

    if not meetings:
        logger.info("No new meeting invitations found")
        return 0

    now = datetime.now(timezone.utc)
    pre_buffer = sched_cfg["pre_meeting_buffer_min"]
    default_duration = sched_cfg["default_duration_min"]
    scheduled_count = 0

    for meeting in meetings:
        meeting_url = meeting.get("meeting_url")
        start_time_str = meeting.get("start_time")
        subject = meeting.get("subject", "Untitled Meeting")

        if not meeting_url or not start_time_str:
            continue

        start_time = datetime.fromisoformat(start_time_str)
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        if start_time < now - timedelta(minutes=5):
            continue

        end_time_str = meeting.get("end_time")
        if end_time_str:
            end_time = datetime.fromisoformat(end_time_str)
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
            duration_seconds = int((end_time - start_time).total_seconds())
        else:
            duration_seconds = default_duration * 60

        duration_seconds = max(300, min(duration_seconds, 4 * 3600))

        conn = await db.get_db()
        cursor = await conn.execute(
            "SELECT id FROM meetings WHERE meeting_url = ? AND start_time = ?",
            (meeting_url, start_time.isoformat()),
        )
        existing = await cursor.fetchone()

        if existing:
            await conn.close()
            continue

        cursor = await conn.execute(
            """INSERT INTO meetings
               (subject, meeting_url, start_time, end_time, duration_seconds,
                organizer, source, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'scheduled')""",
            (
                subject, meeting_url, start_time.isoformat(), end_time_str,
                duration_seconds, meeting.get("organizer", ""),
                meeting.get("source", "email"),
            ),
        )
        meeting_id = cursor.lastrowid
        await conn.commit()
        await conn.close()

        record_at = start_time - timedelta(minutes=pre_buffer)
        if record_at < now:
            record_at = now + timedelta(seconds=10)

        scheduler.add_job(
            _record_meeting_task,
            trigger=DateTrigger(run_date=record_at),
            args=[meeting_id, meeting_url, subject, duration_seconds],
            id=f"meeting_record_{meeting_id}",
            name=f"Record: {subject[:50]}",
            replace_existing=True,
        )

        logger.info(
            f"Scheduled '{subject}' at {record_at.isoformat()} "
            f"(duration: {duration_seconds // 60} min) [#{meeting_id}]"
        )
        scheduled_count += 1

    logger.info(f"Scheduled {scheduled_count} new meeting recordings")
    return scheduled_count


async def schedule_manual_meeting(
    scheduler: AsyncIOScheduler,
    meeting_url: str,
    subject: str,
    start_time: datetime,
    duration_minutes: int,
) -> int:
    """Schedule a manually-entered meeting recording. Returns meeting_id."""
    duration_seconds = max(300, min(duration_minutes * 60, 4 * 3600))

    conn = await db.get_db()
    cursor = await conn.execute(
        """INSERT INTO meetings
           (subject, meeting_url, start_time, end_time, duration_seconds,
            organizer, source, status)
           VALUES (?, ?, ?, ?, ?, ?, 'manual', 'scheduled')""",
        (
            subject, meeting_url, start_time.isoformat(), None,
            duration_seconds, "",
        ),
    )
    meeting_id = cursor.lastrowid
    await conn.commit()
    await conn.close()

    sched_cfg = get_scheduler_config()
    now = datetime.now(timezone.utc)
    record_at = start_time - timedelta(minutes=sched_cfg["pre_meeting_buffer_min"])
    if record_at < now:
        record_at = now + timedelta(seconds=10)

    scheduler.add_job(
        _record_meeting_task,
        trigger=DateTrigger(run_date=record_at),
        args=[meeting_id, meeting_url, subject, duration_seconds],
        id=f"meeting_record_{meeting_id}",
        name=f"Record: {subject[:50]}",
        replace_existing=True,
    )

    logger.info(f"Manually scheduled '{subject}' at {record_at.isoformat()} [#{meeting_id}]")
    return meeting_id


async def get_upcoming_meetings() -> list[dict]:
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


async def get_meeting_history(limit: int = 50) -> list[dict]:
    conn = await db.get_db()
    cursor = await conn.execute(
        """SELECT * FROM meetings
           ORDER BY start_time DESC
           LIMIT ?""",
        (limit,),
    )
    rows = await cursor.fetchall()
    await conn.close()
    return [dict(r) for r in rows]


async def get_meeting_stats() -> dict:
    conn = await db.get_db()
    stats = {}
    for key, query in {
        "total": "SELECT COUNT(*) FROM meetings",
        "scheduled": "SELECT COUNT(*) FROM meetings WHERE status = 'scheduled'",
        "recorded": "SELECT COUNT(*) FROM meetings WHERE status = 'recorded'",
        "failed": "SELECT COUNT(*) FROM meetings WHERE status = 'failed'",
    }.items():
        cursor = await conn.execute(query)
        row = await cursor.fetchone()
        stats[key] = row[0] if row else 0
    await conn.close()
    return stats
