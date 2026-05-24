import logging
import os
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from db import crud

logger = logging.getLogger(__name__)


def start_scheduler(bot: Bot, chat_id: str) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    morning_time = os.getenv("MORNING_CHECK_TIME", "08:00").split(":")
    evening_time = os.getenv("EVENING_SUMMARY_TIME", "21:00").split(":")
    weekly_day = os.getenv("WEEKLY_REPORT_DAY", "monday")

    scheduler.add_job(
        _morning_check,
        "cron",
        hour=int(morning_time[0]),
        minute=int(morning_time[1]),
        kwargs={"bot": bot, "chat_id": chat_id},
    )

    scheduler.add_job(
        _evening_summary,
        "cron",
        hour=int(evening_time[0]),
        minute=int(evening_time[1]),
        kwargs={"bot": bot, "chat_id": chat_id},
    )

    scheduler.add_job(
        _weekly_report,
        "cron",
        day_of_week=weekly_day,
        hour=9,
        minute=0,
        kwargs={"bot": bot, "chat_id": chat_id},
    )

    scheduler.start()
    logger.info("Scheduler started")
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
        lines.append("昨天没有饮食记录。\n")

    # Protein goal based on body weight
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

    if not diet:
        await bot.send_message(
            chat_id=chat_id,
            text="今天还没有饮食记录 📸\n\n记得把今天的薄荷截图发给我，或者直接发数字告诉我吃了什么。",
        )
        return

    net = (diet.total_calories or 0) - (diet.exercise_calories or 0)
    deficit = bmr - net
    protein_pct = int(diet.protein_g / diet.protein_goal_g * 100) if diet.protein_goal_g else 0
    protein_icon = "✓ 接近目标！" if protein_pct >= 85 else ("✅ 超额完成！" if protein_pct >= 100 else "")

    # Week cumulative deficit
    start = today - timedelta(days=6)
    summaries = crud.get_daily_summaries_range(start, today)
    week_deficit = sum(s.calorie_deficit or 0 for s in summaries)
    fat_burned = week_deficit / 7700

    lines = [
        "今日收工 🌙\n",
        "📊 今日数据",
        f"热量：{diet.total_calories:.0f} kcal（缺口 {deficit:.0f} kcal）",
        f"蛋白质：{diet.protein_g:.0f}g / {diet.protein_goal_g:.0f}g（{protein_pct}%）{protein_icon}",
        f"碳水：{diet.carbs_g:.0f}g | 脂肪：{diet.fat_g:.0f}g\n",
        f"本周累计缺口：{week_deficit:.0f} kcal（约消耗 {fat_burned:.2f}kg 脂肪）",
    ]

    await bot.send_message(chat_id=chat_id, text="\n".join(lines))


async def _weekly_report(bot: Bot, chat_id: str) -> None:
    from bot.handlers import _generate_report
    await bot.send_message(chat_id=chat_id, text="正在生成周报...")
    report = await _generate_report()
    await bot.send_message(chat_id=chat_id, text=report)
