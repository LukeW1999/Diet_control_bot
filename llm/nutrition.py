"""Two-stage UK/EU nutrition-label reader.

Stage 1 (LLM vision, qwen3.7-plus): faithfully read the label into rows.
Stage 2 (pure Python): cross-check with three independent rules, flag
suspicious rows, and map to HealthKit dietary fields. Arithmetic is done in
Python, never in the LLM (LLMs are unreliable at math).
"""
import base64
import io
import json
import re
import urllib.parse
from statistics import median

from PIL import Image

from .client import vision_call, extract_json

VISION_MODEL = "qwen3.7-plus"

_EXTRACT_SYSTEM = """You are an OCR extraction engine for UK/EU nutrition labels. Read the table
FAITHFULLY and return JSON only — do NOT convert, infer, or normalise anything.
Copy every number exactly as printed. UK labels usually have TWO columns
(e.g. "per 100g" and "per pack/serving"); capture BOTH.

Return this shape:
{
  "columns": ["<header of col 1>", "<header of col 2>"],
  "rows": [
    {"label": "<row name exactly as printed>", "values": [<col1>, <col2>]}
  ],
  "confidence": "high/medium/low"
}

Rules:
- Include EVERY row: Energy (kJ), Energy (kcal), Fat, of which saturates,
  Carbohydrate, of which sugars, Fibre, Protein, Salt, etc.
- ENERGY: labels often merge it into one cell like "522kJ / 126kcal". You MUST
  still output TWO separate rows — label them exactly "Energy (kJ)" and
  "Energy (kcal)" — each with a plain number (e.g. 522 and 126).
- If there are more than two data columns (e.g. a "%RI" column), IGNORE the
  %RI/percent column; keep only the two absolute columns (per 100g and per pack/serving).
- If a column has no value for a row, use null.
- Numbers only in "values" (strip units like g/kJ/kcal/mg). Preserve decimals exactly.
- "<0.5" style values: use the number (0.5).
- Do not add rows that are not on the label."""

# canonical key -> label substrings (lowercased) that map to it
_KEYS = {
    "energy_kj":   ["energy (kj)", "energy kj", "(kj)"],
    "energy_kcal": ["energy (kcal)", "energy kcal", "(kcal)", "kcal"],
    "fat":         ["fat"],
    "saturates":   ["saturates", "saturated"],
    "carbs":       ["carbohydrate", "carbs"],
    "sugars":      ["sugars", "sugar"],
    "fibre":       ["fibre", "fiber"],
    "protein":     ["protein"],
    "salt":        ["salt"],
}
# order matters: check the more specific "saturates"/"sugars" before "fat"/"carbs"
_KEY_ORDER = ["energy_kj", "energy_kcal", "saturates", "sugars", "fat", "carbs", "fibre", "protein", "salt"]


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _coerce(x):
    """Models sometimes return numbers as strings ('592') — normalise to float."""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        m = re.search(r"-?\d+(?:\.\d+)?", x.replace(",", ""))
        if m:
            try:
                return float(m.group())
            except ValueError:
                return None
    return None


def _downscale(image_b64: str, max_w: int = 1100) -> str:
    """Shrink wide images before sending — faster/cheaper, no accuracy loss on labels."""
    raw = base64.b64decode(image_b64)
    img = Image.open(io.BytesIO(raw))
    if img.width > max_w:
        h = int(img.height * max_w / img.width)
        img = img.resize((max_w, h))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def _match_key(label: str):
    low = (label or "").lower()
    for key in _KEY_ORDER:
        for alias in _KEYS[key]:
            if alias in low:
                return key
    return None


def to_canonical(table: dict) -> dict:
    """rows[] -> {key: [per_100g, per_pack]}"""
    out = {}
    for row in table.get("rows", []):
        key = _match_key(row.get("label", ""))
        if not key or key in out:
            continue
        vals = row.get("values", []) or []
        out[key] = [
            _coerce(vals[0]) if len(vals) > 0 else None,
            _coerce(vals[1]) if len(vals) > 1 else None,
        ]
    return out


