"""WeCom message handling.

Mirrors the Telegram flow in `bot.handlers`: a barcode photo goes to Open Food
Facts and a text description goes to Qwen, both ending in a HealthKit link. The
screenshot-parsing path this module used to carry is gone, along with `llm.parsers`.

State is keyed by WeCom user id. The database is not yet, so only one person can
safely use this.
"""
import asyncio
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

from db import crud
from llm import analyst
from wecom.client import send_text, download_media

logger = logging.getLogger(__name__)

_MAX_HISTORY_TURNS = 8
_CONV_LOG = os.path.join(os.path.dirname(__file__), "..", "data", "conversation_log.jsonl")
_MODE_LABELS = {"auto": "🤖 自动", "coach": "🏋️ 教练", "chat": "💬 聊天"}
_WHOLE_PACK = ("整份", "整包", "一份", "全部", "pack", "whole")

_SETUP_HELP = ("👋 先告诉我三件事，才能算你的基础代谢：\n\n"
               "发「/setup 身高 年龄 性别」，例如：\n"
               "　/setup 165 28 女\n\n"
               "想顺便定个目标，末尾再加每月想减几公斤：\n"
               "　/setup 165 28 女 1\n\n"
               "（不设目标的话按每月 1kg 算。没有运动手表的话，"
               "缺口只能从吃里省，定太快会被安全下限挡住）")

_DAYS_BACK = {"今天": 0, "昨天": 1, "前天": 2, "大前天": 3}

_state: dict[str, dict] = {}


def _s(user_id: str) -> dict:
    """Per-user state. Module globals here would have let one person's mode and
    conversation history show up in another's replies."""
    return _state.setdefault(user_id, {
        "mode": "auto",
        "history": [],
        "food": {"armed": False, "canon": None, "name": None,
                 "serving_g": None, "item_id": None},
    })


def _food_reset(st: dict) -> None:
    st["food"] = {"armed": False, "canon": None, "name": None,
                  "serving_g": None, "item_id": None}


def _append_history(st: dict, user_text: str, assistant_text: str) -> None:
    st["history"] += [{"role": "user", "content": user_text},
                      {"role": "assistant", "content": assistant_text}]
    if len(st["history"]) > _MAX_HISTORY_TURNS * 2:
        del st["history"][:-(_MAX_HISTORY_TURNS * 2)]


