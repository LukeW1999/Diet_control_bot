import os
from datetime import date, timedelta
from .client import text_call
from utils.food_log import search, get_recent, get_by_date, get_high_calorie_days

_NOTE_CLASSIFY_SYSTEM = """用户发来了一段工作或学习内容，请判断分类并提取信息，以JSON返回：
{
  "is_note": true/false,
  "category": "work/study/programming/idea/other",
  "summary": "一句话总结（10字以内）",
  "content": "整理后的笔记内容（保留要点，去掉口语化表达）"
}

分类说明：
- work：工作任务、会议、项目进展
- study：读书、课程、论文、学术内容
- programming：代码、技术、开发相关
- idea：灵感、想法、计划
- other：不属于以上的笔记内容

如果这段文字明显不是笔记（比如问问题、聊天），返回 {"is_note": false}"""

_WEEKLY_NOTES_SYSTEM = """你是一个笔记整理助手。用户给你发来了这周每天的工作和学习笔记，
请帮他整理成一份结构清晰的周报，按以下结构输出：

## 本周工作
（列出主要工作内容）

## 本周学习
（列出学习收获）

## 想法与灵感
（如有）

## 下周计划建议
（根据本周内容，提1-2个建议）

语气简洁，用 bullet point，字数控制在300字以内。"""


async def classify_note(text: str) -> dict | None:
    """Classify user input as a note and extract structured content."""
    if len(text) < 5:
        return None
    raw = await text_call(_NOTE_CLASSIFY_SYSTEM, text)
    try:
        import json, re
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group()) if m else {}
        return data if data.get("is_note") else None
    except Exception:
        return None


async def generate_weekly_notes_summary(notes_text: str) -> str:
    if not notes_text.strip():
        return "这周还没有笔记记录。"
    return await text_call(_WEEKLY_NOTES_SYSTEM, notes_text)


_DIARY_SYSTEM = """用户发来了一段文字，可能是今天的日记或心情记录。
请提取以下信息，以JSON返回，不要返回其他内容：
{
  "is_diary": true/false,
  "mood": "用一个词描述心情，如：好/累/焦虑/开心/一般/烦躁/平静",
  "mood_score": 1-5的整数（1最差，5最好），
  "content": "日记正文（原文保留）"
}

如果这段文字明显不是日记/心情记录（比如问问题、发指令），返回 {"is_diary": false}"""


async def detect_diary(text: str) -> dict | None:
    """Return diary info if text looks like a diary entry, else None."""
    if len(text) < 3:
        return None
    raw = await text_call(_DIARY_SYSTEM, text)
    try:
        import json, re
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group()) if m else {}
        return data if data.get("is_diary") else None
    except Exception:
        return None


_CORRECT_SYSTEM = """你是一个数据纠错助手。用户想修正他的健康记录中某个字段的值。

已知字段映射（中文 → 数据库字段名）：
体重 → weight_kg
体脂率 → body_fat_pct
骨骼肌量 → skeletal_muscle_kg
内脏脂肪 → visceral_fat_level
基础代谢 → bmr_kcal
BMI → bmi
健康评分 → health_score
体年龄 → body_age
脂肪量 → body_fat_kg
皮下脂肪 → subcutaneous_fat_kg
去脂体重 → fat_free_mass_kg
蛋白质摄入 → protein_g
碳水 → carbs_g
脂肪摄入 → fat_g
总热量 → total_calories

根据用户的话，返回JSON，不要返回其他内容：
{
  "table": "body 或 diet",
  "field": "数据库字段名",
  "value": 数字,
  "date": "YYYY-MM-DD 或 today"
}

如果无法识别意图，返回 {"error": "无法识别"}"""


async def detect_correction(text: str) -> dict | None:
    """Return correction intent {table, field, value, date} or None."""
    correction_hints = ["错了", "应该是", "不是", "纠正", "修改", "改成", "改为", "应该"]
    if not any(h in text for h in correction_hints):
        return None
    today_str = date.today().isoformat()
    raw = await text_call(
        _CORRECT_SYSTEM,
        f"今天是{today_str}。用户说：{text}"
    )
    try:
        import json, re
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group()) if m else {}
        if "error" in data or "field" not in data:
            return None
        if data.get("date") == "today":
            data["date"] = today_str
        return data
    except Exception:
        return None

_WEEKLY_SYSTEM = """你是用户的减脂健康顾问。用户正在进行减脂计划，目标是从 91.8kg 减到 74.8kg，
同时保留肌肉。用户的基础代谢是 1916 kcal，蛋白质目标是体重×1.8g/kg。

你会收到用户过去一周的数据，请生成一份简洁有用的周报。
要求：
1. 先用数据说话，再给建议
2. 语气像朋友，不要说教
3. 如果数据不完整，基于已有数据分析，不要假设缺失数据
4. 重点关注：热量缺口是否达标、蛋白质是否足够、肌肉量是否稳定
5. 字数控制在 300 字以内"""

_QA_SYSTEM = """你是用户的健康数据助手。用户会问你关于他的减脂、饮食、训练数据的问题。
请根据提供的数据上下文回答，语气简洁友好。如果数据里没有相关信息就如实说。"""


async def generate_weekly_report(user_data: dict) -> str:
    content = _format_weekly_data(user_data)
    return await text_call(_WEEKLY_SYSTEM, content)


