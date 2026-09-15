"""
Standalone trigger script for scheduled jobs.
Called by system cron (TZ=Europe/London) — no APScheduler needed.

Usage:
    python3 scripts/trigger.py <job>

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

# ── bootstrap ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from telegram import Bot

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── job implementations ───────────────────────────────────────────────────────

async def _run(job: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ALLOWED_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or ALLOWED_CHAT_ID not set in .env")

    bot = Bot(token=token)

    # Import here so project path is already inserted
    from bot.scheduler import (
        _morning_check,
        _evening_summary,
        _notes_reminder,
        _weekly_report,
        _weekly_notes_summary,
    )

    dispatch = {
        "morning":        _morning_check,
        "evening":        _evening_summary,
        "notes":          _notes_reminder,
        "weekly_report":  _weekly_report,
        "weekly_notes":   _weekly_notes_summary,
    }

    if job == "evening":
        async with bot:
            await _evening_everyone(bot, chat_id)
        return

    fn = dispatch.get(job)
    if fn is None:
        valid = ", ".join(dispatch)
        raise ValueError(f"Unknown job '{job}'. Valid: {valid}")

    logger.info("Running job: %s", job)
    async with bot:
        await fn(bot=bot, chat_id=chat_id)
    logger.info("Job done: %s", job)


async def _evening_everyone(bot, primary_chat_id: str) -> None:
    """Run hourly. Each person is nudged when it is evening where they are, not
    where the server is: one of them is seven hours ahead."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from bot.scheduler import build_evening_text
    from db import crud
    from utils import tenant

    for user in sorted(tenant.known()):
        tenant.set_current(user)
        profile = crud.get_user_profile()
        zone = (profile.timezone if profile and profile.timezone else None) or "Europe/London"
        hour = (profile.evening_hour if profile and profile.evening_hour else None) or 21
        local = datetime.now(ZoneInfo(zone))
        if local.hour != hour:
            logger.info("evening: %s is %02d:00 in %s, not %02d:00", user, local.hour, zone, hour)
            continue
        text = build_evening_text()
        if user == tenant.primary():
            await bot.send_message(chat_id=primary_chat_id, text=text)
        else:
            from wecom.client import send_text
            send_text(user, text)
        logger.info("evening sent to %s (%s %02d:00)", user, zone, hour)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    job = sys.argv[1].strip()
    asyncio.run(_run(job))


if __name__ == "__main__":
    main()
