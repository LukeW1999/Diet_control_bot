"""The food log itself, independent of Telegram or WeCom.

Each function returns the text to send, so both transports share one copy of the
rules: what counts as food, what a running total says, what undo removes.
"""
import json
import re

from db import crud
from utils import tenant

# Typing what you ate is the point, so an amount plus a unit is logged without
# arming anything first. The lookahead keeps "睡了8个小时" out.
FOOD_HINT = re.compile(
    r"(?:[\d.]+|[一二两三四五六七八九十半])\s*"
    r"(?:g|G|克|ml|ML|毫升|个|只|片|块|碗|杯|份|勺|根|颗|盒|袋|瓶)"
    r"(?!\s*(?:小时|分钟|天|步|公里|次|人|遍|年|月|周|岁))")

UNDO_WORDS = ("撤回", "记错了", "undo")          # drop the last thing logged
LIST_WORDS = ("删除", "删除记录", "删掉", "删")   # choose which one to drop

# WeChat has no menu, so the two things worth looking at have to be sayable.
TODAY_WORDS = ("今天", "今日", "汇总", "总共", "一共", "多少")
PARTNER_WORDS = ("她", "他", "对方", "ta", "TA", "Ta")

FOOTER = "记错了发「撤回」，要删别的发「删除」\n发「今天」看汇总，发「她」看对方吃了什么"
_PARTNER_LABEL = {"sjy": "她", "wangweiqi": "炜奇"}


def logs_to_server() -> bool:
    """WeCom cannot open the HealthKit link, and even where it can, a running total
    beats waiting for a round trip through Apple Health."""
    profile = crud.get_user_profile()
    return bool(profile and profile.server_food_log)


def today_line() -> str:
    rc = crud.recommend_calories()
    eaten = sum(e.energy_kcal or 0 for e in crud.get_food_entries())
    left = round(rc["high"] - eaten)
    return (f"今天累计 {eaten:.0f} / {rc['low']}–{rc['high']} kcal　"
            + (f"还可吃 {left}" if left > 0 else f"已超 {-left}"))


async def log_text(description: str) -> str:
    """Estimate a typed description, keep every item, and report the running total."""
    from llm.foodsearch import estimate_food_text
    from llm.nutrition import _grams_in, format_estimate, per_100g_from_estimate

    est = await estimate_food_text(description)
    if not logs_to_server():
        return format_estimate(est)

    items = est.get("items") or [{"name": est.get("food", description[:20]),
                                  "portion": "",
                                  "energy_kcal": est.get("dietary_energy_kcal")}]
    total_kcal = est.get("dietary_energy_kcal") or 1
    for i in items:
        share = (i.get("energy_kcal") or 0) / total_kcal
        crud.add_food_entry(
            i.get("name") or description[:20], i.get("portion", ""),
            i.get("energy_kcal"),
            round((est.get("protein_g") or 0) * share, 1),
            round((est.get("carbs_g") or 0) * share, 1),
            round((est.get("fat_g") or 0) * share, 1))

    keep = per_100g_from_estimate(est, description)
    if keep:
        crud.remember_food(*keep)
        # Remember the amount too, so picking it off the list repeats what was
        # eaten rather than falling back to an arbitrary 100g.
        saved = crud.find_food(keep[0])
        grams = _grams_in(items[0].get("portion", ""))
        if saved and grams:
            crud.record_food_use(saved.id, grams)

    lines = ["✅ 已记录"]
    for i in items:
        lines.append(f"　• {i['name']} {i.get('portion','')}　{i.get('energy_kcal')} kcal")
    lines += [f"🔥 这一笔 {est.get('dietary_energy_kcal')} kcal　"
              f"🥩 蛋白 {est.get('protein_g')}g", "", today_line(), "",
              FOOTER]
    return "\n".join(lines)


def _local_time(stamp) -> str:
    """`created_at` is naive UTC; two people here are seven hours apart, so it has
    to be shown where they are or the times mean nothing."""
    if stamp is None:
        return ""
    from datetime import timezone
    from zoneinfo import ZoneInfo
    profile = crud.get_user_profile()
    zone = (profile.timezone if profile and profile.timezone else None) or "Europe/London"
    return stamp.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(zone)).strftime("%H:%M")


def entries_list(entries=None) -> str:
    """Numbered and timed, so "第几笔" and "几点那笔" both pick the same thing."""
    entries = crud.get_food_entries() if entries is None else entries
    if not entries:
        return "今天还没记东西。"
    return "\n".join(
        f"　{i}. {_local_time(e.created_at)}　{e.name} {e.portion}　"
        f"{(e.energy_kcal or 0):.0f} kcal"
        for i, e in enumerate(entries, 1))


