import logging
import os
from dotenv import load_dotenv

load_dotenv()

from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from bot.handlers import (
    cmd_start, cmd_today, cmd_week, cmd_body, cmd_workout, cmd_report,
    cmd_profile, cmd_update,
    handle_photo, handle_text, handle_callback,
)
from bot.scheduler import start_scheduler

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")

    chat_id = os.getenv("ALLOWED_CHAT_ID", "")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("body", cmd_body))
    app.add_handler(CommandHandler("workout", cmd_workout))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Start scheduler only if chat_id is configured
    if chat_id and chat_id != "YOUR_CHAT_ID_HERE":
        bot = app.bot
        # Schedule after event loop starts
        async def post_init(app):
            start_scheduler(bot, chat_id)

        app.post_init = post_init
    else:
        logger.warning("ALLOWED_CHAT_ID not set — scheduler disabled. Send /start to get your Chat ID.")

    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
