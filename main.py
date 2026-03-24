"""Meeting Auto-Recorder — Entry Point.

Automatically reads emails for meeting invites and records them.
"""

import argparse
import asyncio
import logging
import sys

from src import db


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/recorder.log", mode="a"),
    ],
)
logger = logging.getLogger("meeting-recorder")


async def run_scan_and_record():
    """Scan emails for meeting invites and schedule recordings."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from src.meeting_scheduler import scan_emails_and_schedule, get_upcoming_meetings

    logger.info("=== Scanning emails for meeting invites ===")
    scheduler = AsyncIOScheduler()
    scheduler.start()

    await scan_emails_and_schedule(scheduler)

    upcoming = await get_upcoming_meetings()
    if upcoming:
        logger.info(f"Upcoming meetings ({len(upcoming)}):")
        for m in upcoming:
            logger.info(f"  - {m['subject']} at {m['start_time']} ({m['status']})")

        logger.info("Waiting for scheduled recordings... (Ctrl+C to stop)")
        try:
            while True:
                await asyncio.sleep(30)
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown()
    else:
        logger.info("No upcoming meetings to record")
        scheduler.shutdown()


async def run_continuous():
    """Run continuously — scan emails every 15 minutes and auto-record."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from src.config import load_config
    from src.meeting_scheduler import scan_emails_and_schedule

    config = load_config()
    scan_cron = config.get("scheduler", {}).get("scan_cron", "*/15 * * * *")
    tz = config.get("scheduler", {}).get("timezone", "UTC")

    scheduler = AsyncIOScheduler(timezone=tz)

    # Parse cron string
    parts = scan_cron.split()
    cron_kwargs = {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }

    async def _scan_task():
        await scan_emails_and_schedule(scheduler)

    scheduler.add_job(
        _scan_task,
        trigger=CronTrigger(**cron_kwargs, timezone=tz),
        id="scan_meetings",
        name="Scan emails for meetings",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(f"Scheduler started — scanning emails every: {scan_cron}")

    # Run initial scan immediately
    await scan_emails_and_schedule(scheduler)

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler stopped")


async def run_record_now(meeting_url: str, duration: int | None = None):
    """Record a meeting immediately given a URL."""
    from src.meeting_recorder import record_meeting_now

    logger.info(f"=== Recording meeting: {meeting_url} ===")
    result = await record_meeting_now(
        meeting_url=meeting_url,
        subject="manual_recording",
        duration_seconds=duration,
    )
    logger.info(f"Recording result: {result}")


def main():
    parser = argparse.ArgumentParser(description="Meeting Auto-Recorder")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scan", action="store_true", help="Scan emails once and schedule recordings")
    group.add_argument("--schedule", action="store_true", help="Run continuously (scan every 15 min)")
    group.add_argument("--record", type=str, metavar="URL", help="Record a meeting now given a URL")
    parser.add_argument("--duration", type=int, help="Recording duration in seconds (for --record)")

    args = parser.parse_args()
    asyncio.run(_async_main(args))


async def _async_main(args):
    await db.init_db()

    if args.scan:
        await run_scan_and_record()
    elif args.schedule:
        await run_continuous()
    elif args.record:
        await run_record_now(args.record, args.duration)


if __name__ == "__main__":
    main()
