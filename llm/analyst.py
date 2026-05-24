import os
from datetime import date, timedelta
from .client import text_call
from utils.food_log import search, get_recent, get_by_date, get_high_calorie_days

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
            return f"日志里没有找到"{keyword}"的记录"
        return f'包含"{keyword}"的记录共{len(entries)}次：\n\n' + "\n\n".join(entries)

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
    if ctx.get("today_diet"):
        d = ctx["today_diet"]
        lines.append(
            f"今日饮食：摄入{d.get('total_calories')}kcal，蛋白质{d.get('protein_g')}g"
        )
    if ctx.get("week_avg_deficit"):
        lines.append(f"本周平均热量缺口：{ctx['week_avg_deficit']:.0f}kcal/天")
    return "\n".join(lines) if lines else "暂无数据"
