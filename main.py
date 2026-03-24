"""Meeting Auto-Recorder — Entry Point.

Modes:
  --tray          Run hidden in system tray (default for auto-start)
  --scan          One-shot: scan emails and wait for recordings
  --schedule      Run continuously in foreground
  --record URL    Record a meeting immediately
  --install       Enable auto-start on Windows boot
  --uninstall     Disable auto-start
  --status        Show current status and exit
"""

import argparse
import asyncio
import logging
import sys
import threading

from src.config import BASE_DIR, LOG_PATH

# Ensure data dir exists before logging
(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_PATH), mode="a"),
    ],
)
# Only add console handler if not in tray mode
if "--tray" not in sys.argv:
    logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

logger = logging.getLogger("meeting-recorder")


async def run_scan_and_record():
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


async def run_continuous(with_tray: bool = False):
    """Run continuously — scan emails on schedule and auto-record meetings."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from src.config import get_scheduler_config
    from src.meeting_scheduler import scan_emails_and_schedule

    sched_cfg = get_scheduler_config()
    scan_cron = sched_cfg["scan_cron"]
    tz = sched_cfg["timezone"]

    scheduler = AsyncIOScheduler(timezone=tz)

    parts = scan_cron.split()
    cron_kwargs = {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }

    async def _scan_task():
        count = await scan_emails_and_schedule(scheduler)
        if with_tray and count > 0:
            from src.tray_app import show_notification
            show_notification("Meetings Found", f"Scheduled {count} new meeting recording(s)")

    scheduler.add_job(
        _scan_task,
        trigger=CronTrigger(**cron_kwargs, timezone=tz),
        id="scan_meetings",
        name="Scan emails for meetings",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(f"Scheduler started — scanning every: {scan_cron} ({tz})")

    # Run initial scan
    await scan_emails_and_schedule(scheduler)

    if with_tray:
        from src.tray_app import show_notification
        show_notification("Meeting Recorder", "Running in background. Monitoring emails for meetings.")

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler stopped")


async def run_record_now(meeting_url: str, duration: int | None = None):
    from src.meeting_recorder import record_meeting_now

    logger.info(f"=== Recording meeting: {meeting_url} ===")
    result = await record_meeting_now(
        meeting_url=meeting_url,
        subject="manual_recording",
        duration_seconds=duration,
    )
    logger.info(f"Recording result: {result}")


def run_tray_mode():
    """Run in system tray — hidden, no console window."""
    from src import db
    from src.tray_app import start_tray

    loop = asyncio.new_event_loop()

    # Initialize DB
    loop.run_until_complete(db.init_db())

    # Start the scheduler in a background thread
    def _run_scheduler():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_continuous(with_tray=True))

    sched_thread = threading.Thread(target=_run_scheduler, daemon=True)
    sched_thread.start()

    # System tray runs on main thread (required by pystray)
    start_tray(event_loop=loop)


def run_install():
    from src.autostart import enable_autostart, is_autostart_enabled
    if is_autostart_enabled():
        print("Auto-start is already enabled.")
    else:
        if enable_autostart():
            print("Auto-start enabled. Meeting Recorder will start hidden on boot.")
        else:
            print("Failed to enable auto-start.")


def run_uninstall():
    from src.autostart import disable_autostart
    if disable_autostart():
        print("Auto-start disabled.")
    else:
        print("Failed to disable auto-start.")


async def run_status():
    from src import db
    from src.meeting_scheduler import get_upcoming_meetings, get_meeting_stats
    from src.config import get_recording_config, get_email_accounts, get_tray_config
    from src.autostart import is_autostart_enabled

    await db.init_db()

    rec_cfg = get_recording_config()
    accounts = get_email_accounts()
    tray_cfg = get_tray_config()
    stats = await get_meeting_stats()
    upcoming = await get_upcoming_meetings()

    print("=" * 55)
    print("  MEETING AUTO-RECORDER STATUS")
    print("=" * 55)
    print()
    print(f"  Auto-start:       {'Enabled' if is_autostart_enabled() else 'Disabled'}")
    print(f"  Recording path:   {rec_cfg['output_dir']}")
    print(f"  Email accounts:   {len(accounts)}")
    for a in accounts:
        print(f"    - {a.get('name', a.get('imap_user', '?'))}")
    print()
    print(f"  Stats:")
    print(f"    Total meetings: {stats['total']}")
    print(f"    Scheduled:      {stats['scheduled']}")
    print(f"    Recorded:       {stats['recorded']}")
    print(f"    Failed:         {stats['failed']}")
    print()
    if upcoming:
        print(f"  Upcoming ({len(upcoming)}):")
        for m in upcoming:
            print(f"    - {m['subject']} at {m['start_time']}")
    else:
        print("  No upcoming meetings")
    print()
    print(f"  Hotkeys:")
    print(f"    Dashboard:      {tray_cfg['hotkey_toggle_dashboard']}")
    print(f"    Stop recording: {tray_cfg['hotkey_stop_recording']}")
    print()
    print("=" * 55)


def main():
    parser = argparse.ArgumentParser(
        description="Meeting Auto-Recorder — records meetings automatically",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tray", action="store_true", help="Run hidden in system tray (background mode)")
    group.add_argument("--scan", action="store_true", help="Scan emails once and schedule recordings")
    group.add_argument("--schedule", action="store_true", help="Run continuously in foreground")
    group.add_argument("--record", type=str, metavar="URL", help="Record a meeting now given a URL")
    group.add_argument("--install", action="store_true", help="Enable auto-start on Windows boot")
    group.add_argument("--uninstall", action="store_true", help="Disable auto-start")
    group.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--duration", type=int, help="Recording duration in seconds (for --record)")

    args = parser.parse_args()

    if args.tray:
        run_tray_mode()
    elif args.install:
        run_install()
    elif args.uninstall:
        run_uninstall()
    elif args.status:
        asyncio.run(run_status())
    else:
        asyncio.run(_async_main(args))


async def _async_main(args):
    from src import db
    await db.init_db()

    if args.scan:
        await run_scan_and_record()
    elif args.schedule:
        await run_continuous()
    elif args.record:
        await run_record_now(args.record, args.duration)


if __name__ == "__main__":
    main()
