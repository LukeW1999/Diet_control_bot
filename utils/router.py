"""Conversation routing, independent of which messenger carried the message.

WeCom and WeChat both end up here; `send` is passed in because that is the only
part that differs. It takes `progress=True` for the "working on it" notes, which
a transport is free to drop: a WeChat reply spends the inbound `context_token`,
so sending one of those would leave the real answer with no way out. Keeping one copy matters more than it looks: the transports
had already drifted once, and typed food silently stopped being logged on one of
them for a day.
"""
import asyncio
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

from db import crud
from llm import analyst
from utils import foodlog

logger = logging.getLogger(__name__)

_MAX_HISTORY_TURNS = 8
_CONV_LOG = os.path.join(os.path.dirname(__file__), "..", "data", "conversation_log.jsonl")
_MODE_LABELS = {"auto": "🤖 自动", "coach": "🏋️ 教练", "chat": "💬 聊天"}
_WHOLE_PACK = ("整份", "整包", "一份", "全部", "pack", "whole")

_SETUP_HELP = ("👋 先告诉我三件事，才能算你的热量：\n\n"
               "发「/setup 身高 年龄 性别」，例如：\n"
               "　/setup 165 28 女\n\n"
               "默认只记录热量、不减脂。想减的话末尾加每月几公斤：\n"
               "　/setup 165 28 女 1\n\n"
               "（没有运动手表的话，缺口只能从吃里省，定太快会被安全下限挡住）")

_DAYS_BACK = {"今天": 0, "昨天": 1, "前天": 2, "大前天": 3}

_WEIGHT_HELP = ("还差体重。发一句：\n"
                "　体重 58\n"
                "（换成你自己的。基础代谢要用身高、年龄、性别加体重才能算，"
                "四样缺一不可）")

_state: dict[str, dict] = {}


def _s(key: str) -> dict:
    """Per-user state. Module globals here would have let one person's mode and
    conversation history show up in another's replies."""
    return _state.setdefault(key, {
        "mode": "auto",
        "history": [],
        "food": {"armed": False, "canon": None, "name": None,
                 "serving_g": None, "item_id": None, "menu": None,
                 "delete_menu": None},
    })


def _food_reset(st: dict) -> None:
    st["food"] = {"armed": False, "canon": None, "name": None,
                  "serving_g": None, "item_id": None, "menu": None,
                  "delete_menu": None}


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


def _setup_gap() -> str | None:
    """What is still missing before any number here can be trusted. Height, age and
    sex come from the profile; without a weight as well `get_bmr` falls back to the
    `.env` figure, which belongs to the primary user."""
    profile = crud.get_user_profile()
    if not (profile and profile.age and profile.height_cm):
        return "profile"
    if not crud.get_latest_body_composition():
        return "weight"
    return None


async def handle_text(key: str, send, text: str) -> None:
    st = _s(key)
    text = text.strip()
    logger.info("[MSG] from=%s mode=%s text=%s", key, st["mode"], text)

    gap = _setup_gap()
    if gap == "profile" and not text.lower().startswith("/setup"):
        send(_SETUP_HELP)
        return
    if gap == "weight" and not re.search(r"体重\s*[\d.]+", text):
        send(_WEIGHT_HELP)
        return

    if text.lower().startswith("/mode"):
        arg = text[5:].strip()
        mapping = {"教练": "coach", "coach": "coach", "聊天": "chat",
                   "chat": "chat", "自动": "auto", "auto": "auto"}
        if arg in mapping:
            st["mode"] = mapping[arg]
        send(f"当前：{_MODE_LABELS[st['mode']]}\n\n/mode 教练 | /mode 聊天 | /mode 自动")
        return

    undo_n = foodlog.UNDO_RE.match(text)
    if undo_n:
        send(foodlog.undo(int(undo_n.group(1))))
        return
    if text in foodlog.TODAY_WORDS:
        from bot.handlers import _build_today_summary
        send(_build_today_summary(date.today()))
        return

    if text in foodlog.PARTNER_WORDS:
        send(foodlog.partner_day())
        return

    if text in foodlog.LIST_WORDS or text.lower() == "/undo":
        prompt, ids = foodlog.delete_prompt()
        st["food"]["delete_menu"] = ids
        send(prompt)
        return
    if text in foodlog.UNDO_WORDS:
        send(foodlog.undo())
        return

    if text.startswith("/"):
        await _handle_command(key, send, st, text)
        return

    if await _handle_food_text(key, send, st, text):
        return

    if st["mode"] == "coach":
        await _coach(key, send, st, text, "manual")
        return
    if st["mode"] == "chat":
        await _psychologist(key, send, st, text, "manual")
        return

    weight_match = re.search(r"体重\s*([\d.]+)", text)
    if weight_match:
        weight = float(weight_match.group(1))
        when = _weight_date(text)
        crud.quick_weight_entry(when, weight)
        send(f"✅ 体重已记录：{weight} kg（{when}）")
        return

    if foodlog.FOOD_HINT.search(text):
        _food_reset(st)
        await _estimate_and_log(key, send, text)
        return

    correction = await analyst.detect_correction(text)
    if correction:
        record_date = date.fromisoformat(correction["date"])
        ok = crud.apply_correction(correction["table"], correction["field"],
                                   correction["value"], record_date)
        field_cn = {"visceral_fat_level": "内脏脂肪", "body_fat_pct": "体脂率",
                    "weight_kg": "体重", "total_calories": "总热量"}.get(
                        correction["field"], correction["field"])
        send(f"✅ 已修正 {record_date} 的{field_cn}：{correction['value']}"
                  if ok else "找不到记录，无法修正。")
        return

    note = await analyst.classify_note(text)
    if note:
        from utils.notes import save_note
        save_note(date.today(), note.get("category", "other"), text)
        summary = note.get("summary", "")
        send(f"📌 已记录{('：' + summary) if summary else ''}")
        _log({"type": "note", "user": key, "text": text})
        return

    diary = await analyst.detect_diary(text)
    if diary:
        await _diary(key, send, st, text, diary)
        return

    role = await analyst.route_message(text)
    if role == "psychologist":
        await _psychologist(key, send, st, text, "route")
    else:
        await _coach(key, send, st, text, "route")


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


