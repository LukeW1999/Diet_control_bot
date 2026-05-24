from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("今日数据", callback_data="today"),
            InlineKeyboardButton("本周汇总", callback_data="week"),
        ],
        [
            InlineKeyboardButton("身体成分", callback_data="body"),
            InlineKeyboardButton("训练记录", callback_data="workout"),
        ],
        [InlineKeyboardButton("生成周报", callback_data="report")],
    ])
