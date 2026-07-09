import logging
import os
from datetime import date, timedelta

from db import crud
from wecom.client import send_text

logger = logging.getLogger(__name__)


async def _morning_check(user_id: str) -> None:
    from utils.weather import get_london_weather, format_weather
    from utils.quotes import get_random_quote
    from utils.hitokoto import fetch_hitokoto
    from llm.analyst import generate_morning_quote_commentary

    yesterday = date.today() - timedelta(days=1)
    diet = crud.get_diet_record(yesterday)
    body = crud.get_latest_body_composition()
    bmr = crud.get_bmr()

    lines = ["早上好。☀️\n"]

    try:
        weather = await get_london_weather()
        lines.append(format_weather(weather) + "\n")
    except Exception:
        pass

    if diet:
        net = (diet.total_calories or 0) - (diet.exercise_calories or 0)
        deficit = bmr - net
        protein_pct = int(diet.protein_g / diet.protein_goal_g * 100) if diet.protein_goal_g else 0
        lines += [
            "昨天数据：",
            f"🔥 热量摄入：{diet.total_calories:.0f} kcal（缺口 {deficit:.0f} kcal）",
            f"🥩 蛋白质：{diet.protein_g:.0f}g / {diet.protein_goal_g:.0f}g（{protein_pct}%）\n",
        ]
    else:
        lines.append("昨天没有饮食记录。没有数据就没有进步——今天记录好。\n")

    weight = body.weight_kg if body else 90
    protein_goal = float(os.getenv("USER_PROTEIN_GOAL_PER_KG", 1.8)) * weight

    lines += [
        "今天的任务：",
        f"• 蛋白质 ≥ {protein_goal:.0f}g，不达标就是欠债",
        f"• 热量控制在 {bmr - 500:.0f}–{bmr - 300:.0f} kcal",
    ]

    result = get_random_quote()
    if result:
        quote, source = result
        try:
            commentary = await generate_morning_quote_commentary(quote)
            lines += [
                "\n📖 今日金句",
                f"「{quote}」",
                f"——{source}",
                f"\n{commentary}",
            ]
        except Exception:
            lines += ["\n📖 今日金句", f"「{quote}」", f"——{source}"]

    hitokoto = await fetch_hitokoto()
    if hitokoto:
        ht_text, ht_source = hitokoto
        lines += ["\n💬 每日一言", f"「{ht_text}」", f"——{ht_source}"]

    lines.append("\n今天状态怎么样？有什么想说的也可以发给我 📔")

    send_text(user_id, "\n".join(lines))


async def _evening_summary(user_id: str) -> None:
    today = date.today()
    diet = crud.get_diet_record(today)
    bmr = crud.get_bmr()

    month_start = today - timedelta(days=29)
    month_records = crud.get_diet_records_range(month_start, today)
    tracked_days = len(month_records)

    if tracked_days > 0:
        month_deficit = sum(
            bmr - (r.total_calories or 0) + (r.exercise_calories or 0)
            for r in month_records
        )
        avg_daily_deficit = month_deficit / tracked_days
        monthly_fat_loss = (avg_daily_deficit * 30) / 7700
    else:
        avg_daily_deficit = 0
        monthly_fat_loss = 0

    if not diet:
        lines = ["📸 今天还没有饮食记录\n", "今天数据缺失，不计入统计。\n"]
        if tracked_days > 0:
            lines += [
                f"📅 过去30天已记录 {tracked_days} 天",
                f"📉 日均热量缺口：{avg_daily_deficit:.0f} kcal",
                f"📊 按此速度，每月预计减脂：{monthly_fat_loss:.2f} kg",
            ]
        send_text(user_id, "\n".join(lines))
        return

    net = (diet.total_calories or 0) - (diet.exercise_calories or 0)
    today_deficit = bmr - net
    protein_pct = int(diet.protein_g / diet.protein_goal_g * 100) if diet.protein_goal_g else 0
    protein_icon = "✅ 超额完成！" if protein_pct >= 100 else ("👍 接近目标" if protein_pct >= 85 else "")

    lines = [
        "今天收工，来对账。🌙\n",
        "📊 今日数据",
        f"🔥 热量：{diet.total_calories:.0f} kcal（缺口 {today_deficit:.0f} kcal）",
        f"🥩 蛋白质：{diet.protein_g:.0f}g / {diet.protein_goal_g:.0f}g（{protein_pct}%）{protein_icon}",
        f"🍚 碳水：{diet.carbs_g:.0f}g | 🧈 脂肪：{diet.fat_g:.0f}g",
    ]

    if tracked_days > 0:
        lines += [
            f"\n📅 过去30天已记录 {tracked_days} 天（遗漏天不计入）",
            f"📉 日均热量缺口：{avg_daily_deficit:.0f} kcal",
            f"📊 按此速度，每月预计减脂：{monthly_fat_loss:.2f} kg",
        ]

    send_text(user_id, "\n".join(lines))


async def _notes_reminder(user_id: str) -> None:
    from utils.notes import get_today_notes
    today_notes = get_today_notes(date.today())
    if today_notes:
        send_text(user_id, "📝 下午好！今天已经有笔记了，还有什么要补充吗？")
    else:
        send_text(user_id, "📝 下午好！记录一下今天的工作或学习内容吧，发给我就行。")


async def _weekly_notes_summary(user_id: str) -> None:
    from utils.notes import get_week_notes
    from llm.analyst import generate_weekly_notes_summary
    today = date.today()
    start = today - timedelta(days=6)
    notes_text = get_week_notes(start, today)
    send_text(user_id, "📚 正在整理本周笔记...")
    summary = await generate_weekly_notes_summary(notes_text)
    send_text(user_id, f"📚 本周笔记整理\n\n{summary}")


async def _weekly_report(user_id: str) -> None:
    from bot.handlers import _generate_report
    send_text(user_id, "正在生成周报...")
    report = await _generate_report()
    send_text(user_id, report)
