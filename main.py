import logging
import os
from dotenv import load_dotenv

load_dotenv()

from telegram import BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from bot.handlers import (
    cmd_start, cmd_today, cmd_week, cmd_body, cmd_workout, cmd_report,
    cmd_profile, cmd_update, cmd_stats, cmd_mode, cmd_server, _server_watch,
    cmd_food, handle_photo, handle_text, handle_document, handle_callback,
)

# Commands shown when you type "/" or tap the menu button — no more typing.
_COMMANDS = [
    BotCommand("start", "主菜单 / 打开按钮"),
    BotCommand("food", "🍎 记食物（扫条码 / 文字描述）"),
    BotCommand("today", "今日数据"),
    BotCommand("week", "本周汇总"),
    BotCommand("body", "身体成分"),
    BotCommand("workout", "训练记录"),
    BotCommand("stats", "体重统计"),
    BotCommand("profile", "个人资料 / BMR"),
    BotCommand("report", "生成周报"),
    BotCommand("mode", "切换对话模式"),
]


async def _post_init(app: Application) -> None:
    await app.bot.set_my_commands(_COMMANDS)

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

    app = Application.builder().token(token).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("food", cmd_food))
    app.add_handler(CommandHandler("nutrition", cmd_food))  # alias
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("body", cmd_body))
    app.add_handler(CommandHandler("workout", cmd_workout))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("server", cmd_server))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.job_queue.run_repeating(_server_watch, interval=1800, first=120)


    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
