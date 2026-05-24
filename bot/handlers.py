import asyncio
import json
import logging
import os
import re
from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from db import crud
from llm import parsers, analyst
from utils.image import save_and_encode
from .keyboards import main_menu

logger = logging.getLogger(__name__)

# Album (multi-photo) state: media_group_id -> {images, update, wait_msg}
_pending_albums: dict = {}
_background_tasks: set = set()  # keep task references to prevent GC
_conversation_history: list[dict] = []  # last N turns for multi-turn context
_MAX_HISTORY_TURNS = 8  # keep 8 exchanges (16 messages)


def _append_history(user_text: str, assistant_text: str) -> None:
    _conversation_history.append({"role": "user", "content": user_text})
    _conversation_history.append({"role": "assistant", "content": assistant_text})
    # Trim to last N turns
    max_msgs = _MAX_HISTORY_TURNS * 2
    if len(_conversation_history) > max_msgs:
        del _conversation_history[:-max_msgs]


def _allowed(update: Update) -> bool:
    allowed = os.getenv("ALLOWED_CHAT_ID", "")
    if not allowed or allowed == "YOUR_CHAT_ID_HERE":
        return True  # not configured yet — allow all during setup
    return str(update.effective_chat.id) == allowed


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    # Log chat_id so user can copy it into .env
    logger.info(f"Chat ID: {update.effective_chat.id}")
    await update.message.reply_text(
        "👋 健康管理 Bot 已启动！\n\n"
        f"你的 Chat ID：`{update.effective_chat.id}`\n"
        "请把这个 ID 填入 .env 文件的 ALLOWED_CHAT_ID。\n\n"
        "📸 发图片给我：\n"
        "  • 薄荷健康饮食截图 → 记录今日饮食\n"
        "  • 体重秤身体成分报告 → 记录体成分\n\n"
        "💬 发文字给我：\n"
        "  • 训练记录（如 深蹲80kg 5组5次）\n"
        "  • 今天体重 91.2\n"
        "  • 任何关于你健康数据的问题\n\n"
        "📋 指令：/today /week /body /workout /report /profile /update\n\n"
        "💡 /profile 查看个人资料和当前 BMR\n"
        "/update age 27 · /update height 172 · /update gender male\n"
        "/update goal 74.8 · /update protein 1.8",
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )


