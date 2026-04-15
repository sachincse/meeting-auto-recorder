"""Meeting scheduler — reads emails, finds meetings, schedules recordings automatically."""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from src import db
from src.config import get_scheduler_config, get_recording_config, load_user_prefs
from src.email_reader import fetch_meeting_invites
from src.interview_detector import detect_interview_info
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
        notify("Recording Started", f"{subject}", event="start")

        from src.tray_app import update_tray_icon
        update_tray_icon(recording=True)
    except Exception:
        pass

    # Detect company/round for smart folder naming
    # Fetch organizer from DB for better detection
    organizer = ""
    try:
        conn = await db.get_db()
        cursor = await conn.execute("SELECT organizer FROM meetings WHERE id = ?", (meeting_id,))
        row = await cursor.fetchone()
        if row:
            organizer = row[0] or ""
        await conn.close()
    except Exception:
        pass

    info = detect_interview_info(subject, organizer)
    logger.info(f"Detected: company={info['company']}, round={info['round']}")

    # Build structured output directory
    prefs = load_user_prefs()
    auto_organize = prefs.get("auto_organize_folders", True)
    rec_cfg = get_recording_config()
    if auto_organize:
        output_dir = os.path.join(rec_cfg["output_dir"], info["folder_name"])
    else:
        output_dir = rec_cfg["output_dir"]
    os.makedirs(output_dir, exist_ok=True)

    try:
        recorder = MeetingRecorder(meeting_url=meeting_url, subject=subject, output_dir=output_dir)
        set_active_recorder(recorder)
        result = await recorder.record_meeting(duration_seconds=duration_seconds)

        conn = await db.get_db()
        recording_path = result.get("session_folder", "") if result else ""

        # Validate recording files were actually created
        from pathlib import Path
        if recording_path and Path(recording_path).is_dir():
            files = list(Path(recording_path).iterdir())
            file_names = [f.name for f in files]
            file_sizes = {f.name: f.stat().st_size for f in files}
            logger.info(f"Recording files for #{meeting_id}: {file_sizes}")

            if not any(f.endswith('.wav') for f in file_names):
                logger.warning(f"Meeting #{meeting_id}: No audio files produced!")
            if not any(f.endswith('.mp4') for f in file_names):
                logger.warning(f"Meeting #{meeting_id}: No screen recording produced!")
            for fname, size in file_sizes.items():
                if size == 0:
                    logger.warning(f"Meeting #{meeting_id}: {fname} is empty (0 bytes)!")
        else:
            logger.warning(f"Meeting #{meeting_id}: Recording path missing or invalid: {recording_path}")

        await conn.execute(
            "UPDATE meetings SET status = 'recorded', recording_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (recording_path, meeting_id),
        )
        await conn.commit()
        await conn.close()
        logger.info(f"Meeting #{meeting_id} recorded successfully: {recording_path}")

        # After recording completes, handle upload based on user preference
        upload_mode = prefs.get("saarthi_upload_mode", "approve")

        try:
            from src.saarthi_client import SaarthiClient
            client = SaarthiClient()

            if upload_mode == "auto" and client.is_connected:
                # Upload immediately
                from pathlib import Path as _Path
                recording_dir = _Path(recording_path)
                upload_files = {}
                for fname in ['microphone.wav', 'speaker.wav', 'screen.mp4']:
                    fpath = recording_dir / fname
                    if fpath.exists() and fpath.stat().st_size > 0:
                        upload_files[fname] = fpath

                if upload_files:
                    upload_result = client.upload_recording(
                        upload_files, title=subject,
                        company=info["company"], round_name=info["round"],
                    )
                    saarthi_id = upload_result.get('interview_id')
                    logger.info(f"Auto-uploaded to Saarthi: interview #{saarthi_id}")

                    # Update DB with Saarthi interview ID
                    conn = await db.get_db()
                    await conn.execute(
                        "UPDATE meetings SET status = 'uploaded', recording_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (f"saarthi:{saarthi_id}", meeting_id),
                    )
                    await conn.commit()
                    await conn.close()
                else:
                    logger.warning(f"No non-empty recording files found for Saarthi upload in {recording_path}")

            elif upload_mode == "approve":
                # Mark as pending_upload in DB, show in GUI for approval
                conn = await db.get_db()
                await conn.execute(
                    "UPDATE meetings SET status = 'pending_upload' WHERE id = ?",
                    (meeting_id,),
                )
                await conn.commit()
                await conn.close()
                logger.info(f"Recording ready for approval: {subject}")

            elif upload_mode == "off":
                logger.info(f"Upload mode is off, recording saved locally only: {subject}")

        except Exception as e:
            logger.warning(f"Auto-upload to Saarthi failed (recording still saved locally): {e}")

    except Exception as e:
        logger.error(f"Failed to record meeting #{meeting_id}: {e}", exc_info=True)
        await _log_meeting_event(meeting_id, "failed")
    finally:
        set_active_recorder(None)
        try:
            from src.tray_app import update_tray_icon
            update_tray_icon(recording=False)
            from src.notifier import notify
            notify("Recording Finished", f"{subject}", event="stop")
        except Exception:
            pass


