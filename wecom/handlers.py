import asyncio
import base64
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

from db import crud
from llm import parsers, analyst
from wecom.client import send_text, download_media

logger = logging.getLogger(__name__)

_conversation_history: list[dict] = []
_MAX_HISTORY_TURNS = 8
_chat_mode: str = "auto"

_CONV_LOG = os.path.join(os.path.dirname(__file__), "..", "data", "conversation_log.jsonl")
_DEBUG_IMAGE = os.path.join(os.path.dirname(__file__), "..", "data", "images", "debug_last.jpg")

_MODE_LABELS = {"auto": "🤖 自动", "coach": "🏋️ 教练", "chat": "💬 聊天"}
_WORKOUT_KEYWORDS = [
    "深蹲", "卧推", "硬拉", "引体", "哑铃", "杠铃", "训练", "练了",
    "高位下拉", "划船", "推举", "飞鸟", "弯举", "臂屈伸", "夹胸",
    "腿举", "腿屈伸", "腿弯举", "臀推", "保加利亚", "罗马尼亚",
    "坐姿", "站姿", "器械", "绳索", "史密斯",
    "跑步", "跑步机", "椭圆机", "跳绳",
    "rpe", "RPE", "rm", "RM",
    "kg*", "kg×", "*8", "*10", "*12", "*6", "*5", "*4", "*3",
]


def _append_history(user_text: str, assistant_text: str) -> None:
    _conversation_history.append({"role": "user", "content": user_text})
    _conversation_history.append({"role": "assistant", "content": assistant_text})
    if len(_conversation_history) > _MAX_HISTORY_TURNS * 2:
        del _conversation_history[:-(_MAX_HISTORY_TURNS * 2)]


