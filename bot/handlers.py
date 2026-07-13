import asyncio
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

from telegram import Update
from telegram.ext import ContextTypes

from db import crud
from llm import parsers, analyst
from utils.media_store import save_document as _media_save_doc
from .keyboards import main_menu, mode_menu, MODE_LABELS

logger = logging.getLogger(__name__)

_chat_mode: str = "auto"  # "auto" | "coach" | "psychologist"

_CONV_LOG = os.path.join(os.path.dirname(__file__), "..", "data", "conversation_log.jsonl")

# When True, the next photo is parsed as an English nutrition label (one-shot).
_nutrition_mode: bool = False

# After a label is parsed, holds its per-100g/per-pack data awaiting a gram amount.
_pending_nutrition: dict = {}


def _log_event(event: dict) -> None:
    event["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with open(_CONV_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass

_background_tasks: set = set()  # keep task references to prevent GC
_conversation_history: list[dict] = []  # last N turns for multi-turn context
_MAX_HISTORY_TURNS = 8  # keep 8 exchanges (16 messages)

_WORKOUT_KEYWORDS = [
    "深蹲", "卧推", "硬拉", "引体", "哑铃", "杠铃", "训练", "练了",
    "高位下拉", "划船", "推举", "飞鸟", "弯举", "臂屈伸", "夹胸",
    "腿举", "腿屈伸", "腿弯举", "臀推", "保加利亚", "罗马尼亚",
    "坐姿", "站姿", "器械", "绳索", "史密斯",
    "跑步", "跑步机", "椭圆机", "跳绳", "踏步",
    "rpe", "RPE", "rm", "RM",
    "kg*", "kg×", "*8", "*10", "*12", "*6", "*5", "*4", "*3",
]

_CLOSING_SIGNALS = frozenset([
    "好了", "好的谢谢", "谢谢", "感谢", "再见", "拜拜", "明白了",
    "没事了", "就这样", "不说了", "先这样", "先聊到这",
])

_psych_session: dict = {
    "active": False,
    "turns": [],
    "bot": None,
    "chat_id": None,
    "_timer": None,
}


def _cancel_psych_timer() -> None:
    t = _psych_session.get("_timer")
    if t and not t.done():
        t.cancel()
    _psych_session["_timer"] = None


def _schedule_psych_save(bot, chat_id: str, delay: int = 600) -> None:
    _cancel_psych_timer()

    async def _timeout():
        await asyncio.sleep(delay)
        await _close_psych_session(notify=True)

    task = asyncio.create_task(_timeout())
    _psych_session["_timer"] = task
    _psych_session["bot"] = bot
    _psych_session["chat_id"] = chat_id


async def _close_psych_session(notify: bool = False) -> None:
    _cancel_psych_timer()
    turns = list(_psych_session["turns"])
    bot = _psych_session["bot"]
    chat_id = _psych_session["chat_id"]
    _psych_session.update({"active": False, "turns": [], "bot": None, "chat_id": None, "_timer": None})

    if not turns:
        return

    try:
        diary_data = await analyst.generate_diary_from_conversation(turns)
        if diary_data and diary_data.get("content"):
            from db.crud import save_diary
            from utils.psych_memory import load_psych_memory, save_psych_memory
            rec = save_diary(
                entry_date=date.today(),
                content=diary_data["content"],
                mood=diary_data.get("mood"),
                mood_score=diary_data.get("mood_score"),
            )
            memory = load_psych_memory()

            async def _upd():
                new_mem = await analyst.update_psych_memory(memory, diary_data["content"], diary_data.get("mood", ""))
                if new_mem:
                    save_psych_memory(new_mem)

            t = asyncio.create_task(_upd())
            _background_tasks.add(t)
            t.add_done_callback(_background_tasks.discard)

            if notify and bot and chat_id:
                mood_str = f"（心情：{rec.mood}）" if rec.mood else ""
                await bot.send_message(chat_id=chat_id, text=f"📔 已记录今天的对话{mood_str}")
            _log_event({"type": "diary_from_convo", "turns": len(turns), "mood": diary_data.get("mood")})
    except Exception:
        logger.exception("Error saving psych session")


def _append_history(user_text: str, assistant_text: str) -> None:
    _conversation_history.append({"role": "user", "content": user_text})
    _conversation_history.append({"role": "assistant", "content": assistant_text})
    # Trim to last N turns
    max_msgs = _MAX_HISTORY_TURNS * 2
    if len(_conversation_history) > max_msgs:
        del _conversation_history[:-max_msgs]


async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    global _chat_mode
    if not _allowed(update):
        return
    arg = (ctx.args[0] if ctx.args else "").strip()
    mapping = {"教练": "coach", "coach": "coach", "聊天": "chat", "chat": "chat", "自动": "auto", "auto": "auto"}
    if arg in mapping:
        _chat_mode = mapping[arg]
        label = MODE_LABELS[_chat_mode]
        await update.message.reply_text(f"已切换到 {label} 模式", reply_markup=mode_menu(_chat_mode))
    else:
        label = MODE_LABELS[_chat_mode]
        await update.message.reply_text(
            f"当前模式：{label}\n\n用法：/mode 教练 | /mode 聊天 | /mode 自动",
            reply_markup=mode_menu(_chat_mode),
        )


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
        "🥗 记营养表：点下面的「记营养表」按钮，再发英文营养标签照片\n\n"
        "💬 发文字给我：\n"
        "  • 训练记录（如 深蹲80kg 5组5次）\n"
        "  • 任何关于你健康数据的问题\n\n"
        "📊 每天数据（吃/练/体重/体脂）由 HealthKit 自动同步\n\n"
        "📋 指令：/today /week /body /workout /report /profile /update\n\n"
        "💡 /profile 查看个人资料和当前 BMR\n"
        "/update age 27 · /update height 172 · /update gender male\n"
        "/update goal 75.0 · /update protein 1.8",
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


async def cmd_nutrition(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Arm nutrition-label mode from the / menu, then wait for a photo."""
    if not _allowed(update):
        return
    global _nutrition_mode
    _nutrition_mode = True
    await update.message.reply_text(
        "🥗 记营养表已就绪。\n拍一张英文营养成分表照片发给我，我解析成营养数据（每份 per pack）。"
    )


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

    # Nutrition-label mode (one-shot): parse English label via qwen3.7-plus + Python validation.
    global _nutrition_mode
    if _nutrition_mode:
        _nutrition_mode = False  # one-shot
        wait_msg = await update.message.reply_text("🥗 正在解析营养表...")
        try:
            from llm.nutrition import parse_nutrition_label, format_reply
            result = await parse_nutrition_label(b64, column="pack")
            await wait_msg.edit_text(format_reply(result))
            # remember it so the next text (a gram amount) can be scaled
            _pending_nutrition.clear()
            _pending_nutrition.update({
                "canon": result.get("table", {}),
                "perpack": result.get("healthkit", {}),
            })
            _log_event({"type": "nutrition_label", "healthkit": result.get("healthkit"),
                        "warnings": result.get("warnings")})
        except Exception as e:
            logger.exception("nutrition parse failed")
            await wait_msg.edit_text(f"解析失败：{e}")
        return

    # Photos are only used for English nutrition labels now — guide to the button.
    await update.message.reply_text(
        "要记营养标签，先点下面的 🥗 记营养表 按钮，再发图片。",
        reply_markup=main_menu(),
    )


# ── Text handler ───────────────────────────────────────────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    logger.info(f"Chat ID: {update.effective_chat.id}")

    text = update.message.text.strip()
    logger.info("[MSG] mode=%s text=%s", _chat_mode, text)

    # ── 营养表：解析后等待用户回复克数 ──────────────────────────────────────
    if _pending_nutrition.get("canon"):
        from llm.nutrition import scale_to_grams, format_scaled, format_scaled_pack
        if text in ("整份", "整包", "一份", "全部", "pack", "whole"):
            perpack = _pending_nutrition.get("perpack", {})
            _pending_nutrition.clear()
            await update.message.reply_text(format_scaled_pack(perpack))
            return
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(?:g|克|G|克重)?\s*$", text)
        if m:
            grams = float(m.group(1))
            canon = _pending_nutrition["canon"]
            _pending_nutrition.clear()
            scaled = scale_to_grams(canon, grams)
            await update.message.reply_text(format_scaled(scaled))
            _log_event({"type": "nutrition_scaled", "grams": grams, "healthkit": scaled})
            return
        # anything else cancels the pending flow and falls through to normal handling
        _pending_nutrition.clear()

    # ── 固定路由：教练/聊天模式直接跳过所有分类 API ──────────────────────────
    if _chat_mode == "coach":
        wait = await update.message.reply_text("🏋️ 查询中...")
        ctx_data = _build_context()
        answer = await analyst.answer_question(text, ctx_data, history=list(_conversation_history))
        await wait.edit_text(answer)
        _append_history(text, answer)
        _log_event({"type": "coach", "mode": "manual", "text": text, "response": answer})
        return

    if _chat_mode == "chat":
        wait = await update.message.reply_text("💬 思考中...")
        from utils.psych_memory import load_psych_memory
        memory = load_psych_memory()
        answer = await analyst.answer_as_psychologist(text, memory, history=list(_conversation_history))
        await wait.edit_text(answer)
        _append_history(text, answer)
        _log_event({"type": "psychologist", "mode": "manual", "text": text, "response": answer})
        return

    # ── 自动模式：保留原有分类逻辑 ────────────────────────────────────────────

    # Continue an active psychologist session
    if _psych_session["active"]:
        _cancel_psych_timer()
        is_closing = any(sig in text for sig in _CLOSING_SIGNALS)
        from utils.psych_memory import load_psych_memory
        memory = load_psych_memory()
        answer = await analyst.answer_as_psychologist(text, memory, history=list(_conversation_history))
        await update.message.reply_text(answer)
        _psych_session["turns"].append({"user": text, "bot": answer})
        _append_history(text, answer)
        _log_event({"type": "psychologist_session", "text": text, "response": answer})
        if is_closing:
            await _close_psych_session(notify=False)
        else:
            _schedule_psych_save(ctx.bot, update.effective_chat.id)
        return

    # Quick weight entry: "今天体重 91.2" or "体重 91.2"
    weight_match = re.search(r"体重\s*([\d.]+)", text)
    if weight_match:
        weight = float(weight_match.group(1))
        crud.quick_weight_entry(date.today(), weight)
        await update.message.reply_text(f"✅ 体重已记录：{weight} kg（{date.today()}）")
        return

    # Workout detection — before LLM calls so keywords always win
    if any(kw in text for kw in _WORKOUT_KEYWORDS):
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

    # Diary / mood entry — checked BEFORE notes so emotional content starts a session
    diary = await analyst.detect_diary(text)
    if diary:
        logger.info("[ROUTE] diary → starting psych session, mood=%s", diary.get("mood"))
        _psych_session["active"] = True
        _psych_session["turns"] = []
        from utils.psych_memory import load_psych_memory
        memory = load_psych_memory()
        answer = await analyst.answer_as_psychologist(text, memory, history=[])
        await update.message.reply_text(answer)
        _psych_session["turns"].append({"user": text, "bot": answer})
        _append_history(text, answer)
        _log_event({"type": "psychologist_session_start", "trigger": "diary", "text": text})
        _schedule_psych_save(ctx.bot, update.effective_chat.id)
        return

    # Note detection
    note = await analyst.classify_note(text)
    if note:
        logger.info("[ROUTE] note → category=%s", note.get("category"))
        _log_event({"type": "note", "text": text, "category": note.get("category"), "summary": note.get("summary")})
        from utils.notes import save_note
        save_note(date.today(), note.get("category", "other"), text)
        summary = note.get("summary", "")
        await update.message.reply_text(f"📌 已记录{('：' + summary) if summary else ''}")
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

    # Auto-route to coach or psychologist
    role = await analyst.route_message(text)
    logger.info("[ROUTE] → %s | text=%.80s", role, text)

    if role == "psychologist":
        _psych_session["active"] = True
        _psych_session["turns"] = []
        from utils.psych_memory import load_psych_memory
        memory = load_psych_memory()
        answer = await analyst.answer_as_psychologist(text, memory, history=list(_conversation_history))
        await update.message.reply_text(answer)
        _psych_session["turns"].append({"user": text, "bot": answer})
        _append_history(text, answer)
        _log_event({"type": "psychologist_session_start", "trigger": "route", "text": text})
        _schedule_psych_save(ctx.bot, update.effective_chat.id)
        return

    # Coach: health/diet/workout queries
    wait = await update.message.reply_text("查询中...")
    ctx_data = _build_context()
    answer = await analyst.answer_question(text, ctx_data, history=list(_conversation_history))
    await wait.edit_text(answer)
    _append_history(text, answer)
    _log_event({"type": "coach", "text": text, "response": answer})


# ── Document handler ──────────────────────────────────────────────────────────

_SUPPORTED_DOC_EXTS = {".md", ".txt", ".docx"}

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    doc = update.message.document
    filename = doc.file_name or "document"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in _SUPPORTED_DOC_EXTS:
        await update.message.reply_text(
            f"暂不支持 {ext or '未知'} 格式，支持：.md / .txt / .docx"
        )
        return

    wait = await update.message.reply_text("📄 正在读取文档...")
    try:
        file = await ctx.bot.get_file(doc.file_id)
        file_bytes = bytes(await file.download_as_bytearray())

        # Save to media store (Hermes will read from here)
        saved_path = _media_save_doc(file_bytes, filename)

        # Extract text for preview and logging
        if ext in (".md", ".txt"):
            text_content = file_bytes.decode("utf-8", errors="replace")
        else:  # .docx
            import docx as _docx
            import io as _io
            doc_obj = _docx.Document(_io.BytesIO(file_bytes))
            text_content = "\n".join(p.text for p in doc_obj.paragraphs if p.text.strip())

        preview = text_content[:300]
        _log_event({
            "type": "document_received",
            "filename": filename,
            "saved_path": saved_path,
            "size_bytes": len(file_bytes),
            "preview": text_content[:200],
        })

        await wait.edit_text(
            f"📄 已保存「{filename}」（{len(file_bytes)//1024 or 1} KB）\n"
            f"Hermes 将在下次周期分析时读取此文档。\n\n"
            f"内容预览：\n{preview}{'…' if len(text_content) > 300 else ''}"
        )

    except Exception as e:
        logger.exception("Document handling error")
        await wait.edit_text(f"读取文档失败：{e}")


# ── Callback query (inline keyboard) ─────────────────────────────────────────

async def _menu_edit(query, text, parse_mode=None) -> None:
    """Refresh the menu bubble in place: edit the same message and re-attach the
    menu so tapping today/week/… repeatedly updates one bubble instead of piling
    up new messages. Swallows Telegram's 'message is not modified' (same content)."""
    from telegram.error import BadRequest
    try:
        await query.edit_message_text(text, parse_mode=parse_mode, reply_markup=main_menu())
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    global _nutrition_mode
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "nutrition_on":
        _nutrition_mode = True
        await query.edit_message_text(
            "🥗 记营养表已就绪。\n发一张英文营养成分表照片给我，我解析成营养数据（每份 per pack）。"
        )
        return

    if data.startswith("set_mode:"):
        global _chat_mode
        _chat_mode = data.split(":")[1]
        label = MODE_LABELS[_chat_mode]
        await query.edit_message_text(f"已切换到 {label} 模式", reply_markup=mode_menu(_chat_mode))
        return

    if data == "today":
        await _menu_edit(query, _build_today_summary(date.today()), parse_mode="Markdown")
    elif data == "week":
        today = date.today()
        start = today - timedelta(days=6)
        records = crud.get_daily_summaries_range(start, today)
        if not records:
            await _menu_edit(query, "本周还没有数据。")
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
            await _menu_edit(query, text, parse_mode="Markdown")
    elif data == "body":
        rec = crud.get_latest_body_composition()
        if not rec:
            await _menu_edit(query, "还没有身体成分记录。")
        else:
            await _menu_edit(query, _format_body_reply(rec, None), parse_mode="Markdown")
    elif data == "workout":
        today = date.today()
        workouts = crud.get_workouts_range(today - timedelta(days=6), today)
        if not workouts:
            await _menu_edit(query, "本周还没有训练记录。")
        else:
            lines = [f"💪 本周训练（{len(workouts)} 次）\n"]
            for w in workouts:
                exercises = json.loads(w.exercises or "[]")
                ex_names = "、".join(e["exercise"] for e in exercises[:3])
                lines.append(f"• {w.date} — {ex_names or w.workout_type}")
            await _menu_edit(query, "\n".join(lines))
    elif data == "report":
        await query.edit_message_text("正在生成周报...")
        report = await _generate_report()
        await _menu_edit(query, report)


# ── Formatting helpers ─────────────────────────────────────────────────────────

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

    lines = [f"📅 今日汇总（{today}）\n"]

    if diet:
        summ = crud.get_daily_summary(today)
        bmr = summ.bmr if summ and summ.bmr else crud.get_bmr()
        net = (diet.total_calories or 0) - (diet.exercise_calories or 0)
        deficit = summ.calorie_deficit if summ and summ.calorie_deficit is not None else bmr - net
        # protein goal lives on DailySummary; HK-written diet records have none.
        protein_goal_g = (summ.protein_goal_g if summ and summ.protein_goal_g
                          else (diet.protein_goal_g or 0))
        lines += [
            f"🔥 摄入：{(diet.total_calories or 0):.0f} kcal | 运动：{(diet.exercise_calories or 0):.0f} kcal",
            f"📉 热量缺口：{deficit:.0f} kcal",
            f"🥩 蛋白质：{(diet.protein_g or 0):.0f}g / {protein_goal_g:.0f}g",
            f"🍚 碳水：{(diet.carbs_g or 0):.0f}g | 🧈 脂肪：{(diet.fat_g or 0):.0f}g",
        ]
    else:
        lines.append(
            "今天的数据还没同步。\n"
            "每天 23:50 自动从 HealthKit 同步；想现在看，手动跑一次「同步健康」快捷指令。"
        )

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

    diet_record_count = sum(1 for s in summaries if (s.total_calories_in or 0) > 0)

    ctx = {}
    if body:
        ctx["latest_body"] = {
            "date": str(body.date),
            "weight_kg": body.weight_kg,
            "body_fat_pct": body.body_fat_pct,
            "skeletal_muscle_kg": body.skeletal_muscle_kg,
            "fat_free_mass_kg": body.fat_free_mass_kg,
        }
    if body_history:
        ctx["body_history"] = [
            {
                "date": str(r.date),
                "weight_kg": r.weight_kg,
                "body_fat_pct": r.body_fat_pct,
                "skeletal_muscle_kg": r.skeletal_muscle_kg,
                "fat_free_mass_kg": r.fat_free_mass_kg,
            }
            for r in body_history
        ]
    if today_diet:
        ctx["today_diet"] = {
            "total_calories": today_diet.total_calories,
            "protein_g": today_diet.protein_g,
        }
    if avg_deficit is not None:
        ctx["week_avg_deficit"] = avg_deficit
        ctx["diet_record_count"] = diet_record_count
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


# --- /server : ESBMC-Inv cluster load (added for ops monitoring) ------------
import subprocess as _subprocess

_ESBMC_SERVERS = [
    ("London (dev+LLM)", "8.211.242.246"),
    ("node C (baseline 900s)", "8.208.52.173"),
    ("node A (zero-reg)", "8.208.113.132"),
]
_ESBMC_PEM = "/root/.ssh/pair.pem"


def _probe_esbmc_server(host: str) -> str:
    cmd = [
        "ssh", "-i", _ESBMC_PEM, "-o", "ConnectTimeout=8",
        "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes", f"root@{host}",
        "cut -d' ' -f1-3 /proc/loadavg; "
        "pgrep -xc esbmc 2>/dev/null || echo 0; "
        "pgrep -fc 'run_esbmc_inv_batch|run_baseline_900' 2>/dev/null || echo 0; "
        "free -m | awk '/Mem:/{print $7}'",
    ]
    try:
        r = _subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except Exception as e:
        return "  🔴 OFF (关机/不可达)"
    if r.returncode != 0:
        return "  🔴 OFF (已关机省钱)"
    p = (r.stdout.strip() + "\n\n\n\n").split("\n")
    load, esbmc_n, batch_n, freem = p[0], p[1], p[2], p[3]
    try:
        load1 = float(load.split()[0])
    except Exception:
        load1 = 0.0
    busy = load1 > 0.5 or esbmc_n not in ("0", "")
    tag = "🟢 BUSY" if busy else "💤 IDLE — 可关机省钱"
    return (f"  load: {load}  | esbmc: {esbmc_n}  batch: {batch_n}\n"
            f"  free: {freem}MB  {tag}")


async def cmd_server(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await update.message.reply_text("🔍 查询 ESBMC-Inv 集群负载...")
    lines = []
    for name, host in _ESBMC_SERVERS:
        out = await asyncio.to_thread(_probe_esbmc_server, host)
        lines.append(f"*{name}*  `{host}`\n{out}")
    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


# --- periodic idle watch: alert once per idle transition --------------------
import os as _os

_idle_alerted: dict = {}  # host -> True once we've alerted for this idle spell


def _server_status(host: str):
    """Return (busy: bool|None, text). None = unreachable (do not alert)."""
    cmd = [
        "ssh", "-i", _ESBMC_PEM, "-o", "ConnectTimeout=8",
        "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes", f"root@{host}",
        "cut -d' ' -f1-3 /proc/loadavg; "
        "pgrep -xc esbmc 2>/dev/null || echo 0; "
        "pgrep -fc 'run_esbmc_inv_batch|run_baseline_900' 2>/dev/null || echo 0",
    ]
    try:
        r = _subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except Exception:
        return (None, "unreachable")
    if r.returncode != 0:
        return (None, "unreachable")
    p = (r.stdout.strip() + "\n\n\n").split("\n")
    load, esbmc_n, batch_n = p[0], p[1], p[2]
    try:
        load1 = float(load.split()[0])
    except Exception:
        load1 = 0.0
    busy = load1 > 0.5 or esbmc_n not in ("0", "")
    return (busy, f"load {load} | esbmc {esbmc_n} batch {batch_n}")


async def _server_watch(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat = _os.getenv("ALLOWED_CHAT_ID", "")
    if not chat:
        return
    for name, host in _ESBMC_SERVERS:
        busy, text = await asyncio.to_thread(_server_status, host)
        if busy is None:
            continue
        if not busy:
            if not _idle_alerted.get(host):
                _idle_alerted[host] = True
                try:
                    await ctx.bot.send_message(
                        chat_id=int(chat),
                        text=(f"💤 *{name}* `{host}` 空闲了（没在跑任务）。\n"
                              f"{text}\n可以关机省钱。"),
                        parse_mode="Markdown")
                except Exception:
                    pass
        else:
            _idle_alerted[host] = False
