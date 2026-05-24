import logging
import os
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from db import crud

logger = logging.getLogger(__name__)

UK_TZ = ZoneInfo("Europe/London")


def start_scheduler(bot: Bot, chat_id: str) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=UK_TZ)

    morning_time = os.getenv("MORNING_CHECK_TIME", "08:00").split(":")
    weekly_day = os.getenv("WEEKLY_REPORT_DAY", "monday")

    scheduler.add_job(
        _morning_check,
        "cron",
        hour=int(morning_time[0]),
        minute=int(morning_time[1]),
        timezone=UK_TZ,
        kwargs={"bot": bot, "chat_id": chat_id},
    )

    scheduler.add_job(
        _evening_summary,
        "cron",
        hour=21,
        minute=30,
        timezone=UK_TZ,
        kwargs={"bot": bot, "chat_id": chat_id},
    )

    scheduler.add_job(
        _weekly_report,
        "cron",
        day_of_week=weekly_day,
        hour=9,
        minute=0,
        timezone=UK_TZ,
        kwargs={"bot": bot, "chat_id": chat_id},
    )

    scheduler.start()
    logger.info("Scheduler started (timezone: Europe/London)")
    return scheduler


async def _morning_check(bot: Bot, chat_id: str) -> None:
    yesterday = date.today() - timedelta(days=1)
    diet = crud.get_diet_record(yesterday)
    body = crud.get_latest_body_composition()
    bmr = float(os.getenv("USER_BMR", 1916))

    lines = ["早上好！☀️\n"]

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
        lines.append("昨天没有饮食记录，已从统计中排除。\n")

    weight = body.weight_kg if body else 90
    protein_goal = float(os.getenv("USER_PROTEIN_GOAL_PER_KG", 1.8)) * weight

    lines += [
        "今天目标：",
        f"• 蛋白质 ≥ {protein_goal:.0f}g",
        f"• 热量控制在 {bmr - 500:.0f}–{bmr - 300:.0f} kcal",
        "\n记得发今天的饮食截图 📸",
    ]

    await bot.send_message(chat_id=chat_id, text="\n".join(lines))


async def _evening_summary(bot: Bot, chat_id: str) -> None:
    today = date.today()
    diet = crud.get_diet_record(today)
    bmr = float(os.getenv("USER_BMR", 1916))

    # ── 过去30天（只统计有记录的天）──────────────────────────
    month_start = today - timedelta(days=29)
    month_records = crud.get_diet_records_range(month_start, today)
    tracked_days = len(month_records)

    if tracked_days > 0:
        month_deficit = sum(
            bmr - (r.total_calories or 0) + (r.exercise_calories or 0)
            for r in month_records
        )
        avg_daily_deficit = month_deficit / tracked_days
        monthly_projected_deficit = avg_daily_deficit * 30
        monthly_fat_loss = monthly_projected_deficit / 7700
    else:
        avg_daily_deficit = 0
        monthly_fat_loss = 0

    # ── 今天没有记录 ──────────────────────────────────────────
    if not diet:
        lines = [
            "📸 今天还没有饮食记录\n",
            "今天数据缺失，不计入统计。\n",
        ]
        if tracked_days > 0:
            lines += [
                f"📅 过去30天已记录 {tracked_days} 天",
                f"📉 日均热量缺口：{avg_daily_deficit:.0f} kcal",
                f"📊 按此速度，每月预计减脂：{monthly_fat_loss:.2f} kg",
            ]
        await bot.send_message(chat_id=chat_id, text="\n".join(lines))
        return

    # ── 今天有记录 ────────────────────────────────────────────
    net = (diet.total_calories or 0) - (diet.exercise_calories or 0)
    today_deficit = bmr - net
    protein_pct = int(diet.protein_g / diet.protein_goal_g * 100) if diet.protein_goal_g else 0
    protein_icon = "✅ 超额完成！" if protein_pct >= 100 else ("👍 接近目标" if protein_pct >= 85 else "")

    lines = [
        "今日收工 🌙\n",
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

    await bot.send_message(chat_id=chat_id, text="\n".join(lines))


async def _weekly_report(bot: Bot, chat_id: str) -> None:
    from bot.handlers import _generate_report
    await bot.send_message(chat_id=chat_id, text="正在生成周报...")
    report = await _generate_report()
    await bot.send_message(chat_id=chat_id, text=report)