async def rehydrate_scheduled_meetings(scheduler: AsyncIOScheduler) -> int:
    """Re-register DateTrigger jobs for future meetings already in the DB.

    APScheduler uses an in-memory job store by default, so any pending
    DateTrigger jobs are lost when the tray process exits (reboot, crash,
    logout). Without rehydration, a meeting scanned in a previous session
    would never fire — it is still in the DB, so ``scan_emails_and_schedule``
    treats it as a duplicate and skips scheduling.

    Call this once at tray startup, BEFORE the first ``scan_emails_and_schedule``.
    It will re-add a DateTrigger for every ``status='scheduled'`` row whose
    ``start_time`` is still in the future (or within the last 30 minutes),
    and mark older rows as ``missed``.
    """
    now = datetime.now(timezone.utc)
    sched_cfg = get_scheduler_config()
    pre_buffer = sched_cfg["pre_meeting_buffer_min"]
    default_duration = sched_cfg["default_duration_min"]

    conn = await db.get_db()
    cursor = await conn.execute(
        """SELECT id, subject, meeting_url, start_time, duration_seconds
           FROM meetings
           WHERE status = 'scheduled'
             AND meeting_url IS NOT NULL AND meeting_url != ''"""
    )
    rows = await cursor.fetchall()
    await conn.close()

    rehydrated = 0
    missed = 0
    for r in rows:
        meeting_id, subject, meeting_url, start_time_str, duration_seconds = (
            r[0], r[1], r[2], r[3], r[4],
        )
        duration_seconds = duration_seconds or (default_duration * 60)

        try:
            start_time = datetime.fromisoformat(start_time_str)
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
        except Exception as e:
            logger.warning(f"Cannot parse start_time for #{meeting_id}: {e}")
            continue

        # Already past — mark as missed and skip
        if start_time < now - timedelta(minutes=30):
            await _log_meeting_event(meeting_id, "missed")
            logger.info(
                f"Meeting #{meeting_id} '{subject}' was past its start time — marked missed"
            )
            missed += 1
            continue

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
        rehydrated += 1
        logger.info(
            f"Rehydrated #{meeting_id} '{subject}' → recording at {record_at.isoformat()}"
        )

    logger.info(
        f"Rehydration complete: {rehydrated} re-scheduled, {missed} marked missed"
    )
    return rehydrated


async def scan_emails_and_schedule(scheduler: AsyncIOScheduler) -> int:
    """Scan all email accounts for meeting invites, store in DB, schedule recordings."""
    if _scanning_paused:
        logger.info("Scanning is paused, skipping")
        return 0

    logger.info("Scanning emails for meeting invitations...")
    sched_cfg = get_scheduler_config()

    # Clean up: mark past "scheduled" meetings as "missed"
    try:
        conn = await db.get_db()
        await conn.execute(
            """UPDATE meetings SET status = 'missed', updated_at = CURRENT_TIMESTAMP
               WHERE status = 'scheduled'
                 AND start_time < datetime('now', '-30 minutes')""",
        )
        await conn.commit()
        await conn.close()
    except Exception as e:
        logger.debug(f"Cleanup failed: {e}")

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

    # Sync local meeting data to Saarthi web for cross-session persistence
    try:
        from src.saarthi_client import SaarthiClient
        client = SaarthiClient()
        if client.is_connected:
            conn = await db.get_db()
            cursor = await conn.execute(
                "SELECT * FROM meetings ORDER BY start_time DESC LIMIT 50"
            )
            rows = await cursor.fetchall()
            await conn.close()
            sync_data = [dict(r) for r in rows]
            result = client.sync_meetings(sync_data)
            synced = result.get("synced", 0)
            logger.info(f"Synced {synced} meetings to Saarthi")
    except Exception as e:
        logger.debug(f"Meeting sync to Saarthi failed: {e}")

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
        "pending_upload": "SELECT COUNT(*) FROM meetings WHERE status = 'pending_upload'",
        "uploaded": "SELECT COUNT(*) FROM meetings WHERE status = 'uploaded'",
        "failed": "SELECT COUNT(*) FROM meetings WHERE status = 'failed'",
    }.items():
        cursor = await conn.execute(query)
        row = await cursor.fetchone()
        stats[key] = row[0] if row else 0
    await conn.close()
    return stats
