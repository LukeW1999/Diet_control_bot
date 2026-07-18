from telegram import InlineKeyboardButton, InlineKeyboardMarkup

MODE_LABELS = {
    "auto":   "🤖 自动",
    "coach":  "🏋️ 教练",
    "chat":   "💬 聊天",
}


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
        [InlineKeyboardButton("🍎 记食物（扫码/描述）", callback_data="food_on")],
    ])


def mode_menu(current: str) -> InlineKeyboardMarkup:
    def btn(mode: str) -> InlineKeyboardButton:
        label = MODE_LABELS[mode]
        if mode == current:
            label = "✅ " + label
        return InlineKeyboardButton(label, callback_data=f"set_mode:{mode}")
    return InlineKeyboardMarkup([[btn("auto"), btn("coach"), btn("chat")]])