def validate(canon: dict) -> dict:
    """Three independent sanity checks. Returns consensus ratio + warnings."""
    warnings = []

    # (1) per-pack / per-100g ratio should be constant across every row
    ratios = [b / a for a, b in canon.values() if _num(a) and _num(b) and a > 0]
    ratio = median(ratios) if ratios else None
    if ratio:
        for k, (a, b) in canon.items():
            if _num(a) and _num(b) and a > 0:
                r = b / a
                expected = a * ratio
                # only warn on a real gap: both relative (>6%) AND absolute (>0.5g),
                # so rounding on tiny rows (sugars 0.7→1.9 etc.) doesn't false-alarm
                if abs(r - ratio) / ratio > 0.06 and abs(b - expected) > 0.5:
                    warnings.append(
                        f"{k}: 两栏比例 {r:.2f} 偏离整体 {ratio:.2f}"
                        f"（按比例应为 {expected:.1f}）"
                    )

    # (2) kcal ≈ fat*9 + carbs*4 + protein*4  (per 100g column)
    fat = canon.get("fat", [None])[0]
    carb = canon.get("carbs", [None])[0]
    prot = canon.get("protein", [None])[0]
    kcal = canon.get("energy_kcal", [None])[0]
    if all(_num(x) for x in (fat, carb, prot, kcal)) and kcal > 0:
        calc = fat * 9 + carb * 4 + prot * 4
        if abs(calc - kcal) / kcal > 0.12:
            warnings.append(
                f"热量核对：宏量算出 {calc:.0f} kcal ≠ 标签 {kcal:.0f} kcal"
                f"（脂肪/碳水/蛋白可能读错）"
            )

    # (3) subset rules
    for sub, whole, name in [("sugars", "carbs", "糖 > 碳水"), ("saturates", "fat", "饱和脂肪 > 总脂肪")]:
        s = canon.get(sub, [None])[0]
        w = canon.get(whole, [None])[0]
        if _num(s) and _num(w) and s > w + 0.05:
            warnings.append(f"{name}：{s} > {w}（不合理，至少一个读错）")

    return {"serving_ratio": ratio, "warnings": warnings}


def to_healthkit(canon: dict, column: int = 1) -> dict:
    """column: 0=per 100g, 1=per pack. Maps to HealthKit dietary sample fields."""
    def g(k):
        v = canon.get(k, [None, None])
        return v[column] if column < len(v) else None

    salt = g("salt")
    sodium_mg = round(salt * 400) if _num(salt) else None  # 1 g salt = 400 mg sodium
    return {
        "dietary_energy_kcal": g("energy_kcal"),
        "protein_g": g("protein"),
        "carbs_g": g("carbs"),
        "fat_g": g("fat"),
        "saturated_fat_g": g("saturates"),
        "fiber_g": g("fibre"),
        "sugar_g": g("sugars"),
        "sodium_mg": sodium_mg,
    }


def _f(v, unit=""):
    return f"{v:g}{unit}" if _num(v) else "—"


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


def scale_to_grams(canon: dict, grams: float) -> dict:
    """Scale per-100g values to an arbitrary gram amount (exact)."""
    factor = grams / 100.0

    def s(k):
        v = canon.get(k, [None, None])[0]
        return round(v * factor, 1) if _num(v) else None

    salt = canon.get("salt", [None])[0]
    sodium = round(salt * factor * 400) if _num(salt) else None
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


def format_reply(result: dict) -> str:
    """Show per-100g and per-pack bases, then ask for the gram amount."""
    hk = result.get("healthkit", {})       # per pack
    canon = result.get("table", {})
    e100 = canon.get("energy_kcal", [None])[0]
    p100 = canon.get("protein", [None])[0]
    c100 = canon.get("carbs", [None])[0]
    f100 = canon.get("fat", [None])[0]

    lines = [
        "🥗 营养表解析（qwen3.7-plus）",
        f"每100g：🔥{_f(e100)}kcal　🥩{_f(p100)}　🍞{_f(c100)}　🧈{_f(f100)}",
        f"整份pack：🔥{_f(hk.get('dietary_energy_kcal'))}kcal　🥩{_f(hk.get('protein_g'))}　🍞{_f(hk.get('carbs_g'))}　🧈{_f(hk.get('fat_g'))}",
    ]
    if result.get("warnings"):
        lines.append("⚠️ " + "；".join(result["warnings"]))
    lines.append("\n👉 吃了多少克？回数字（如 150），或回「整份」。")
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


def format_scaled_pack(hk: dict) -> str:
    """Final nutrition when the user chooses the whole pack, with a HealthKit link."""
    return "\n".join([
        "✅ 记整份（per pack）：",
        f"🔥 {_f(hk.get('dietary_energy_kcal'))} kcal",
        f"🥩 蛋白 {_f(hk.get('protein_g'),'g')}　🍞 碳水 {_f(hk.get('carbs_g'),'g')}　🧈 脂肪 {_f(hk.get('fat_g'),'g')}",
        f"🌾 纤维 {_f(hk.get('fiber_g'),'g')}　🍬 糖 {_f(hk.get('sugar_g'),'g')}　🧂 钠 {_f(hk.get('sodium_mg'),'mg')}",
        f"\n🍎 点这里写入健康：\n{healthkit_link(hk)}",
    ])


async def parse_nutrition_label(image_b64: str, column: str = "pack") -> dict:
    """Full chain: downscale -> VL extract -> Python validate -> HealthKit map."""
    small = _downscale(image_b64)
    raw = await vision_call(
        _EXTRACT_SYSTEM,
        "Extract this UK nutrition label faithfully as JSON (both columns, every row).",
        small,
        model=VISION_MODEL,
    )
    table = extract_json(raw)
    canon = to_canonical(table)
    check = validate(canon)
    col = 1 if column == "pack" else 0
    return {
        "columns": table.get("columns"),
        "table": canon,
        "serving_ratio": check["serving_ratio"],
        "warnings": check["warnings"],
        "healthkit": to_healthkit(canon, column=col),
    }
