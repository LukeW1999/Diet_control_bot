"""Two ways to turn a food into nutrition data:

1. lookup_barcode()  — scan a barcode → Open Food Facts → per-100g facts.
   (OFF terms: 1 API call = 1 real scan; we send a User-Agent as they ask.)
2. estimate_food_text() — free-text description → Qwen with web search →
   estimated total nutrition for the portion described.

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


_ESTIMATE_SYSTEM = """你是营养估算助手。用户用自然语言描述了他吃的食物（通常已含数量或份量）。
请结合联网搜索，估算「用户描述的这一份」的**总**营养（不是每100g）。只返回 JSON，别加解释文字。

返回格式：
{
  "food": "食物名称（简短）",
  "assumed_portion": "你假设的份量，如「1个巨无霸约219g」",
  "energy_kcal": 数字,
  "protein_g": 数字,
  "carbs_g": 数字,
  "fat_g": 数字,
  "sugar_g": 数字或null,
  "fiber_g": 数字或null,
  "sodium_mg": 数字或null,
  "note": "一句话说明估算依据/不确定性"
}

规则：
- 所有营养值是「用户这一份」的合计，已按描述的数量放大。
- 数字只填数值，别带单位。拿不准的字段填 null。
- 找不到确切数据时，用同类食物的常见值估，并在 note 里说明。"""


async def estimate_food_text(description: str) -> dict:
    """Estimate total nutrition for a free-text food description via Qwen + web search."""
    raw = await text_call(_ESTIMATE_SYSTEM, description, search=True)
    data = extract_json(raw)
    # Normalise to the HealthKit dict shape used by nutrition.healthkit_link/format.
    return {
        "food": data.get("food") or description[:40],
        "assumed_portion": data.get("assumed_portion") or "",
        "note": data.get("note") or "",
        "dietary_energy_kcal": _n(data.get("energy_kcal")),
        "protein_g": _n(data.get("protein_g")),
        "carbs_g": _n(data.get("carbs_g")),
        "fat_g": _n(data.get("fat_g")),
        "sugar_g": _n(data.get("sugar_g")),
        "fiber_g": _n(data.get("fiber_g")),
        "sodium_mg": _n(data.get("sodium_mg")),
        "saturated_fat_g": None,
    }
