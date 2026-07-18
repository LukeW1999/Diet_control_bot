"""Shared nutrition math + formatting.

Data comes from two sources (see llm.foodsearch): a barcode → Open Food Facts
(per-100g, canonical shape) or a free-text estimate from Qwen. This module owns
the pieces they share: scale-per-100g-to-grams, the HealthKit write link, and the
Telegram reply formatting. No LLM vision here — labels are read via barcode now.
"""
import json
import urllib.parse


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _f(v, unit=""):
    return f"{v:g}{unit}" if _num(v) else "—"


# ── HealthKit write link ────────────────────────────────────────────────────────
_HK_BASE = "https://bot.weiqiwang.work/hk/write"
_HK_KEYMAP = {
    "dietary_energy_kcal": "kcal", "protein_g": "protein", "carbs_g": "carbs",
    "fat_g": "fat", "saturated_fat_g": "satfat", "fiber_g": "fiber",
    "sugar_g": "sugar", "sodium_mg": "sodium",
}


def healthkit_link(hk: dict) -> str:
    """Tappable https link → redirects into the iOS '写入健康' shortcut."""
    payload = {short: hk.get(k) for k, short in _HK_KEYMAP.items() if _num(hk.get(k))}
    q = urllib.parse.urlencode({"d": json.dumps(payload, separators=(",", ":"))})
    return f"{_HK_BASE}?{q}"


# ── scale per-100g → grams ──────────────────────────────────────────────────────
def scale_to_grams(canon: dict, grams: float) -> dict:
    """Scale per-100g canonical values to an arbitrary gram amount (exact)."""
    factor = grams / 100.0

    def s(k):
        v = canon.get(k, [None])[0]
        return round(v * factor, 1) if _num(v) else None

    salt = canon.get("salt", [None])[0]
    sodium = round(salt * factor * 400) if _num(salt) else None  # 1g salt = 400mg sodium
    return {
        "grams": grams,
        "dietary_energy_kcal": s("energy_kcal"),
        "protein_g": s("protein"),
        "carbs_g": s("carbs"),
        "fat_g": s("fat"),
        "saturated_fat_g": s("saturates"),
        "fiber_g": s("fibre"),
        "sugar_g": s("sugars"),
        "sodium_mg": sodium,
    }


# ── formatting ──────────────────────────────────────────────────────────────────
def format_off_prompt(prod: dict) -> str:
    """After a barcode lookup: show the product + per-100g facts, then ask grams."""
    canon = prod["canon"]
    e = canon.get("energy_kcal", [None])[0]
    p = canon.get("protein", [None])[0]
    c = canon.get("carbs", [None])[0]
    fat = canon.get("fat", [None])[0]

    title = prod["name"]
    if prod.get("brand"):
        title += f"（{prod['brand']}）"
    lines = [
        f"🔎 {title}",
        f"每100g：🔥{_f(e)}kcal　🥩{_f(p)}　🍞{_f(c)}　🧈{_f(fat)}",
    ]
    serving = prod.get("serving_g")
    if _num(serving):
        lines.append(f"（一份约 {_f(serving)}g）")
        lines.append(f"\n👉 吃了多少克？回数字（如 {serving:g}），或回「整份」。")
    else:
        lines.append("\n👉 吃了多少克？回数字（如 150）。")
    return "\n".join(lines)


def format_scaled(scaled: dict) -> str:
    """Final nutrition for the chosen gram amount, with a HealthKit link."""
    return "\n".join([
        f"✅ 记 {_f(scaled['grams'])}g：",
        f"🔥 {_f(scaled['dietary_energy_kcal'])} kcal",
        f"🥩 蛋白 {_f(scaled['protein_g'],'g')}　🍞 碳水 {_f(scaled['carbs_g'],'g')}　🧈 脂肪 {_f(scaled['fat_g'],'g')}",
        f"🌾 纤维 {_f(scaled['fiber_g'],'g')}　🍬 糖 {_f(scaled['sugar_g'],'g')}　🧂 钠 {_f(scaled['sodium_mg'],'mg')}",
        f"\n🍎 点这里写入健康：\n{healthkit_link(scaled)}",
    ])


def format_estimate(est: dict) -> str:
    """Free-text estimate (Qwen + search): show the assumed portion + a HealthKit link."""
    lines = [f"🍎 {est['food']}（联网估算）"]
    if est.get("assumed_portion"):
        lines.append(f"份量：{est['assumed_portion']}")
    lines += [
        f"🔥 {_f(est.get('dietary_energy_kcal'))} kcal",
        f"🥩 蛋白 {_f(est.get('protein_g'),'g')}　🍞 碳水 {_f(est.get('carbs_g'),'g')}　🧈 脂肪 {_f(est.get('fat_g'),'g')}",
    ]
    if est.get("note"):
        lines.append(f"ℹ️ {est['note']}")
    lines.append(f"\n🍎 点这里写入健康：\n{healthkit_link(est)}")
    return "\n".join(lines)