def delete_prompt() -> tuple[str, list[int]]:
    """The list to choose from, and the ids behind it so a later reply still maps to
    the row it showed even if something else changed in between."""
    entries = crud.get_food_entries()
    if not entries:
        return "今天还没记东西，没有可删的。", []
    return ("🗑️ 删哪一笔？回数字：\n" + entries_list(entries),
            [e.id for e in entries])


def delete_by_id(entry_id: int) -> str:
    entry = crud.delete_food_entry(entry_id)
    if entry is None:
        return "这一笔已经不在了。"
    remaining = crud.get_food_entries()
    return (f"🗑️ 已删除：{entry.name} {entry.portion}"
            f"（{(entry.energy_kcal or 0):.0f} kcal）\n\n{today_line()}"
            + ("\n\n剩下的：\n" + entries_list(remaining) if remaining else ""))


def undo(index: int | None = None) -> str:
    """Remove the last entry, or the numbered one from today's list."""
    entries = crud.get_food_entries()
    if not entries:
        return "今天还没有可撤回的记录。"
    if index is None:
        entry = crud.undo_last_food_entry()
    elif 1 <= index <= len(entries):
        entry = crud.delete_food_entry(entries[index - 1].id)
    else:
        return (f"今天只有 {len(entries)} 笔，没有第 {index} 笔：\n"
                + entries_list(entries))
    return (f"↩️ 已撤回：{entry.name} {entry.portion}"
            f"（{(entry.energy_kcal or 0):.0f} kcal）\n\n{today_line()}"
            + ("\n\n剩下的：\n" + entries_list() if crud.get_food_entries() else ""))


UNDO_RE = re.compile(r"^\s*(?:撤回|删掉|删除)\s*(\d+)\s*$")


def library_list(keyword: str = "") -> tuple[str, list[int]]:
    items = crud.get_food_library(keyword)
    if not items:
        return (f"食物库里没有匹配「{keyword}」的东西。" if keyword
                else "食物库还是空的。记一次东西，之后就会出现在这里。"), []
    lines = ["📚 吃过的东西 —— 直接回数字就再记一份："]
    for i, it in enumerate(items, 1):
        last = f"（{it.last_grams:g}g）" if it.last_grams else ""
        lines.append(f"　{i}. {it.name}{last}")
    return "\n".join(lines), [it.id for it in items]


def log_from_library(item_id: int, grams: float | None = None) -> str:
    from llm.nutrition import scale_to_grams, format_scaled
    item = crud.get_food_item(item_id)
    if item is None:
        return "这条记录已经不在食物库里了。"
    grams = grams or item.last_grams or item.serving_g or 100
    scaled = scale_to_grams(json.loads(item.canon_json), grams)
    crud.record_food_use(item.id, grams)
    if not logs_to_server():
        return format_scaled(scaled)
    crud.add_food_entry(item.name, f"{grams:g}g", scaled["dietary_energy_kcal"],
                        scaled["protein_g"], scaled["carbs_g"], scaled["fat_g"])
    return (f"✅ 已记录 {item.name} {grams:g}g　"
            f"{(scaled['dietary_energy_kcal'] or 0):.0f} kcal\n\n"
            f"{today_line()}\n\n{FOOTER}")


def partner_day() -> str:
    """What the other half ate and weighs. The diary and the psychologist's notes
    stay private to whoever wrote them; writes stay separate regardless."""
    from datetime import date
    other = tenant.partner()
    if not other:
        return "还没有另一半的数据。"
    mine = tenant.current()
    try:
        tenant.set_current(other)
        entries = crud.get_food_entries()
        rc = crud.recommend_calories()
        record = crud.get_diet_record(date.today())
        body = crud.get_latest_body_composition()
    finally:
        tenant.set_current(mine)

    who = _PARTNER_LABEL.get(other, other)
    eaten = sum(e.energy_kcal or 0 for e in entries) or (
        record.total_calories if record else 0) or 0
    # "记了" rather than "吃了": all this knows is what was written down, and
    # reporting a light day as if it were the whole of someone's eating reads as
    # an accusation.
    lines = [f"👀 {who}今天记了 {len(entries)} 笔，共 {eaten:.0f} kcal"
             f"（目标 {rc['low']}–{rc['high']}）"]
    if entries:
        lines += [f"　• {e.name} {e.portion}　{(e.energy_kcal or 0):.0f} kcal"
                  for e in entries]
        if eaten < rc["low"] * 0.5:
            lines.append("（大概还有没记上的）")
    elif eaten:
        lines.append("（对方用 HealthKit 同步，看不到单项明细）")
    else:
        lines.append("今天还没记。")
    if body and body.weight_kg:
        lines.append(f"⚖️ 最新体重：{body.weight_kg} kg（{body.date}）")
    return "\n".join(lines)
