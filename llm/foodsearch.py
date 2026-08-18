"""Two ways to turn a food into nutrition data:

1. lookup_barcode()  — scan a barcode → Open Food Facts → per-100g facts.
   (OFF terms: 1 API call = 1 real scan; we send a User-Agent as they ask.)
2. estimate_food_text() — free-text description → Qwen itemises it →
   per-item nutrition, summed here into the portion's total.

Both return data in the canonical shapes used by llm.nutrition so the rest of
the pipeline (scale to grams, HealthKit link, formatting) is shared.
"""
import logging
import os
import re

import httpx

from .client import text_call, extract_json

logger = logging.getLogger(__name__)

# OFF asks apps to identify themselves so they can reach out if needed. Set a
# contact in .env (OFF_USER_AGENT) to include an email; default stays impersonal.
_OFF_UA = os.getenv("OFF_USER_AGENT", "DietControlBot/1.0 (+https://github.com/LukeW1999/Diet_control_bot)")
_OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
_OFF_FIELDS = "product_name,product_name_en,brands,serving_size,serving_quantity,nutriments"


def _n(v):
    """OFF numbers arrive as float or numeric string; normalise to float/None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"-?\d+(?:\.\d+)?", v.replace(",", ""))
        if m:
            try:
                return float(m.group())
            except ValueError:
                return None
    return None


def _off_canon(nutriments: dict) -> dict:
    """Map OFF per-100g nutriments to the canonical {key: [per100, None]} shape
    consumed by llm.nutrition.scale_to_grams (which reads the per-100g slot)."""
    g = lambda k: _n(nutriments.get(k))

    kcal = g("energy-kcal_100g")
    if kcal is None:
        kj = g("energy-kj_100g") or g("energy_100g")
        if kj is not None:
            kcal = round(kj / 4.184, 1)  # kJ → kcal fallback

    # salt(g) preferred; else derive from sodium(g): salt = sodium × 2.5
    salt = g("salt_100g")
    if salt is None:
        sod = g("sodium_100g")
        if sod is not None:
            salt = round(sod * 2.5, 3)

    return {
        "energy_kcal": [kcal, None],
        "protein":     [g("proteins_100g"), None],
        "carbs":       [g("carbohydrates_100g"), None],
        "sugars":      [g("sugars_100g"), None],
        "fat":         [g("fat_100g"), None],
        "saturates":   [g("saturated-fat_100g"), None],
        "fibre":       [g("fiber_100g"), None],
        "salt":        [salt, None],
    }


async def lookup_barcode(code: str) -> dict | None:
    """Look up a barcode on Open Food Facts. Returns
    {name, brand, serving_g, canon} or None if the product/nutrition is missing."""
    url = _OFF_URL.format(code=code)
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": _OFF_UA}) as cli:
            r = await cli.get(url, params={"fields": _OFF_FIELDS})
            data = r.json()
    except Exception:
        logger.exception("OFF lookup failed for %s", code)
        return None

    if data.get("status") != 1:
        return None
    p = data.get("product", {}) or {}
    nutriments = p.get("nutriments", {}) or {}
    canon = _off_canon(nutriments)
    if canon["energy_kcal"][0] is None:
        return None  # no usable nutrition on this product

    name = (p.get("product_name_en") or p.get("product_name") or "").strip()
    return {
        "code": code,
        "name": name or f"条码 {code}",
        "brand": (p.get("brands") or "").strip(),
        "serving_g": _n(p.get("serving_quantity")),  # grams per serving, if known
        "serving_size": (p.get("serving_size") or "").strip(),
        "canon": canon,
    }


_ESTIMATE_SYSTEM = """你是营养估算助手。用户用自然语言描述了他吃的食物，可能包含多样食物。
请逐项拆解，对每一项分别估算营养。只返回 JSON，别加解释文字。

返回格式：
{
  "items": [
    {
      "name": "食物名称（简短）",
      "portion": "这一项的份量，如「150g」「1个约50g」",
      "energy_kcal": 数字,
      "protein_g": 数字,
      "carbs_g": 数字,
      "fat_g": 数字,
      "sugar_g": 数字或null,
      "fiber_g": 数字或null,
      "sodium_mg": 数字或null
    }
  ],
  "note": "一句话说明估算依据/不确定性"
}

规则：
- 用户描述里的每一样食物都要单独成为一个 item，不要合并成一项。
- 每一项的数值是「该项这个份量」的合计，已按描述的数量放大，不是每100g。
- 不要自己计算总和，也不要返回 total 字段，合计由程序计算。
- 数字只填数值，别带单位。拿不准的字段填 null。
- 用户没写重量时，在 portion 里写明你假设的克数，并在 note 里说明这是假设。"""


def _sum(items: list[dict], key: str) -> float | None:
    """Sum one nutrient across items, keeping None when no item reported it."""
    present = [v for v in (_n(i.get(key)) for i in items) if v is not None]
    return round(sum(present), 1) if present else None


async def estimate_food_text(description: str) -> dict:
    """Estimate nutrition for a free-text description. The model itemises and the
    totals are summed here: asked for a single flat total it under-counts a
    multi-food meal by about 12%."""
    data = extract_json(await text_call(_ESTIMATE_SYSTEM, description))
    items = [i for i in data.get("items", []) if isinstance(i, dict)]
    return {
        "food": items[0].get("name", "") if len(items) == 1 else f"{len(items)} 项",
        "items": [
            {"name": i.get("name", ""), "portion": i.get("portion", ""),
             "energy_kcal": _n(i.get("energy_kcal"))}
            for i in items
        ],
        "note": data.get("note") or "",
        "dietary_energy_kcal": _sum(items, "energy_kcal"),
        "protein_g": _sum(items, "protein_g"),
        "carbs_g": _sum(items, "carbs_g"),
        "fat_g": _sum(items, "fat_g"),
        "sugar_g": _sum(items, "sugar_g"),
        "fiber_g": _sum(items, "fiber_g"),
        "sodium_mg": _sum(items, "sodium_mg"),
        "saturated_fat_g": None,
    }
