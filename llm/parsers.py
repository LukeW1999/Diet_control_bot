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

返回格式：
{
  "date": "YYYY-MM-DD",
  "weight_kg": 数字,
  "bmi": 数字,
  "body_fat_pct": 数字,
  "body_fat_kg": 数字,
  "muscle_mass_kg": 数字,
  "skeletal_muscle_kg": 数字,
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


async def classify_image(image_b64: str) -> str:
    result = await vision_call(_CLASSIFY_PROMPT, "请判断这张图片的类型。", image_b64)
    result = result.strip().lower()
    for t in ("diet", "body", "weight_history", "other"):
        if t in result:
            return t
    return "other"


async def parse_diet_image(image_b64: str) -> dict:
    raw = await vision_call(_DIET_SYSTEM, "请提取这张薄荷健康饮食截图中的所有数据。", image_b64)
    data = extract_json(raw)
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