async def cmd_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    p = crud.get_user_profile()
    body = crud.get_latest_body_composition()
    bmr = crud.get_bmr()

    lines = ["👤 个人资料\n"]
    if p:
        if p.age:
            lines.append(f"年龄：{p.age} 岁")
        if p.height_cm:
            lines.append(f"身高：{p.height_cm} cm")
        if p.gender:
            lines.append(f"性别：{'男' if p.gender == 'male' else '女'}")
        if p.weight_goal_kg:
            lines.append(f"目标体重：{p.weight_goal_kg} kg")
        if p.protein_goal_per_kg:
            lines.append(f"蛋白质目标：{p.protein_goal_per_kg} g/kg")
    else:
        lines.append("（还没有资料，用 /update 设置）")

    weight_str = f"（当前体重 {body.weight_kg} kg）" if body and body.weight_kg else ""
    lines.append(f"\n🔥 当前基础代谢：{bmr:.0f} kcal/天 {weight_str}")

    if not (p and p.age and p.height_cm):
        lines.append("\n💡 设置资料后 BMR 将自动随体重变化：\n/update age 27\n/update height 172\n/update gender male")

    await update.message.reply_text("\n".join(lines))


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Pure-Python weight stats — no LLM, guaranteed accurate numbers."""
    if not _allowed(update):
        return

    today = date.today()
    records = crud.get_body_compositions_range(today - timedelta(days=730), today)
    records = [r for r in records if r.weight_kg is not None]

    if not records:
        await update.message.reply_text("暂无体重数据。")
        return

    bmr = crud.get_bmr()
    goal = float(os.getenv("USER_WEIGHT_GOAL", 75.0))
    latest = records[-1]
    lines = [f"📊 体重统计（纯Python计算）\n"]

    # Current
    lines.append(f"⚖️ 最新体重：{latest.weight_kg} kg（{latest.date}）")
    lines.append(f"🎯 目标：{goal} kg　距离：{latest.weight_kg - goal:.1f} kg\n")

    # Peak
    peak = max(records, key=lambda r: r.weight_kg)
    peak_loss = peak.weight_kg - latest.weight_kg
    peak_days = (latest.date - peak.date).days
    if peak_days > 0:
        lines.append(f"📉 距峰值（{peak.weight_kg}kg，{peak.date}）")
        lines.append(f"   已减 {peak_loss:.2f} kg / {peak_days} 天（{peak_days/7:.1f} 周）")
        lines.append(f"   均速 {peak_loss/peak_days*7:.2f} kg/周\n")

    # Recent segments
    checkpoints = [7, 14, 30]
    for days_ago in checkpoints:
        cutoff = today - timedelta(days=days_ago)
        past = [r for r in records if r.date <= cutoff]
        if not past:
            continue
        ref = past[-1]
        diff = latest.weight_kg - ref.weight_kg
        actual_days = (latest.date - ref.date).days
        if actual_days == 0:
            continue
        arrow = "▼" if diff < 0 else "▲"
        lines.append(
            f"过去 ~{days_ago}天（{ref.date}）：{arrow} {abs(diff):.2f} kg"
            f"（{actual_days}天，{diff/actual_days*7:.2f} kg/周）"
        )

    # BMR & deficit
    lines.append(f"\n🔥 BMR：{bmr:.0f} kcal")
    summaries = crud.get_daily_summaries_range(today - timedelta(days=6), today)
    if summaries:
        avg_deficit = sum(s.calorie_deficit or 0 for s in summaries) / len(summaries)
        lines.append(f"📉 近7天均缺口：{avg_deficit:.0f} kcal/天")
        projected = avg_deficit * 30 / 7700
        lines.append(f"📊 按此速度月减脂：{projected:.2f} kg")

    # Target pace
    safe_low = latest.weight_kg * 0.005
    safe_high = latest.weight_kg * 0.01
    lines.append(f"\n✅ 安全减速：{safe_low:.2f}–{safe_high:.2f} kg/周")

    await update.message.reply_text("\n".join(lines))


async def cmd_update(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "用法：\n"
            "/update age 27\n"
            "/update height 172\n"
            "/update gender male\n"
            "/update goal 74.8\n"
            "/update protein 1.8"
        )
        return

    key_map = {
        "age": ("age", int, "岁"),
        "height": ("height_cm", float, "cm"),
        "gender": ("gender", str, ""),
        "goal": ("weight_goal_kg", float, "kg"),
        "protein": ("protein_goal_per_kg", float, "g/kg"),
    }

    key = args[0].lower()
    raw = args[1]

    if key not in key_map:
        await update.message.reply_text(f"未知字段 {key}，可用：age / height / gender / goal / protein")
        return

    field, cast, unit = key_map[key]
    try:
        value = cast(raw)
    except ValueError:
        await update.message.reply_text(f"数值格式不对：{raw}")
        return

    crud.update_user_profile(**{field: value})
    bmr = crud.get_bmr()
    await update.message.reply_text(
        f"✅ 已更新 {key} = {value}{unit}\n🔥 当前 BMR：{bmr:.0f} kcal/天"
    )


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    msg = _build_today_summary(date.today())
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    today = date.today()
    start = today - timedelta(days=6)
    records = crud.get_daily_summaries_range(start, today)
    if not records:
        await update.message.reply_text("本周还没有数据。")
        return

    total_deficit = sum(r.calorie_deficit or 0 for r in records)
    avg_deficit = total_deficit / len(records)
    avg_cal = sum(r.total_calories_in or 0 for r in records) / len(records)
    protein_days = sum(1 for r in records if r.protein_achievement_pct and r.protein_achievement_pct >= 90)

    body_records = crud.get_body_compositions_range(start, today)
    weight_trend = ""
    if len(body_records) >= 2:
        delta = body_records[-1].weight_kg - body_records[0].weight_kg
        sign = "↓" if delta < 0 else "↑"
        weight_trend = f"\n⚖️ 体重变化：{sign}{abs(delta):.1f}kg（{body_records[0].date} → {body_records[-1].date}）"

    fat_burned = total_deficit / 7700
    text = (
        f"📊 本周汇总（{start} ~ {today}）\n\n"
        f"🔥 平均每日摄入：{avg_cal:.0f} kcal\n"
        f"📉 累计热量缺口：{total_deficit:.0f} kcal（≈ {fat_burned:.2f}kg 脂肪）\n"
        f"📈 日均缺口：{avg_deficit:.0f} kcal\n"
        f"🥩 蛋白质达标天数：{protein_days}/{len(records)} 天"
        f"{weight_trend}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_body(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    rec = crud.get_latest_body_composition()
    if not rec:
        await update.message.reply_text("还没有身体成分记录，发一张体成分截图给我吧。")
        return
    await update.message.reply_text(_format_body_reply(rec, prev=None), parse_mode="Markdown")


async def cmd_workout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    today = date.today()
    start = today - timedelta(days=6)
    workouts = crud.get_workouts_range(start, today)
    if not workouts:
        await update.message.reply_text("本周还没有训练记录。")
        return
    lines = [f"💪 本周训练（共 {len(workouts)} 次）\n"]
    for w in workouts:
        exercises = json.loads(w.exercises or "[]")
        ex_names = "、".join(e["exercise"] for e in exercises[:3])
        if len(exercises) > 3:
            ex_names += f" 等{len(exercises)}个动作"
        lines.append(f"• {w.date} — {ex_names or w.workout_type}")
    await update.message.reply_text("\n".join(lines))


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await update.message.reply_text("正在生成周报，稍等...")
    report = await _generate_report()
    await update.message.reply_text(report)


# ── Photo handler ──────────────────────────────────────────────────────────────

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    logger.info(f"Chat ID: {update.effective_chat.id}")

    import base64
    photo = update.message.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)
    image_bytes = bytes(await file.download_as_bytearray())
    b64 = base64.b64encode(image_bytes).decode()

    media_group_id = update.message.media_group_id

    if media_group_id:
        # Album: collect all photos then process together
        if media_group_id not in _pending_albums:
            wait_msg = await update.message.reply_text("正在收集图片...")
            _pending_albums[media_group_id] = {
                "images": [b64],
                "update": update,
                "ctx": ctx,
                "wait_msg": wait_msg,
            }
            task = asyncio.create_task(_process_album_delayed(media_group_id))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
        else:
            _pending_albums[media_group_id]["images"].append(b64)
    else:
        wait_msg = await update.message.reply_text("正在分析图片，请稍等...")
        await _process_single_photo(b64, image_bytes, update, ctx, wait_msg)


async def _process_album_delayed(media_group_id: str) -> None:
    await asyncio.sleep(3.0)  # wait for all photos in album to arrive
    entry = _pending_albums.pop(media_group_id, None)
    if not entry:
        return

    images = entry["images"]
    update = entry["update"]
    wait_msg = entry["wait_msg"]
    today_str = str(date.today())

    try:
        await wait_msg.edit_text(f"正在分析 {len(images)} 张图片，请稍等...")

        # Classify by first image
        image_type = await parsers.classify_image(images[0])

        if image_type == "body":
            merged: dict = {}
            for b64 in images:
                data, _ = await parsers.parse_body_composition_image(b64)
                for k, v in data.items():
                    if v is not None and merged.get(k) is None:
                        merged[k] = v
            merged["date"] = today_str
            prev = crud.get_latest_body_composition()
            rec = crud.upsert_body_composition(merged, "album", str(merged))
            reply = _format_body_reply(rec, prev)
        else:
            reply = f"相册目前仅支持身体成分报告（识别为 {image_type}）。"

        await wait_msg.edit_text(reply, parse_mode="Markdown")
    except Exception as e:
        logger.exception("Album processing error")
        await wait_msg.edit_text(f"解析失败：{e}\n\n请重新发图或手动输入数据。")


async def _process_single_photo(b64: str, image_bytes: bytes, update: Update,
                                 ctx: ContextTypes.DEFAULT_TYPE, wait_msg) -> None:
    try:
        image_type = await parsers.classify_image(b64)
        today_str = str(date.today())

        if image_type == "diet":
            filepath, enc = save_and_encode(image_bytes, "diet")
            data, raw = await parsers.parse_diet_image(enc)
            data["date"] = today_str
            rec = crud.upsert_diet_record(data, filepath, raw)
            reply = _format_diet_reply(data, rec)

        elif image_type == "body":
            filepath, enc = save_and_encode(image_bytes, "body")
            data, raw = await parsers.parse_body_composition_image(enc)
            data["date"] = today_str
            prev = crud.get_latest_body_composition()
            rec = crud.upsert_body_composition(data, filepath, raw)
            reply = _format_body_reply(rec, prev)

        elif image_type == "weight_history":
            filepath, enc = save_and_encode(image_bytes, "body")
            records, raw = await parsers.parse_weight_history_image(enc)
            saved = 0
            for r in records:
                if r.get("weight_kg"):
                    crud.quick_weight_entry(_parse_date(r["date"]), r["weight_kg"])
                    saved += 1
            reply = f"✅ 已导入 {saved} 条体重历史记录"

        else:
            reply = "这张图片我识别不出来，请发薄荷饮食截图或体成分报告截图。"

        await wait_msg.edit_text(reply, parse_mode="Markdown")

    except Exception as e:
        logger.exception("Error handling photo")
        await wait_msg.edit_text(f"解析失败：{e}\n\n请重新发图或手动输入数据。")


# ── Text handler ───────────────────────────────────────────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    logger.info(f"Chat ID: {update.effective_chat.id}")

    text = update.message.text.strip()

    # Note detection
    note = await analyst.classify_note(text)
    if note:
        from utils.notes import save_note, CATEGORY_ICONS
        save_note(date.today(), note.get("category", "other"), note.get("content", text))
        label = CATEGORY_ICONS.get(note.get("category", "other"), "📝 其他")
        summary = note.get("summary", "")
        await update.message.reply_text(f"📌 已记录到「{label}」\n{summary}")
        return

    # Diary / mood entry detection
    diary = await analyst.detect_diary(text)
    if diary:
        from db.crud import save_diary
        rec = save_diary(
            entry_date=date.today(),
            content=diary.get("content", text),
            mood=diary.get("mood"),
            mood_score=diary.get("mood_score"),
        )
        mood_str = f"心情：{rec.mood}（{rec.mood_score}/5）" if rec.mood else ""
        from utils.psych_memory import load_psych_memory, save_psych_memory
        memory = load_psych_memory()
        response = await analyst.generate_diary_response(diary.get("content", text), diary.get("mood", ""), memory)
        await update.message.reply_text(f"📔 {rec.date} {mood_str}\n\n{response}")
        _append_history(text, response)
        async def _update_memory():
            new_mem = await analyst.update_psych_memory(memory, diary.get("content", text), diary.get("mood", ""))
            if new_mem:
                save_psych_memory(new_mem)
        task = asyncio.create_task(_update_memory())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return

    # Correction intent: "内脏脂肪应该是13" / "体脂率错了，是29.2"
    correction = await analyst.detect_correction(text)
    if correction:
        from db.crud import apply_correction
        from datetime import date as date_cls
        record_date = date_cls.fromisoformat(correction["date"])
        ok = apply_correction(correction["table"], correction["field"], correction["value"], record_date)
        if ok:
            field_cn = {
                "visceral_fat_level": "内脏脂肪",
                "body_fat_pct": "体脂率",
                "weight_kg": "体重",
                "skeletal_muscle_kg": "骨骼肌量",
                "bmr_kcal": "基础代谢",
                "total_calories": "总热量",
                "protein_g": "蛋白质",
            }.get(correction["field"], correction["field"])
            await update.message.reply_text(
                f"✅ 已修正 {record_date} 的{field_cn}：{correction['value']}"
            )
        else:
            await update.message.reply_text("找不到对应记录，无法修正。")
        return

    # Quick weight entry: "今天体重 91.2" or "体重 91.2"
    weight_match = re.search(r"体重\s*([\d.]+)", text)
    if weight_match:
        weight = float(weight_match.group(1))
        crud.quick_weight_entry(date.today(), weight)
        await update.message.reply_text(f"✅ 体重已记录：{weight} kg（{date.today()}）")
        return

    # Workout detection
    workout_keywords = ["深蹲", "卧推", "硬拉", "引体", "哑铃", "杠铃", "训练", "练了", "组", "rpe", "RPE"]
    if any(kw in text.lower() for kw in workout_keywords):
        wait = await update.message.reply_text("正在解析训练记录...")
        try:
            data, raw = await parsers.parse_workout_text(text)
            rec = crud.save_workout(data)
            exercises = json.loads(rec.exercises or "[]")
            ex_lines = []
            for ex in exercises:
                sets_str = ", ".join(
                    f"{s.get('weight')}kg×{s.get('reps')}" + (f"@RPE{s['rpe']}" if s.get("rpe") else "")
                    for s in ex.get("sets", [])
                )
                ex_lines.append(f"  • {ex['exercise']}：{sets_str}")
            reply = f"✅ {rec.date} 训练已记录\n\n💪 动作：\n" + "\n".join(ex_lines)
            if rec.notes:
                reply += f"\n\n📝 {rec.notes}"
            await wait.edit_text(reply)
        except Exception as e:
            logger.exception("Workout parse error")
            await wait.edit_text(f"解析训练记录失败：{e}")
        return

    # Route to coach or psychologist
    role = await analyst.route_message(text)

    if role == "psychologist":
        wait = await update.message.reply_text("思考中...")
        from utils.psych_memory import load_psych_memory
        memory = load_psych_memory()
        answer = await analyst.answer_as_psychologist(text, memory, history=list(_conversation_history))
        await wait.edit_text(answer)
        _append_history(text, answer)
        return

    # Coach: health/diet/workout queries
    wait = await update.message.reply_text("查询中...")
    ctx_data = _build_context()
    answer = await analyst.answer_question(text, ctx_data, history=list(_conversation_history))
    await wait.edit_text(answer)
    _append_history(text, answer)


# ── Callback query (inline keyboard) ─────────────────────────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "today":
        await query.edit_message_text(_build_today_summary(date.today()), parse_mode="Markdown")
    elif data == "week":
        fake_update = update
        # Reuse cmd_week logic
        today = date.today()
        start = today - timedelta(days=6)
        records = crud.get_daily_summaries_range(start, today)
        if not records:
            await query.edit_message_text("本周还没有数据。")
        else:
            total_deficit = sum(r.calorie_deficit or 0 for r in records)
            avg_deficit = total_deficit / len(records)
            avg_cal = sum(r.total_calories_in or 0 for r in records) / len(records)
            protein_days = sum(1 for r in records if r.protein_achievement_pct and r.protein_achievement_pct >= 90)
            fat_burned = total_deficit / 7700
            text = (
                f"📊 本周汇总（{start} ~ {today}）\n\n"
                f"🔥 平均每日摄入：{avg_cal:.0f} kcal\n"
                f"📉 累计热量缺口：{total_deficit:.0f} kcal（≈ {fat_burned:.2f}kg 脂肪）\n"
                f"📈 日均缺口：{avg_deficit:.0f} kcal\n"
                f"🥩 蛋白质达标天数：{protein_days}/{len(records)} 天"
            )
            await query.edit_message_text(text, parse_mode="Markdown")
    elif data == "body":
        rec = crud.get_latest_body_composition()
        if not rec:
            await query.edit_message_text("还没有身体成分记录。")
        else:
            await query.edit_message_text(_format_body_reply(rec, None), parse_mode="Markdown")
    elif data == "workout":
        today = date.today()
        workouts = crud.get_workouts_range(today - timedelta(days=6), today)
        if not workouts:
            await query.edit_message_text("本周还没有训练记录。")
        else:
            lines = [f"💪 本周训练（{len(workouts)} 次）\n"]
            for w in workouts:
                exercises = json.loads(w.exercises or "[]")
                ex_names = "、".join(e["exercise"] for e in exercises[:3])
                lines.append(f"• {w.date} — {ex_names or w.workout_type}")
            await query.edit_message_text("\n".join(lines))
    elif data == "report":
        await query.edit_message_text("正在生成周报...")
        report = await _generate_report()
        await query.edit_message_text(report)


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _format_diet_reply(data: dict, rec) -> str:
    s = data.get("summary", {})
    total = s.get("total_calories", 0) or 0
    exercise = s.get("exercise_calories", 0) or 0
    budget = s.get("budget_calories", 0) or 0
    over = s.get("over_budget", 0) or 0
    net = total - exercise

    protein = s.get("protein_g", 0) or 0
    protein_goal = s.get("protein_goal_g", 0) or 0
    carbs = s.get("carbs_g", 0) or 0
    carbs_goal = s.get("carbs_goal_g", 0) or 0
    fat = s.get("fat_g", 0) or 0
    fat_goal = s.get("fat_goal_g", 0) or 0

    protein_icon = "✅" if protein >= protein_goal else "⚠️"
    carbs_icon = "✅" if carbs <= carbs_goal else "⚠️"
    fat_icon = "✅" if fat <= fat_goal else "⚠️"

    budget_str = f"超出 {over:.0f}" if over > 0 else f"缺口 {abs(over):.0f}"

    lines = [
        f"✅ {data.get('date', '今日')} 饮食已记录\n",
        f"🔥 总摄入：{total:.0f} kcal（预算 {budget:.0f}，{budget_str}）",
        f"🏃 运动消耗：{exercise:.0f} kcal（净摄入 {net:.0f}）\n",
        f"🥩 蛋白质：{protein:.0f}g / 目标 {protein_goal:.0f}g {protein_icon}",
        f"🍚 碳水：{carbs:.0f}g / 目标 {carbs_goal:.0f}g {carbs_icon}",
        f"🧈 脂肪：{fat:.0f}g / 目标 {fat_goal:.0f}g {fat_icon}\n",
        "📋 今日食物",
    ]

    meals = data.get("meals", [])
    meal_labels = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "加餐"}
    for meal in meals:
        label = meal_labels.get(meal.get("meal_type", ""), meal.get("meal_type", ""))
        cal = meal.get("total_calories", 0)
        foods = meal.get("foods", [])
        food_str = "、".join(f"{f['name']} {f.get('amount', '')}" for f in foods[:4])
        if len(foods) > 4:
            food_str += f" 等{len(foods)}项"
        lines.append(f"{label} {cal:.0f} kcal：{food_str}")

    return "\n".join(lines)


def _format_body_reply(rec, prev) -> str:
    def delta(curr, prev_val, unit="", fmt=".1f"):
        if prev_val is None or curr is None:
            return "—"
        d = curr - prev_val
        sign = "+" if d > 0 else ""
        return f"{sign}{d:{fmt}}{unit}"

    prev_weight = prev.weight_kg if prev and prev.date != rec.date else None
    prev_fat = prev.body_fat_pct if prev and prev.date != rec.date else None
    prev_muscle = prev.muscle_mass_kg if prev and prev.date != rec.date else None

    weight_goal = float(os.getenv("USER_WEIGHT_GOAL", 74.8))
    to_go = (rec.weight_kg or 0) - weight_goal

    lines = [
        "✅ 身体成分已记录\n",
        f"📅 {rec.date}",
        f"⚖️ 体重：{rec.weight_kg} kg（变化：{delta(rec.weight_kg, prev_weight, 'kg')}）",
        f"🫧 体脂率：{rec.body_fat_pct}%（变化：{delta(rec.body_fat_pct, prev_fat, '%')}）",
    ]

    if rec.body_fat_kg:
        lines.append(f"   脂肪量：{rec.body_fat_kg} kg")
    if rec.subcutaneous_fat_pct or rec.subcutaneous_fat_kg:
        sub_str = ""
        if rec.subcutaneous_fat_pct:
            sub_str += f"{rec.subcutaneous_fat_pct}%"
        if rec.subcutaneous_fat_kg:
            sub_str += f" / {rec.subcutaneous_fat_kg}kg"
        lines.append(f"   皮下脂肪：{sub_str.strip()}")

    if rec.muscle_mass_kg or rec.skeletal_muscle_kg:
        lines.append(f"💪 肌肉量：{rec.muscle_mass_kg} kg（变化：{delta(rec.muscle_mass_kg, prev_muscle, 'kg')}）")
        if rec.skeletal_muscle_kg:
            lines.append(f"   骨骼肌量：{rec.skeletal_muscle_kg} kg")

    if rec.visceral_fat_level:
        lines.append(f"🔥 内脏脂肪：{rec.visceral_fat_level}级")

    extra = []
    if rec.bmr_kcal:
        extra.append(f"基础代谢 {rec.bmr_kcal:.0f}kcal")
    if rec.body_age:
        extra.append(f"体年龄 {rec.body_age}岁")
    if rec.health_score:
        extra.append(f"健康评分 {rec.health_score}分")
    if rec.body_type:
        extra.append(f"体型 {rec.body_type}")
    if extra:
        lines.append("📊 " + " | ".join(extra))

    lines += [
        f"\n📈 距离目标",
        f"还需减重：{to_go:.1f} kg → 目标 {weight_goal} kg",
    ]

    if rec.ideal_weight_kg:
        lines.append(f"理想体重：{rec.ideal_weight_kg} kg")
    if rec.fat_to_lose_kg:
        lines.append(f"还需减脂：{rec.fat_to_lose_kg:.1f} kg")

    return "\n".join(lines)


def _build_today_summary(today: date) -> str:
    diet = crud.get_diet_record(today)
    summary = crud.get_daily_summary(today)
    body = crud.get_latest_body_composition()

    if not diet and not summary:
        return f"📅 {today}\n\n今天还没有饮食记录。发薄荷截图给我吧 📸"

    lines = [f"📅 今日汇总（{today}）\n"]

    if diet:
        bmr = crud.get_bmr()
        net = (diet.total_calories or 0) - (diet.exercise_calories or 0)
        deficit = bmr - net
        lines += [
            f"🔥 摄入：{diet.total_calories:.0f} kcal | 运动：{diet.exercise_calories:.0f} kcal",
            f"📉 热量缺口：{deficit:.0f} kcal",
            f"🥩 蛋白质：{diet.protein_g:.0f}g / {diet.protein_goal_g:.0f}g",
            f"🍚 碳水：{diet.carbs_g:.0f}g | 🧈 脂肪：{diet.fat_g:.0f}g",
        ]

    if body:
        lines.append(f"\n⚖️ 最新体重：{body.weight_kg} kg（{body.date}）")

    return "\n".join(lines)


def _build_context() -> dict:
    body = crud.get_latest_body_composition()
    today_diet = crud.get_diet_record(date.today())
    today = date.today()
    summaries = crud.get_daily_summaries_range(today - timedelta(days=6), today)
    avg_deficit = (
        sum(s.calorie_deficit or 0 for s in summaries) / len(summaries)
        if summaries else None
    )
    body_history = crud.get_body_compositions_range(today - timedelta(days=730), today)

    ctx = {}
    if body:
        ctx["latest_body"] = {
            "date": str(body.date),
            "weight_kg": body.weight_kg,
            "body_fat_pct": body.body_fat_pct,
            "muscle_mass_kg": body.muscle_mass_kg,
        }
    if body_history:
        ctx["body_history"] = [
            {
                "date": str(r.date),
                "weight_kg": r.weight_kg,
                "body_fat_pct": r.body_fat_pct,
                "skeletal_muscle_kg": r.skeletal_muscle_kg,
            }
            for r in body_history
        ]
        # Pre-compute weight trend so LLM doesn't do the math
        records_with_weight = [r for r in body_history if r.weight_kg is not None]
        if len(records_with_weight) >= 2:
            first = records_with_weight[0]
            last = records_with_weight[-1]
            days = (last.date - first.date).days
            weight_change = last.weight_kg - first.weight_kg
            weeks = days / 7
            ctx["weight_trend"] = {
                "from_date": str(first.date),
                "to_date": str(last.date),
                "from_weight_kg": first.weight_kg,
                "to_weight_kg": last.weight_kg,
                "total_change_kg": round(weight_change, 2),
                "days": days,
                "weeks": round(weeks, 1),
                "kg_per_week": round(weight_change / weeks, 2) if weeks > 0 else None,
            }
    if today_diet:
        ctx["today_diet"] = {
            "total_calories": today_diet.total_calories,
            "protein_g": today_diet.protein_g,
        }
    if avg_deficit is not None:
        ctx["week_avg_deficit"] = avg_deficit
    return ctx


async def _generate_report() -> str:
    today = date.today()
    start = today - timedelta(days=6)
    diet_records = crud.get_diet_records_range(start, today)
    body_records = crud.get_body_compositions_range(start, today)
    workout_records = crud.get_workouts_range(start, today)

    bmr = crud.get_bmr()

    user_data = {
        "diet_records": [
            {
                "date": str(r.date),
                "total_calories": r.total_calories,
                "protein_g": r.protein_g,
                "protein_goal_g": r.protein_goal_g,
                "calorie_deficit": bmr - (r.total_calories or 0) + (r.exercise_calories or 0),
            }
            for r in diet_records
        ],
        "body_records": [
            {
                "date": str(r.date),
                "weight_kg": r.weight_kg,
                "body_fat_pct": r.body_fat_pct,
                "muscle_mass_kg": r.muscle_mass_kg,
            }
            for r in body_records
        ],
        "workout_records": [{"date": str(r.date), "type": r.workout_type} for r in workout_records],
    }

    return await analyst.generate_weekly_report(user_data)


def _parse_date(d) -> date:
    if isinstance(d, date):
        return d
    if not d or d == "today":
        return date.today()
    return date.fromisoformat(str(d)[:10])
