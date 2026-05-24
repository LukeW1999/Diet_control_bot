"""
Compute and cache body stats to data/stats_cache.json.
Called automatically whenever body composition data is saved.
LLM reads this file as ground-truth facts — no arithmetic needed.
"""
import json
import os
from datetime import date, timedelta

_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "stats_cache.json"
)


def _diff_block(records, days_label: str, meaning: str) -> dict | None:
    """Return a diff dict for the last N days, or None if insufficient data."""
    if len(records) < 2:
        return None
    first, last = records[0], records[-1]
    actual_days = (last["date"] - first["date"]).days
    if actual_days == 0:
        return None
    change = last["weight_kg"] - first["weight_kg"]
    weeks = actual_days / 7
    return {
        "from_date": str(first["date"]),
        "to_date": str(last["date"]),
        "actual_days": actual_days,
        "actual_weeks": round(weeks, 1),
        "from_weight_kg": first["weight_kg"],
        "to_weight_kg": last["weight_kg"],
        "change_kg": round(change, 2),
        "kg_per_week": round(change / weeks, 2),
        "meaning": meaning,
    }


def _body_comp_diff(records, field: str, label: str) -> dict | None:
    """Return first/last non-null values for a body composition field."""
    filled = [r for r in records if r.get(field) is not None]
    if len(filled) < 2:
        return None
    first, last = filled[0], filled[-1]
    change = last[field] - first[field]
    days = (last["date"] - first["date"]).days
    return {
        "from_date": str(first["date"]),
        "to_date": str(last["date"]),
        "from_value": first[field],
        "to_value": last[field],
        "change": round(change, 2),
        "days": days,
        "label": label,
    }


def compute_and_save() -> None:
    """Read DB, compute all stats, write stats_cache.json."""
    from db import crud

    today = date.today()
    raw = crud.get_body_compositions_range(today - timedelta(days=730), today)
    if not raw:
        return

    # Normalise to plain dicts so we can json-serialize
    all_records = [
        {
            "date": r.date,
            "weight_kg": r.weight_kg,
            "body_fat_pct": r.body_fat_pct,
            "skeletal_muscle_kg": r.skeletal_muscle_kg,
            "muscle_mass_kg": r.muscle_mass_kg,  # fat-free mass
            "visceral_fat_level": r.visceral_fat_level,
            "bmi": r.bmi,
        }
        for r in raw
    ]

    w_records = [r for r in all_records if r["weight_kg"] is not None]
    if not w_records:
        return

    latest = w_records[-1]
    peak = max(w_records, key=lambda r: r["weight_kg"])

    # Weight trends
    def slice_recent(days: int):
        cutoff = today - timedelta(days=days)
        subset = [r for r in w_records if r["date"] >= cutoff]
        return subset if len(subset) >= 2 else None

    weight_trends = {}

    # From peak
    peak_idx = w_records.index(peak)
    from_peak = w_records[peak_idx:]
    if len(from_peak) >= 2:
        weight_trends["from_peak"] = _diff_block(
            from_peak, "peak→now", "从历史最高体重到现在的总减重进度和均速"
        )

    for label, days, meaning in [
        ("last_90d", 90, "近3个月减重速度"),
        ("last_30d", 30, "近1个月减重速度"),
        ("last_7d", 7, "近1周减重速度"),
    ]:
        subset = slice_recent(days)
        if subset:
            weight_trends[label] = _diff_block(subset, label, meaning)

    # Body composition trends
    body_comp = {}
    for field, label in [
        ("body_fat_pct", "体脂率变化（%），下降=减脂成功"),
        ("skeletal_muscle_kg", "骨骼肌量变化（kg），上升=增肌，下降=需警惕"),
        ("muscle_mass_kg", "去脂体重变化（kg），下降=肌肉/水分流失"),
        ("visceral_fat_level", "内脏脂肪等级变化，下降=内脏健康改善"),
        ("bmi", "BMI变化"),
    ]:
        d = _body_comp_diff(all_records, field, label)
        if d:
            body_comp[field] = d

    cache = {
        "generated_at": str(today),
        "note": "所有数字由Python精确计算，LLM应直接引用这些数字，不要自行重新计算",
        "latest": {
            "date": str(latest["date"]),
            "weight_kg": latest["weight_kg"],
            "body_fat_pct": latest.get("body_fat_pct"),
            "skeletal_muscle_kg": latest.get("skeletal_muscle_kg"),
            "muscle_mass_kg": latest.get("muscle_mass_kg"),
        },
        "peak_weight": {
            "date": str(peak["date"]),
            "weight_kg": peak["weight_kg"],
            "note": "历史最高体重记录点",
        },
        "weight_trends": weight_trends,
        "body_composition_trends": body_comp,
    }

    os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, default=str)


def load_stats_cache() -> dict | None:
    if not os.path.exists(_CACHE_PATH):
        return None
    with open(_CACHE_PATH, encoding="utf-8") as f:
        return json.load(f)
