from datetime import date as _date

from .client import text_call, extract_json


def _today() -> str:
    return _date.today().isoformat()


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


async def parse_workout_text(text: str) -> tuple[dict, str]:
    raw = await text_call(_WORKOUT_SYSTEM, text)
    data = extract_json(raw)
    return data, raw
