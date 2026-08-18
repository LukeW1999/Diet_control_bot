from telegram import InlineKeyboardButton, InlineKeyboardMarkup

MODE_LABELS = {
    "auto":   "🤖 自动",
    "coach":  "🏋️ 教练",
    "chat":   "💬 聊天",
}


def main_menu(refeed_on: bool = False) -> InlineKeyboardMarkup:
    refeed_label = "🔁 Refeed 日：开 ✅（点关）" if refeed_on else "🔁 Refeed 日：关（点开）"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("今日数据", callback_data="today"),
            InlineKeyboardButton("本周汇总", callback_data="week"),
        ],
        [
            InlineKeyboardButton("身体成分", callback_data="body"),
            InlineKeyboardButton("本月汇总", callback_data="month"),
        ],
        [InlineKeyboardButton("生成周报", callback_data="report")],
        [InlineKeyboardButton("🍎 记食物（扫码/描述）", callback_data="food_on")],
        [InlineKeyboardButton("📚 食物库", callback_data="food_lib")],
        [InlineKeyboardButton(refeed_label, callback_data="refeed_toggle")],
    ])


def mode_menu(current: str) -> InlineKeyboardMarkup:
    def btn(mode: str) -> InlineKeyboardButton:
        label = MODE_LABELS[mode]
        if mode == current:
            label = "✅ " + label
        return InlineKeyboardButton(label, callback_data=f"set_mode:{mode}")
    return InlineKeyboardMarkup([[btn("auto"), btn("coach"), btn("chat")]])


def food_library_menu(items: list) -> InlineKeyboardMarkup:
    """One button per saved product; the label carries the last amount eaten so a
    repeat log is a single tap away."""
    rows = []
    for it in items:
        label = it.name if not it.brand else f"{it.name}（{it.brand}）"
        if it.last_grams:
            label += f" · 上次{it.last_grams:g}g"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"food_pick:{it.id}")])
    return InlineKeyboardMarkup(rows)


# Where Luke actually goes. Anything else is reachable with "/tz Area/City".
TZ_PRESETS = [("🇬🇧 英国", "Europe/London"),
              ("🇸🇬 新加坡", "Asia/Singapore"),
              ("🇨🇳 中国", "Asia/Shanghai")]


def tz_menu(current: str) -> InlineKeyboardMarkup:
    def btn(label: str, zone: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(("✅ " if zone == current else "") + label,
                                    callback_data=f"tz_set:{zone}")
    return InlineKeyboardMarkup([[btn(l, z) for l, z in TZ_PRESETS]])