async def answer_question(question: str, context: dict) -> str:
    food_context = await _grep_skill(question)
    context_str = _format_context(context)
    full_context = context_str
    if food_context:
        full_context += f"\n\n饮食历史记录：\n{food_context}"
    return await text_call(_QA_SYSTEM, f"用户数据：\n{full_context}\n\n用户问题：{question}")


_GREP_SKILL_PROMPT = f"""今天是 {date.today()}。你是一个食物日志搜索助手。

食物日志每天一条，格式：
[YYYY-MM-DD] 总摄入:Xkcal 蛋白质:Xg 碳水:Xg 脂肪:Xg
  早餐(Xkcal): 食物1数量, 食物2数量...
  午餐/晚餐/运动...

根据用户问题，决定如何搜索日志。只返回以下之一，不要返回其他内容：

- 如果问某一天（今天/昨天/前天/具体日期）→ 返回 DATE:YYYY-MM-DD
- 如果问最近/本周/这几天 → 返回 RECENT:7
- 如果问上周/最近两周 → 返回 RECENT:14
- 如果问放纵餐/高热量/超标/作弊 → 返回 HIGH_CALORIE:2200
- 如果问某种食物（频率/次数/有没有吃过）→ 返回 SEARCH:食物名
- 如果问题与饮食历史无关 → 返回 NONE"""


async def _grep_skill(question: str) -> str:
    """Ask Qwen what to grep, then execute the search."""
    instruction = await text_call(_GREP_SKILL_PROMPT, question)
    instruction = instruction.strip()

    if instruction.startswith("DATE:"):
        d = instruction[5:].strip()
        try:
            from datetime import date as date_cls
            entry = get_by_date(date_cls.fromisoformat(d))
            return entry or f"{d} 无记录"
        except ValueError:
            return ""

    if instruction.startswith("RECENT:"):
        days = int(instruction[7:].strip())
        entries = get_recent(days)
        return "\n\n".join(entries) if entries else f"最近{days}天无记录"

    if instruction.startswith("HIGH_CALORIE:"):
        threshold = int(instruction[13:].strip())
        entries = get_high_calorie_days(threshold)
        if not entries:
            return f"没有找到高热量天（>{threshold}kcal）"
        return f"高热量天共{len(entries)}次：\n\n" + "\n\n".join(entries[-10:])

    if instruction.startswith("SEARCH:"):
        keyword = instruction[7:].strip()
        entries = search(keyword)
        if not entries:
            return f"日志里没有找到「{keyword}」的记录"
        return f"包含「{keyword}」的记录共{len(entries)}次：\n\n" + "\n\n".join(entries)

    # NONE or unrecognized
    entries = get_recent(3)
    return "\n\n".join(entries) if entries else ""


def _format_weekly_data(data: dict) -> str:
    lines = ["本周数据汇总：\n"]

    diets = data.get("diet_records", [])
    if diets:
        lines.append("== 饮食记录 ==")
        for d in diets:
            deficit = d.get("calorie_deficit", 0)
            lines.append(
                f"{d['date']}: 摄入{d.get('total_calories', 0):.0f}kcal, "
                f"蛋白质{d.get('protein_g', 0):.0f}g/{d.get('protein_goal_g', 0):.0f}g, "
                f"热量缺口{deficit:.0f}kcal"
            )

    bodies = data.get("body_records", [])
    if bodies:
        lines.append("\n== 身体成分 ==")
        for b in bodies:
            lines.append(
                f"{b['date']}: 体重{b.get('weight_kg', '?')}kg, "
                f"体脂{b.get('body_fat_pct', '?')}%, "
                f"肌肉{b.get('muscle_mass_kg', '?')}kg"
            )

    workouts = data.get("workout_records", [])
    if workouts:
        lines.append(f"\n== 训练 ==\n共训练 {len(workouts)} 次")

    return "\n".join(lines)


def _format_context(ctx: dict) -> str:
    lines = []
    if ctx.get("latest_body"):
        b = ctx["latest_body"]
        lines.append(
            f"最新体重：{b.get('weight_kg')}kg，体脂率：{b.get('body_fat_pct')}%，"
            f"肌肉量：{b.get('muscle_mass_kg')}kg（{b.get('date')}）"
        )
    if ctx.get("body_history"):
        history = ctx["body_history"]
        if len(history) >= 2:
            lines.append("\n近期体重/体成分记录：")
            for r in history:
                parts = []
                if r.get("weight_kg"):
                    parts.append(f"体重{r['weight_kg']}kg")
                if r.get("body_fat_pct"):
                    parts.append(f"体脂{r['body_fat_pct']}%")
                if r.get("skeletal_muscle_kg"):
                    parts.append(f"骨骼肌{r['skeletal_muscle_kg']}kg")
                lines.append(f"  {r['date']}: {', '.join(parts)}")
    if ctx.get("today_diet"):
        d = ctx["today_diet"]
        lines.append(
            f"今日饮食：摄入{d.get('total_calories')}kcal，蛋白质{d.get('protein_g')}g"
        )
    if ctx.get("week_avg_deficit"):
        lines.append(f"本周平均热量缺口：{ctx['week_avg_deficit']:.0f}kcal/天")
    return "\n".join(lines) if lines else "暂无数据"