async def _handle_food_text(key: str, send, st: dict, text: str) -> bool:
    """Grams for a looked-up barcode, or a description to estimate. True if handled."""
    from llm.nutrition import scale_to_grams, format_scaled
    food = st["food"]

    to_delete = food.get("delete_menu")
    if to_delete:
        m = re.match(r"^\s*(\d+)\s*$", text)
        food["delete_menu"] = None
        if m and 1 <= int(m.group(1)) <= len(to_delete):
            send(foodlog.delete_by_id(to_delete[int(m.group(1)) - 1]))
            return True

    menu = food.get("menu")
    if menu:
        m = re.match(r"^\s*(\d+)\s*$", text)
        if m and 1 <= int(m.group(1)) <= len(menu):
            item_id = menu[int(m.group(1)) - 1]
            _food_reset(st)
            send(foodlog.log_from_library(item_id))
            return True
        _food_reset(st)

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
            send(foodlog.log_from_library(item_id, grams) if item_id
                      else format_scaled(scale_to_grams(canon, grams)))
            _log({"type": "food_scaled", "user": key, "grams": grams})
            return True
        _food_reset(st)  # not an amount, treat it as an ordinary message
        return False

    if food.get("armed"):
        # `/food` only still matters for a description with no amount in it, which
        # `FOOD_HINT` cannot spot. Either way it is the same logging path.
        _food_reset(st)
        await _estimate_and_log(key, send, text)
        return True

    return False


async def _estimate_and_log(key: str, send, text: str) -> None:
    send("🍎 估算中...", progress=True)
    try:
        send(await foodlog.log_text(text))
        _log({"type": "food_estimate", "user": key, "text": text})
    except Exception as e:
        logger.exception("food estimate failed")
        send(f"估算失败：{e}")


async def handle_image(key: str, send, fetch_media) -> None:
    """A photo is a product barcode. Screenshot parsing is no longer supported."""
    st = _s(key)
    if not st["food"]["armed"]:
        send("要记食物，先发 /food，再拍条码或文字描述这个食物。")
        return

    send("🔎 正在识别条码...", progress=True)
    try:
        from utils.barcode import decode as decode_barcode
        from llm.foodsearch import lookup_barcode
        from llm.nutrition import format_off_prompt

        code = decode_barcode(fetch_media())
        if not code:
            send("没识别出条码。把条码拍清楚、正对着再发一次，\n"
                               "或直接文字描述这个食物（如「乐事原味薯片 一包」），我来估。")
            return  # stay armed
        prod = await lookup_barcode(code)
        if not prod:
            send(f"Open Food Facts 里没有条码 {code} 的营养数据。\n"
                               "直接文字描述这个食物，我联网估算。")
            return  # stay armed
        crud.remember_food(prod["name"], prod["canon"], barcode=prod["code"],
                           brand=prod.get("brand"), serving_g=prod.get("serving_g"))
        saved = crud.find_food(prod["name"], prod["code"])
        st["food"].update({"armed": True, "canon": prod["canon"], "name": prod["name"],
                           "serving_g": prod.get("serving_g"),
                           "item_id": saved.id if saved else None})
        send(format_off_prompt(prod))
        _log({"type": "barcode", "user": key, "code": code, "name": prod["name"]})
    except Exception as e:
        logger.exception("barcode/OFF failed")
        send(f"查询失败：{e}")


async def _coach(key: str, send, st: dict, text: str, mode: str) -> None:
    send("🏋️ 查询中...", progress=True)
    from bot.handlers import _build_context
    answer = await analyst.answer_question(text, _build_context(), history=list(st["history"]))
    send(answer)
    _append_history(st, text, answer)
    _log({"type": "coach", "user": key, "mode": mode, "text": text, "response": answer})