def _log(event: dict) -> None:
    event["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with open(_CONV_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


async def handle_text(user_id: str, text: str) -> None:
    global _chat_mode
    text = text.strip()
    logger.info("[MSG] mode=%s text=%s", _chat_mode, text)

    # /mode 切换
    if text.lower().startswith("/mode"):
        arg = text[5:].strip()
        mapping = {"教练": "coach", "coach": "coach", "聊天": "chat", "chat": "chat", "自动": "auto", "auto": "auto"}
        if arg in mapping:
            _chat_mode = mapping[arg]
            send_text(user_id, f"已切换到 {_MODE_LABELS[_chat_mode]} 模式\n\n/mode 教练 | /mode 聊天 | /mode 自动")
        else:
            send_text(user_id, f"当前：{_MODE_LABELS[_chat_mode]}\n\n/mode 教练 | /mode 聊天 | /mode 自动")
        return

    # 其他指令
    if text.startswith("/"):
        await _handle_command(user_id, text)
        return

    # ── 手动模式：直接跳过分类 ─────────────────────────────────────────────
    if _chat_mode == "coach":
        send_text(user_id, "🏋️ 查询中...")
        from bot.handlers import _build_context
        answer = await analyst.answer_question(text, _build_context(), history=list(_conversation_history))
        send_text(user_id, answer)
        _append_history(text, answer)
        _log({"type": "coach", "mode": "manual", "text": text, "response": answer})
        return

    if _chat_mode == "chat":
        send_text(user_id, "💬 思考中...")
        from utils.psych_memory import load_psych_memory
        answer = await analyst.answer_as_psychologist(text, load_psych_memory(), history=list(_conversation_history))
        send_text(user_id, answer)
        _append_history(text, answer)
        _log({"type": "psychologist", "mode": "manual", "text": text, "response": answer})
        return

    # ── 自动模式 ──────────────────────────────────────────────────────────

    # 体重快录
    weight_match = re.search(r"体重\s*([\d.]+)", text)
    if weight_match:
        weight = float(weight_match.group(1))
        crud.quick_weight_entry(date.today(), weight)
        send_text(user_id, f"✅ 体重已记录：{weight} kg（{date.today()}）")
        return

    # 训练关键词（先于LLM分类）
    if any(kw in text for kw in _WORKOUT_KEYWORDS):
        send_text(user_id, "正在解析训练记录...")
        try:
            data, _ = await parsers.parse_workout_text(text)
            rec = crud.save_workout(data)
            exercises = json.loads(rec.exercises or "[]")
            lines = [f"✅ {rec.date} 训练已记录\n\n💪 动作："]
            for ex in exercises:
                sets_str = ", ".join(
                    f"{s.get('weight')}kg×{s.get('reps')}" + (f"@RPE{s['rpe']}" if s.get("rpe") else "")
                    for s in ex.get("sets", [])
                )
                lines.append(f"  • {ex['exercise']}：{sets_str}")
            send_text(user_id, "\n".join(lines))
        except Exception as e:
            send_text(user_id, f"解析训练记录失败：{e}")
        return

    # 纠错
    correction = await analyst.detect_correction(text)
    if correction:
        from db.crud import apply_correction
        from datetime import date as date_cls
        record_date = date_cls.fromisoformat(correction["date"])
        ok = apply_correction(correction["table"], correction["field"], correction["value"], record_date)
        field_cn = {"visceral_fat_level": "内脏脂肪", "body_fat_pct": "体脂率", "weight_kg": "体重"}.get(correction["field"], correction["field"])
        send_text(user_id, f"✅ 已修正 {record_date} 的{field_cn}：{correction['value']}" if ok else "找不到记录，无法修正。")
        return

    # 笔记
    note = await analyst.classify_note(text)
    if note:
        from utils.notes import save_note
        save_note(date.today(), note.get("category", "other"), text)
        summary = note.get("summary", "")
        send_text(user_id, f"📌 已记录{('：' + summary) if summary else ''}")
        _log({"type": "note", "text": text})
        return

    # 日记
    diary = await analyst.detect_diary(text)
    if diary:
        from db.crud import save_diary
        from utils.psych_memory import load_psych_memory, save_psych_memory
        rec = save_diary(entry_date=date.today(), content=diary.get("content", text),
                         mood=diary.get("mood"), mood_score=diary.get("mood_score"))
        mood_str = f"心情：{rec.mood}（{rec.mood_score}/5）" if rec.mood else ""
        memory = load_psych_memory()
        response = await analyst.generate_diary_response(diary.get("content", text), diary.get("mood", ""), memory)
        send_text(user_id, f"📔 {rec.date} {mood_str}\n\n{response}")
        _append_history(text, response)
        _log({"type": "diary_reply", "text": text, "response": response})
        async def _upd():
            new_mem = await analyst.update_psych_memory(memory, diary.get("content", text), diary.get("mood", ""))
            if new_mem:
                save_psych_memory(new_mem)
        asyncio.create_task(_upd())
        return

    # 路由
    role = await analyst.route_message(text)
    if role == "psychologist":
        send_text(user_id, "思考中...")
        from utils.psych_memory import load_psych_memory
        answer = await analyst.answer_as_psychologist(text, load_psych_memory(), history=list(_conversation_history))
        send_text(user_id, answer)
        _append_history(text, answer)
        _log({"type": "psychologist", "text": text, "response": answer})
        return

    send_text(user_id, "查询中...")
    from bot.handlers import _build_context
    answer = await analyst.answer_question(text, _build_context(), history=list(_conversation_history))
    send_text(user_id, answer)
    _append_history(text, answer)
    _log({"type": "coach", "text": text, "response": answer})


async def handle_image(user_id: str, media_id: str) -> None:
    send_text(user_id, "正在分析图片，请稍等...")
    try:
        image_bytes = download_media(media_id)
        try:
            with open(_DEBUG_IMAGE, "wb") as f:
                f.write(image_bytes)
        except Exception:
            pass

        b64 = base64.b64encode(image_bytes).decode()
        today_str = str(date.today())
        image_type = await parsers.classify_image(b64)

        if image_type == "diet":
            from utils.image import save_and_encode
            filepath, enc = save_and_encode(image_bytes, "diet")
            data, raw = await parsers.parse_diet_image(enc)
            if not data.get("date"):
                data["date"] = today_str
            rec = crud.upsert_diet_record(data, filepath, raw)
            from bot.handlers import _format_diet_reply
            reply = _format_diet_reply(data, rec)

        elif image_type == "body":
            from utils.image import save_and_encode
            filepath, enc = save_and_encode(image_bytes, "body")
            data, raw = await parsers.parse_body_composition_image(enc)
            if not data.get("date"):
                data["date"] = today_str
            prev = crud.get_latest_body_composition()
            rec = crud.upsert_body_composition(data, filepath, raw)
            from bot.handlers import _format_body_reply
            reply = _format_body_reply(rec, prev)

        else:
            reply = "这张图片我识别不出来，请发薄荷饮食截图或体成分报告截图。"

        send_text(user_id, reply)
        _log({"type": f"photo_{image_type}", "response": reply[:200]})

    except Exception as e:
        logger.exception("Image handling error")
        send_text(user_id, f"解析失败：{e}")


async def _handle_command(user_id: str, text: str) -> None:
    cmd = text.split()[0].lower()
    if cmd == "/today":
        from bot.handlers import _build_today_summary
        send_text(user_id, _build_today_summary(date.today()))
    elif cmd == "/week":
        today = date.today()
        records = crud.get_daily_summaries_range(today - timedelta(days=6), today)
        if not records:
            send_text(user_id, "本周还没有数据。")
        else:
            total = sum(r.calorie_deficit or 0 for r in records)
            avg_cal = sum(r.total_calories_in or 0 for r in records) / len(records)
            send_text(user_id, f"📊 本周\n🔥 均摄入：{avg_cal:.0f}kcal\n📉 累计缺口：{total:.0f}kcal ≈ {total/7700:.2f}kg脂肪")
    elif cmd == "/body":
        rec = crud.get_latest_body_composition()
        if rec:
            from bot.handlers import _format_body_reply
            send_text(user_id, _format_body_reply(rec, None))
        else:
            send_text(user_id, "还没有身体成分记录。")
    elif cmd == "/report":
        send_text(user_id, "正在生成周报...")
        from bot.handlers import _generate_report
        send_text(user_id, await _generate_report())
    elif cmd == "/stats":
        from bot.handlers import cmd_stats
        send_text(user_id, "请用 /mode 教练 后直接问体重变化。")
    else:
        send_text(user_id, f"可用指令：/today /week /body /report /mode 教练|聊天|自动")
