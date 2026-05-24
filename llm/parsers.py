from .client import vision_call, text_call, extract_json

_CLASSIFY_PROMPT = """你是一个图片类型分类助手。请判断这张截图属于哪一类：
1. diet - 薄荷健康饮食记录（包含食物列表和热量）
2. body - 身体成分报告（包含体重、体脂率、肌肉量等指标）
3. weight_history - 体重历史记录列表（多天体重数据）
4. other - 其他

只返回类型代码，不要返回其他内容。"""

_DIET_SYSTEM = """你是一个营养数据提取助手。用户会发给你薄荷健康App的饮食记录截图。
薄荷截图顶部有当日汇总（总摄入热量、运动消耗、超出预算数值、碳水/蛋白质/脂肪克数），
下方按早餐/午餐/晚餐/加餐分组列出每个食物的名称、数量和热量。

请提取全部数据，以JSON格式返回，不要返回任何其他内容。

返回格式：
{
  "date": "YYYY-MM-DD",
  "summary": {
    "total_calories": 数字,
    "exercise_calories": 数字,
    "budget_calories": 数字,
    "over_budget": 数字（超出为正，缺口为负）,
    "carbs_g": 数字,
    "carbs_goal_g": 数字,
    "protein_g": 数字,
    "protein_goal_g": 数字,
    "fat_g": 数字,
    "fat_goal_g": 数字
  },
  "meals": [
    {
      "meal_type": "breakfast/lunch/dinner/snack",
      "total_calories": 数字,
      "foods": [
        {
          "name": "食物名称",
          "amount": "数量（含单位，如200克、2只、500毫升）",
          "calories": 数字
        }
      ]
    }
  ],
  "exercise": [
    {
      "name": "运动名称",
      "calories_burned": 数字,
      "source": "来源（如Apple Health）"
    }
  ],
  "confidence": "high/medium/low"
}"""

_BODY_SYSTEM = """你是一个身体成分数据提取助手。用户会发给你体重秤App的身体成分报告截图。
请提取所有可见的数据，以JSON格式返回，不要返回任何其他内容。

字段说明（重要）：
- body_fat_pct：取标注为「体脂率」的值（通常20-35%），不是「脂肪率」也不是其他脂肪百分比
- body_fat_kg：取「脂肪量」或「体脂量」（单位kg）
- muscle_mass_kg：取标注为「骨骼肌量」的值（单位kg），不是「肌肉量」
- skeletal_muscle_kg：同上，取「骨骼肌量」

返回格式：
{
  "date": "YYYY-MM-DD",
  "weight_kg": 数字,
  "bmi": 数字,
  "body_fat_pct": 数字（仅取「体脂率」）,
  "body_fat_kg": 数字（取「脂肪量」kg）,
  "muscle_mass_kg": 数字（取「骨骼肌量」kg）,
  "skeletal_muscle_kg": 数字（取「骨骼肌量」kg）,
  "fat_free_mass_kg": 数字,
  "protein_kg": 数字,
  "water_kg": 数字,
  "bone_mass_kg": 数字,
  "subcutaneous_fat_kg": 数字,
  "visceral_fat_level": 整数,
  "bmr_kcal": 数字,
  "body_age": 整数,
  "health_score": 整数,
  "weight_to_lose_kg": 数字或null,
  "fat_to_lose_kg": 数字或null,
  "confidence": "high/medium/low"
}

所有字段如果图片中没有则返回null，不要猜测数据。"""

_WEIGHT_HISTORY_SYSTEM = """你是一个体重数据提取助手。用户会发给你体重历史记录列表截图，可能包含多天数据。
请提取每一条记录，以JSON数组格式返回，不要返回任何其他内容。

返回格式（数组）：
[
  {
    "date": "YYYY-MM-DD",
    "weight_kg": 数字,
    "body_fat_pct": 数字或null,
    "muscle_mass_kg": 数字或null
  }
]

按日期从旧到新排序。如果某条记录缺少数据，对应字段返回null。"""