async def _psychologist(key: str, send, st: dict, text: str, mode: str) -> None:
    send("💬 思考中...", progress=True)
    from utils.psych_memory import load_psych_memory
    answer = await analyst.answer_as_psychologist(text, load_psych_memory(),
                                                  history=list(st["history"]))
    send(answer)
    _append_history(st, text, answer)
    _log({"type": "psychologist", "user": key, "mode": mode, "text": text, "response": answer})


async def _diary(key: str, send, st: dict, text: str, diary: dict) -> None:
    from utils.psych_memory import load_psych_memory, save_psych_memory
    content = diary.get("content", text)
    rec = crud.save_diary(entry_date=date.today(), content=content,
                          mood=diary.get("mood"), mood_score=diary.get("mood_score"))
    memory = load_psych_memory()
    response = await analyst.generate_diary_response(content, diary.get("mood", ""), memory)
    mood_str = f"心情：{rec.mood}（{rec.mood_score}/5）" if rec.mood else ""
    send(f"📔 {rec.date} {mood_str}\n\n{response}")
    _append_history(st, text, response)
    _log({"type": "diary_reply", "user": key, "text": text, "response": response})

    async def _upd():
        new_mem = await analyst.update_psych_memory(memory, content, diary.get("mood", ""))
        if new_mem:
            save_psych_memory(new_mem)
    asyncio.create_task(_upd())


async def _handle_command(key: str, send, st: dict, text: str) -> None:
    cmd = text.split()[0].lower()
    arg = text[len(cmd):].strip()

    if cmd == "/setup":
        parts = arg.split()
        if len(parts) < 3:
            send(_SETUP_HELP)
            return
        try:
            height, age = float(parts[0]), int(parts[1])
        except ValueError:
            send(_SETUP_HELP)
            return
        gender = "female" if parts[2] in ("女", "f", "female", "F") else "male"
        # Maintenance unless a goal is asked for: nobody should be put on a
        # deficit by default.
        goal = float(parts[3]) if len(parts) > 3 else 0.0
        crud.update_user_profile(height_cm=height, age=age, gender=gender,
                                 monthly_loss_kg=goal,
                                 # No tracker, so everyday movement is not reported
                                 # anywhere and BMR alone would understate upkeep.
                                 activity_factor=1.3,
                                 # WeCom cannot open the HealthKit link, so intake
                                 # is summed here instead of synced back.
                                 server_food_log=1,
                                 active_eatback_pct=0.4)
        aim = "维持体重，只记录热量" if goal <= 0 else f"每月减 {goal:g}kg"
        send(f"✅ 资料已保存\n"
                           f"身高 {height:g}cm　年龄 {age}　"
                           f"{'女' if gender == 'female' else '男'}\n"
                           f"目标：{aim}\n\n"
                           f"下一步：发一句「体重 58」记下今天的体重。"
                           f"基础代谢要用体重才能算，记了才有数。")
        # Deliberately no BMR here: without a weight it would be the .env fallback.
        return

    if cmd == "/food":
        _food_reset(st)
        st["food"]["armed"] = True
        send("🍎 记食物已就绪。\n"
                           "· 拍一张商品条码照片 → 查 Open Food Facts，再问你吃了多少克\n"
                           "· 或直接文字描述（如「150g蓝莓」）→ 我来估算")
    elif cmd == "/foods":
        text_out, ids = foodlog.library_list(arg)
        st["food"]["menu"] = ids
        send(text_out)
    elif cmd in ("/ta", "/partner", "/对方"):
        send(foodlog.partner_day())
    elif cmd == "/today":
        from bot.handlers import _build_today_summary
        send(_build_today_summary(date.today()))
    elif cmd == "/week":
        today = date.today()
        records = crud.get_daily_summaries_range(today - timedelta(days=6), today)
        if not records:
            send("本周还没有数据。")
        else:
            total = sum(r.calorie_deficit or 0 for r in records)
            avg_cal = sum(r.total_calories_in or 0 for r in records) / len(records)
            send(f"📊 本周\n🔥 均摄入：{avg_cal:.0f}kcal\n"
                               f"📉 累计缺口：{total:.0f}kcal ≈ {total/7700:.2f}kg脂肪")
    elif cmd == "/body":
        rec = crud.get_latest_body_composition()
        if rec:
            from bot.handlers import _format_body_reply
            send(_format_body_reply(rec, None))
        else:
            send("还没有身体成分记录。")
    elif cmd == "/report":
        send("正在生成周报...", progress=True)
        from bot.handlers import _generate_report
        send(await _generate_report())
    else:
        send("直接打字就能记，比如「米饭200g」「一个鸡蛋」。\n\n"
                           "可用指令：\n/foods 吃过的东西　撤回 删掉上一笔\n"
                           "/ta 看对方今天吃了什么\n"
                           "/today 今日　/week 本周　/body 身体成分　/report 周报\n"
                           "/mode 教练|聊天|自动")