def _log(event: dict) -> None:
    event["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with open(_CONV_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _needs_setup() -> bool:
    """Without age and height `get_bmr` falls back to the `.env` figure, which
    belongs to the primary user and would be wrong for anyone else."""
    p = crud.get_user_profile()
    return not (p and p.age and p.height_cm)


async def handle_text(user_id: str, text: str) -> None:
    st = _s(user_id)
    text = text.strip()
    logger.info("[MSG] from=%s mode=%s text=%s", user_id, st["mode"], text)

    if _needs_setup() and not text.lower().startswith("/setup"):
        send_text(user_id, _SETUP_HELP)
        return

    if text.lower().startswith("/mode"):
        arg = text[5:].strip()
        mapping = {"教练": "coach", "coach": "coach", "聊天": "chat",
                   "chat": "chat", "自动": "auto", "auto": "auto"}
        if arg in mapping:
            st["mode"] = mapping[arg]
        send_text(user_id, f"当前：{_MODE_LABELS[st['mode']]}\n\n/mode 教练 | /mode 聊天 | /mode 自动")
        return

    if text.startswith("/"):
        await _handle_command(user_id, st, text)
        return

    if await _handle_food_text(user_id, st, text):
        return

    if st["mode"] == "coach":
        await _coach(user_id, st, text, "manual")
        return
    if st["mode"] == "chat":
        await _psychologist(user_id, st, text, "manual")
        return

    weight_match = re.search(r"体重\s*([\d.]+)", text)
    if weight_match:
        weight = float(weight_match.group(1))
        when = _weight_date(text)
        crud.quick_weight_entry(when, weight)
        send_text(user_id, f"✅ 体重已记录：{weight} kg（{when}）")
        return

    correction = await analyst.detect_correction(text)
    if correction:
        record_date = date.fromisoformat(correction["date"])
        ok = crud.apply_correction(correction["table"], correction["field"],
                                   correction["value"], record_date)
        field_cn = {"visceral_fat_level": "内脏脂肪", "body_fat_pct": "体脂率",
                    "weight_kg": "体重", "total_calories": "总热量"}.get(
                        correction["field"], correction["field"])
        send_text(user_id, f"✅ 已修正 {record_date} 的{field_cn}：{correction['value']}"
                  if ok else "找不到记录，无法修正。")
        return

    note = await analyst.classify_note(text)
    if note:
        from utils.notes import save_note
        save_note(date.today(), note.get("category", "other"), text)
        summary = note.get("summary", "")
        send_text(user_id, f"📌 已记录{('：' + summary) if summary else ''}")
        _log({"type": "note", "user": user_id, "text": text})
        return

    diary = await analyst.detect_diary(text)
    if diary:
        await _diary(user_id, st, text, diary)
        return

    role = await analyst.route_message(text)
    if role == "psychologist":
        await _psychologist(user_id, st, text, "route")
    else:
        await _coach(user_id, st, text, "route")


def _weight_date(text: str) -> date:
    """Which day a weigh-in belongs to. Someone without a scale at home weighs
    wherever they can and records it later, so a bare number cannot always mean
    today."""
    for word, back in _DAYS_BACK.items():
        if word in text:
            return date.today() - timedelta(days=back)
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", text)
    if m:
        today = date.today()
        month, day = int(m.group(1)), int(m.group(2))
        year = today.year - 1 if month > today.month else today.year
        try:
            return date(year, month, day)
        except ValueError:
            pass
    return date.today()


async def _handle_food_text(user_id: str, st: dict, text: str) -> bool:
    """Grams for a looked-up barcode, or a description to estimate. True if handled."""
    from llm.nutrition import scale_to_grams, format_scaled, format_estimate, per_100g_from_estimate
    food = st["food"]

    if food.get("canon"):
        serving_g = food.get("serving_g")
        if text in _WHOLE_PACK and isinstance(serving_g, (int, float)):
            grams = float(serving_g)
        else:
            m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(?:g|克|G|克重)?\s*$", text)
            grams = float(m.group(1)) if m else None
        if grams is not None:
            canon, item_id = food["canon"], food["item_id"]
            _food_reset(st)
            if item_id:
                crud.record_food_use(item_id, grams)
            scaled = scale_to_grams(canon, grams)
            send_text(user_id, format_scaled(scaled))
            _log({"type": "food_scaled", "user": user_id, "grams": grams})
            return True
        _food_reset(st)  # not an amount, treat it as an ordinary message
        return False

    if food.get("armed"):
        _food_reset(st)
        send_text(user_id, "🍎 估算中...")
        try:
            from llm.foodsearch import estimate_food_text
            est = await estimate_food_text(text)
            reply = format_estimate(est)
            keep = per_100g_from_estimate(est, text)
            if keep:
                crud.remember_food(*keep)
                reply += f"\n📚 已存入食物库（{keep[0]}），下次 /foods 直接选"
            send_text(user_id, reply)
            _log({"type": "food_estimate", "user": user_id, "text": text})
        except Exception as e:
            logger.exception("food estimate failed")
            send_text(user_id, f"估算失败：{e}")
        return True

    return False


async def handle_image(user_id: str, media_id: str) -> None:
    """A photo is a product barcode. Screenshot parsing is no longer supported."""
    st = _s(user_id)
    if not st["food"]["armed"]:
        send_text(user_id, "要记食物，先发 /food，再拍条码或文字描述这个食物。")
        return

    send_text(user_id, "🔎 正在识别条码...")
    try:
        from utils.barcode import decode as decode_barcode
        from llm.foodsearch import lookup_barcode
        from llm.nutrition import format_off_prompt

        code = decode_barcode(download_media(media_id))
        if not code:
            send_text(user_id, "没识别出条码。把条码拍清楚、正对着再发一次，\n"
                               "或直接文字描述这个食物（如「乐事原味薯片 一包」），我来估。")
            return  # stay armed
        prod = await lookup_barcode(code)
        if not prod:
            send_text(user_id, f"Open Food Facts 里没有条码 {code} 的营养数据。\n"
                               "直接文字描述这个食物，我联网估算。")
            return  # stay armed
        crud.remember_food(prod["name"], prod["canon"], barcode=prod["code"],
                           brand=prod.get("brand"), serving_g=prod.get("serving_g"))
        saved = crud.find_food(prod["name"], prod["code"])
        st["food"].update({"armed": True, "canon": prod["canon"], "name": prod["name"],
                           "serving_g": prod.get("serving_g"),
                           "item_id": saved.id if saved else None})
        send_text(user_id, format_off_prompt(prod))
        _log({"type": "barcode", "user": user_id, "code": code, "name": prod["name"]})
    except Exception as e:
        logger.exception("barcode/OFF failed")
        send_text(user_id, f"查询失败：{e}")


async def _coach(user_id: str, st: dict, text: str, mode: str) -> None:
    send_text(user_id, "🏋️ 查询中...")
    from bot.handlers import _build_context
    answer = await analyst.answer_question(text, _build_context(), history=list(st["history"]))
    send_text(user_id, answer)
    _append_history(st, text, answer)
    _log({"type": "coach", "user": user_id, "mode": mode, "text": text, "response": answer})


async def _psychologist(user_id: str, st: dict, text: str, mode: str) -> None:
    send_text(user_id, "💬 思考中...")
    from utils.psych_memory import load_psych_memory
    answer = await analyst.answer_as_psychologist(text, load_psych_memory(),
                                                  history=list(st["history"]))
    send_text(user_id, answer)
    _append_history(st, text, answer)
    _log({"type": "psychologist", "user": user_id, "mode": mode, "text": text, "response": answer})


async def _diary(user_id: str, st: dict, text: str, diary: dict) -> None:
    from utils.psych_memory import load_psych_memory, save_psych_memory
    content = diary.get("content", text)
    rec = crud.save_diary(entry_date=date.today(), content=content,
                          mood=diary.get("mood"), mood_score=diary.get("mood_score"))
    memory = load_psych_memory()
    response = await analyst.generate_diary_response(content, diary.get("mood", ""), memory)
    mood_str = f"心情：{rec.mood}（{rec.mood_score}/5）" if rec.mood else ""
    send_text(user_id, f"📔 {rec.date} {mood_str}\n\n{response}")
    _append_history(st, text, response)
    _log({"type": "diary_reply", "user": user_id, "text": text, "response": response})

    async def _upd():
        new_mem = await analyst.update_psych_memory(memory, content, diary.get("mood", ""))
        if new_mem:
            save_psych_memory(new_mem)
    asyncio.create_task(_upd())


async def _handle_command(user_id: str, st: dict, text: str) -> None:
    cmd = text.split()[0].lower()
    arg = text[len(cmd):].strip()

    if cmd == "/setup":
        parts = arg.split()
        if len(parts) < 3:
            send_text(user_id, _SETUP_HELP)
            return
        try:
            height, age = float(parts[0]), int(parts[1])
        except ValueError:
            send_text(user_id, _SETUP_HELP)
            return
        gender = "female" if parts[2] in ("女", "f", "female", "F") else "male"
        goal = float(parts[3]) if len(parts) > 3 else 1.0
        crud.update_user_profile(height_cm=height, age=age, gender=gender,
                                 monthly_loss_kg=goal,
                                 # No tracker to calibrate against for a new user.
                                 active_eatback_pct=0.4)
        bmr = crud.get_bmr()
        send_text(user_id, f"✅ 资料已保存\n"
                           f"身高 {height:g}cm　年龄 {age}　"
                           f"{'女' if gender == 'female' else '男'}\n"
                           f"目标 每月 {goal:g}kg\n\n"
                           f"基础代谢 {bmr:.0f} kcal\n\n"
                           f"下一步：发一句「体重 58」记录今天的体重，"
                           f"我就能算出你每天该吃多少。")
        return

    if cmd == "/food":
        _food_reset(st)
        st["food"]["armed"] = True
        send_text(user_id, "🍎 记食物已就绪。\n"
                           "· 拍一张商品条码照片 → 查 Open Food Facts，再问你吃了多少克\n"
                           "· 或直接文字描述（如「150g蓝莓」）→ 我来估算")
    elif cmd == "/foods":
        items = crud.get_food_library(arg)
        if not items:
            send_text(user_id, f"食物库里没有匹配「{arg}」的东西。" if arg
                      else "食物库还是空的。扫一次条码，之后就会出现在这里。")
            return
        lines = ["📚 食物库（回「用 序号 克数」记录，如「用 1 150」）"]
        for i, it in enumerate(items, 1):
            last = f" · 上次{it.last_grams:g}g" if it.last_grams else ""
            lines.append(f"{i}. {it.name}{last}")
        st["food"]["menu"] = [it.id for it in items]
        send_text(user_id, "\n".join(lines))
    elif cmd == "/today":
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
            send_text(user_id, f"📊 本周\n🔥 均摄入：{avg_cal:.0f}kcal\n"
                               f"📉 累计缺口：{total:.0f}kcal ≈ {total/7700:.2f}kg脂肪")
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
    else:
        send_text(user_id, "可用指令：\n/food 记食物　/foods 食物库\n"
                           "/today 今日　/week 本周　/body 身体成分　/report 周报\n"
                           "/mode 教练|聊天|自动")