_WORKOUT_SYSTEM = """你是一个健身数据提取助手。用户用自然语言描述了今天的训练内容，请提取结构化数据，以JSON格式返回。

返回格式：
{
  "date": "YYYY-MM-DD 或 today",
  "workout_type": "strength/cardio/mixed",
  "exercises": [
    {
      "exercise": "动作名称",
      "sets": [
        {"weight": 重量kg, "reps": 次数, "rpe": RPE评分或null}
      ]
    }
  ],
  "cardio": {
    "type": "running/cycling/etc 或 null",
    "duration_min": 分钟数,
    "distance_km": 公里数或null,
    "calories": 热量或null
  },
  "duration_min": 总时长分钟,
  "notes": "其他备注"
}"""


def _normalize_diet(data: dict) -> dict:
    """Normalize LLM diet response to canonical field names."""
    s = data.get("summary", {})

    # over_budget: convert bool or missing to number
    over = s.get("over_budget")
    if isinstance(over, bool) or over is None:
        total = s.get("total_calories") or 0
        exercise = s.get("exercise_calories") or 0
        budget = s.get("budget_calories") or 0
        over = round(total - exercise - budget, 1)
    s["over_budget"] = over

    # Normalize meals
    meals = []
    meal_type_map = {"早餐": "breakfast", "午餐": "lunch", "晚餐": "dinner", "加餐": "snack",
                     "breakfast": "breakfast", "lunch": "lunch", "dinner": "dinner", "snack": "snack"}
    for m in data.get("meals", []):
        meal_type = m.get("meal_type") or m.get("meal_name") or ""
        meal_type = meal_type_map.get(meal_type, meal_type_map.get(meal_type.lower(), "snack"))
        foods = []
        for f in m.get("foods", m.get("items", [])):
            foods.append({
                "name": f.get("name", ""),
                "amount": f.get("amount") or f.get("quantity", ""),
                "calories": f.get("calories", 0),
            })
        meals.append({
            "meal_type": meal_type,
            "total_calories": m.get("total_calories") or m.get("calories", 0),
            "foods": foods,
        })
    data["meals"] = meals

    # Normalize exercise
    exercise_list = []
    for e in data.get("exercise", []):
        exercise_list.append({
            "name": e.get("name") or e.get("activity", ""),
            "calories_burned": e.get("calories_burned") or e.get("calories", 0),
            "source": e.get("source", ""),
        })
    data["exercise"] = exercise_list
    data["summary"] = s
    return data


async def classify_image(image_b64: str) -> str:
    result = await vision_call(_CLASSIFY_PROMPT, "请判断这张图片的类型。", image_b64)
    r = result.strip().lower()
    if any(k in r for k in ("diet", "1", "饮食", "薄荷", "食物", "热量", "早餐", "午餐", "晚餐")):
        return "diet"
    if any(k in r for k in ("body", "2", "身体成分", "体脂", "肌肉", "体重秤", "bmi")):
        return "body"
    if any(k in r for k in ("weight_history", "3", "历史", "记录列表")):
        return "weight_history"
    return "other"


async def parse_diet_image(image_b64: str) -> dict:
    raw = await vision_call(_DIET_SYSTEM, "请提取这张薄荷健康饮食截图中的所有数据。", image_b64)
    data = extract_json(raw)
    data = _normalize_diet(data)
    return data, raw


async def parse_body_composition_image(image_b64: str) -> tuple[dict, str]:
    raw = await vision_call(_BODY_SYSTEM, "请提取这张身体成分报告截图中的所有数据。", image_b64)
    data = extract_json(raw)
    return data, raw


async def parse_weight_history_image(image_b64: str) -> tuple[list, str]:
    raw = await vision_call(_WEIGHT_HISTORY_SYSTEM, "请提取所有体重记录数据。", image_b64)
    data = extract_json(raw)
    return data, raw


async def parse_workout_text(text: str) -> tuple[dict, str]:
    raw = await text_call(_WORKOUT_SYSTEM, text)
    data = extract_json(raw)
    return data, raw
