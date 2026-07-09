"""
WeCom trigger script for scheduled jobs.
Called by system cron (TZ=Europe/London) — no APScheduler needed.

Usage:
    python3 scripts/trigger_wecom.py <job>

Jobs:
    morning         — 08:00 UK, morning greeting + quote
    evening         — 21:30 UK, evening summary
    notes           — 16:00 UK, notes reminder
    weekly_report   — Monday 09:00 UK, weekly fitness report
    weekly_notes    — Sunday 20:00 UK, weekly notes summary
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _run(job: str) -> None:
    user_id = os.getenv("WECOM_USER_ID")
    if not user_id:
        raise RuntimeError("WECOM_USER_ID not set in .env")

    from wecom.scheduler import (
        _morning_check,
        _evening_summary,
        _notes_reminder,
        _weekly_report,
        _weekly_notes_summary,
    )

    dispatch = {
        "morning":       _morning_check,
        "evening":       _evening_summary,
        "notes":         _notes_reminder,
        "weekly_report": _weekly_report,
        "weekly_notes":  _weekly_notes_summary,
    }

    fn = dispatch.get(job)
    if fn is None:
        valid = ", ".join(dispatch)
        raise ValueError(f"Unknown job '{job}'. Valid: {valid}")

    logger.info("Running WeCom job: %s", job)
    await fn(user_id=user_id)
    logger.info("Job done: %s", job)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    job = sys.argv[1].strip()
    asyncio.run(_run(job))


if __name__ == "__main__":
    main()
