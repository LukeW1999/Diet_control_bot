import json
import os
import re
from datetime import date, timedelta
from pathlib import Path


LOG_PATH = Path(__file__).parent.parent / "data" / "food_log.txt"


def write_entry(record) -> None:
    """Write or overwrite today's entry in the food log."""
    meals = json.loads(record.meals_json or "[]")
    exercise = json.loads(record.exercise_json or "[]")
    meal_labels = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "加餐"}

    lines = [
        f"[{record.date}] 总摄入:{record.total_calories:.0f}kcal "
        f"蛋白质:{record.protein_g:.0f}g 碳水:{record.carbs_g:.0f}g 脂肪:{record.fat_g:.0f}g"
    ]
    for meal in meals:
        label = meal_labels.get(meal.get("meal_type", ""), meal.get("meal_type", ""))
        cal = meal.get("total_calories", 0)
        foods = ", ".join(
            f"{f['name']}{f.get('amount', '')}" for f in meal.get("foods", [])
        )
        lines.append(f"  {label}({cal:.0f}kcal): {foods}")

    for ex in exercise:
        lines.append(f"  运动: {ex.get('name', '')} {ex.get('calories_burned', 0):.0f}kcal")

    new_entry = "\n".join(lines)
    date_tag = f"[{record.date}]"

    # Remove existing entry for this date then append updated one
    existing = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""
    blocks = _split_blocks(existing)
    blocks = [b for b in blocks if not b.startswith(date_tag)]
    blocks.append(new_entry)
    blocks.sort()  # keep chronological order

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def search(keyword: str, max_results: int = 10) -> list[str]:
    """Return log entries containing keyword."""
    if not LOG_PATH.exists():
        return []
    blocks = _split_blocks(LOG_PATH.read_text(encoding="utf-8"))
    kw = keyword.lower()
    matched = [b for b in blocks if kw in b.lower()]
    return matched[-max_results:]


def get_recent(days: int = 7) -> list[str]:
    """Return the last N days of entries."""
    if not LOG_PATH.exists():
        return []
    blocks = _split_blocks(LOG_PATH.read_text(encoding="utf-8"))
    cutoff = str(date.today() - timedelta(days=days))
    recent = [b for b in blocks if b[:12] >= f"[{cutoff}]"]
    return recent


def get_by_date(target_date: date) -> str | None:
    """Return entry for a specific date."""
    results = search(f"[{target_date}]", max_results=1)
    return results[0] if results else None


def get_high_calorie_days(threshold: int = 2200) -> list[str]:
    """Return days where total intake exceeded threshold."""
    if not LOG_PATH.exists():
        return []
    blocks = _split_blocks(LOG_PATH.read_text(encoding="utf-8"))
    results = []
    for b in blocks:
        m = re.search(r"总摄入:(\d+)kcal", b)
        if m and int(m.group(1)) >= threshold:
            results.append(b)
    return results


def _split_blocks(text: str) -> list[str]:
    blocks = [b.strip() for b in text.strip().split("\n\n") if b.strip()]
    return blocks
