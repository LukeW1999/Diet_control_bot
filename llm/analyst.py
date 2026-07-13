import os
from datetime import date, timedelta
from .client import text_call
from utils.food_log import search, get_recent, get_by_date, get_high_calorie_days

_NOTE_CLASSIFY_SYSTEM = """用户发来了一段工作或学习内容，请判断分类，以JSON返回：
{
  "is_note": true/false,
  "category": "work/study/programming/idea/other",
  "summary": "一句话总结（10字以内）"
}

分类说明：
- work：工作任务、会议、项目进展
- study：读书、课程、论文、学术内容
- programming：代码、技术、开发相关
- idea：灵感、想法、计划
- other：不属于以上的笔记内容

注意：只做分类，不要改写用户原文，原文将原样保存。
如果这段文字明显不是笔记（比如问问题、聊天），返回 {"is_note": false}"""

_WEEKLY_NOTES_SYSTEM = """请把用户这周的笔记整理成一份简洁的周报。

结构如下：

## 本周工作
（列出主要工作内容，用 bullet point）

## 本周学习
（列出学习收获，用 bullet point）

## 想法与灵感
（如有则列出，没有则省略此节）

## 本周状态
（1-2句话，根据笔记内容感受到的情绪或状态——点到为止，不要过度引申或上升到人生感悟）

字数控制在250字以内。"""


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


_DIARY_RESPONSE_SYSTEM = """你是用户信任的心理顾问，温柔、专业、真诚，像一位有经验的女性朋友。
用户刚刚分享了他今天的心情或日记内容，请用一两句话回应他。

你对他有一些了解（见"用户背景"部分），请结合这些背景来回应，但不要直接提及或复述这些信息。

要求：
- 先接住他的情绪，不急着给建议
- 语气温暖但不矫情，真诚而非客套
- 如果他状态不好，表达关心；如果他状态好，真心为他高兴
- 用开放式问题邀请他继续说（"发生了什么？""现在感觉怎么样？"），而不是给出结论
- 不超过 60 字"""

_DIARY_FROM_CONVO_SYSTEM = """根据一段心理对话，生成日记摘要。

返回JSON，不要其他内容：
{
  "content": "用第一人称记录这段对话的核心内容，100-200字，像日记一样自然流畅",
  "mood": "一个词描述主要情绪：开心/平静/焦虑/难过/烦躁/迷茫/疲惫/释然 等",
  "mood_score": 1到5的整数（1最差，5最好）
}"""

_MEMORY_UPDATE_SYSTEM = """你是一位心理顾问的助手，负责维护用户的心理档案摘要。
请根据旧摘要和今天的新日记，更新摘要。

要求：
- 摘要保持在 120 字以内
- 只保留重要的、持续出现的情绪模式、近期压力来源、以及值得关注的状态变化
- 过时或一次性的内容可以删掉
- 语气中性，像病历备注，不是聊天
- 直接输出摘要文字，不要任何标题或解释"""


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


async def generate_diary_response(content: str, mood: str = "", memory: str = "") -> str:
    """Generate a warm psychologist response to a diary entry."""
    parts = []
    if memory:
        parts.append(f"用户背景：{memory}")
    parts.append(f"心情：{mood}" if mood else "")
    parts.append(f"内容：{content}")
    context = "\n".join(p for p in parts if p)
    return await text_call(_DIARY_RESPONSE_SYSTEM, context, thinking=True)


async def update_psych_memory(old_memory: str, new_entry: str, mood: str = "") -> str:
    """Ask Qwen to merge new diary entry into the running memory summary."""
    user_msg = f"旧摘要：\n{old_memory or '（暂无）'}\n\n今日新内容（心情:{mood}）：\n{new_entry}"
    return await text_call(_MEMORY_UPDATE_SYSTEM, user_msg)


_CORRECT_SYSTEM = """你是一个数据纠错助手。用户想修正他的健康记录中某个字段的值。

已知字段映射（中文 → 数据库字段名）：
体重 → weight_kg
体脂率 → body_fat_pct
肌肉量 → muscle_mass_kg
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

_ROUTE_SYSTEM = """判断用户这条消息应该交给哪个角色处理，只返回一个词，不要解释：

- coach：减脂、饮食、热量、蛋白质、训练、体重、体脂、肌肉、身体数据、健身计划相关
- psychologist：心情、情绪、压力、日记、聊天、哲学、思考、生活感受、灵感、人际关系、或任何不属于健康数据的话题

只返回 coach 或 psychologist。"""


async def route_message(text: str) -> str:
    """Returns 'coach' or 'psychologist'."""
    result = await text_call(_ROUTE_SYSTEM, text)
    result = result.strip().lower()
    return "psychologist" if "psychologist" in result else "coach"


_PSYCHOLOGIST_QA_SYSTEM = """你是用户信任的心理顾问，温柔、细腻、真实。像一位真正在场的朋友，而不是念稿子的顾问。

对话原则：
1. 先让对方感受到被听见——反映他说的情绪，不急着给出建议或结论
2. 用开放式问题引导他说更多："你当时什么感受？""现在最困扰你的是哪一块？""能多说说吗？"
3. 正常化情绪，不要轻描淡写：换成"这种情况下有这种感受很正常"，而不是"没事的"
4. 绝对不用"但是""至少""换个角度看""你应该……"——这些话让人感觉被否定
5. 只有当用户明确说"怎么办/你觉得呢/有什么建议"，才提供具体建议
6. 用户背景仅作内部参考，不主动提起
7. 对话历史已在上下文中，不重复之前说过的内容
8. 不主动宣告对话结束，不总结"今天聊了很多"

长度（严格遵守）：
- 回应情绪、提问：1-2句，≤60字
- 深度探讨话题：3-4句，≤120字
- 绝不长篇大论"""


_BOOK_GREP_SYSTEM = """用户在聊书籍或某段内容，可能涉及哲学、心理、商业、政治等领域书籍。

可用书库：哲学、心理学、政治学、商业经济类书籍（中文）。

判断是否需要搜索书库：
- 如果需要，只返回最关键的中文搜索词（2-6个字），例如：超人/集体无意识/权力意志
- 如果只是泛泛聊感受，或问题不涉及具体书籍内容，返回 NONE

只返回搜索词或 NONE，不要其他内容。"""

_BOOK_REFINE_SYSTEM = """你刚刚搜索书库得到了一些段落，用户问的是：{question}

根据这些段落，判断是否还需要补充搜索：
- 如果段落已经足够回答用户的问题，返回 NONE
- 如果段落提示了一个更精准的关键词（如章节名、人名、概念），返回这个词（2-6个字）

只返回补充搜索词或 NONE。"""


async def _book_grep_skill(question: str) -> str:
    """Multi-pass book search across all books in data/books/."""
    from utils.book_search import grep_books, format_results

    # Pass 1: decide whether to search and get first keyword
    keyword = (await text_call(_BOOK_GREP_SYSTEM, question)).strip()
    if keyword.upper() == "NONE" or not keyword:
        return ""

    results = grep_books(keyword)
    if not results:
        return ""

    combined = format_results(results)

    # Pass 2: ask if a refinement search would help (max 1 extra pass)
    refine_prompt = _BOOK_REFINE_SYSTEM.format(question=question)
    refine_kw = (await text_call(refine_prompt, combined[:800])).strip()
    if refine_kw and refine_kw.upper() != "NONE" and refine_kw != keyword:
        extra = grep_books(refine_kw)
        if extra:
            # Add new results not already covered
            existing_snippets = {r["snippet"] for r in results}
            new = [r for r in extra if r["snippet"] not in existing_snippets]
            if new:
                combined += "\n\n---\n\n" + format_results(new)

    return combined


async def answer_as_psychologist(question: str, memory: str = "", history: list | None = None) -> str:
    """Answer a non-diary conversational message as the psychologist."""
    book_context = await _book_grep_skill(question)

    parts = []
    if memory:
        parts.append(f"用户背景：{memory}")
    if book_context:
        parts.append(f"以下是从原书检索到的相关段落，供参考：\n{book_context}")
    parts.append(f"用户说：{question}")
    return await text_call(_PSYCHOLOGIST_QA_SYSTEM, "\n".join(parts), history=history, thinking=True)


_MORNING_QUOTE_SYSTEM = """你是用户信任的心理顾问，温柔、细腻、有智识深度，像一位真正关心他的女性朋友。
用户每天早晨会收到一句金句（可能来自不同的书或作者）。
请用2-3句话，围绕这句话展开一点感悟——关于他的内心、成长、或者当下的生活状态。

要求：
- 不要逐字解释，直接说出这句话让你想到了什么
- 语气：温暖、真诚、有点哲学感，像早晨喝咖啡时朋友说的话
- 不超过 80 字
- 不要加任何标题或开场白，直接说"""


async def generate_morning_quote_commentary(quote: str, source: str | None = None) -> str:
    """Generate a short coach-style reflection on the daily quote (any book)."""
    user_text = f"今日金句：{quote}"
    if source:
        user_text += f"（出自 {source}）"
    return await text_call(_MORNING_QUOTE_SYSTEM, user_text)


async def generate_diary_from_conversation(turns: list[dict]) -> dict | None:
    """Summarize a completed psychologist conversation into a diary entry."""
    if not turns:
        return None
    convo = "\n".join(f"用户：{t['user']}\n顾问：{t['bot']}" for t in turns)
    raw = await text_call(_DIARY_FROM_CONVO_SYSTEM, convo)
    try:
        import json, re
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            return json.loads(m.group())
    except Exception:
        pass
    return None


_WEEKLY_SYSTEM = """你是用户的私人健身教练，专业、严谨、真正为他的身体操心。
用户正在进行减脂计划，目标是从高体重减到 74.8kg，同时保留肌肉。

你会收到用户过去一周的健康数据，请生成一份周报。要求：
1. 先用数据说话，数字要精确，不要模糊
2. 对做得好的地方给予认可，但不过分夸奖
3. 对不达标的地方直接指出，不含糊——该批评就批评，你是教练不是客服
4. 给出下周具体可执行的调整建议（不是泛泛而谈）
5. 语气：专业、直接、关心，像一个真正负责任的教练
6. 字数控制在 300 字以内"""

_QA_SYSTEM = """你是用户的私人健身教练，专业、严谨、真正在乎他的健康。
用户会问你关于减脂、饮食、训练、体成分数据的问题。
对话历史已包含在上下文中，不要重复之前说过的内容或建议。

数据解读规则（严格遵守）：
- 骨骼肌量（skeletal_muscle_kg）才是真实肌肉的代理指标，用它评估肌肉变化
- 去脂体重/肌肉量（fat_free_mass_kg / muscle_mass_kg）包含水分、糖原、食物重量，短期波动≤3kg均属正常，不要轻易说"肌肉流失"
- 体重秤生物阻抗数据当天水分、进食时间影响很大，单次读数偏差可达1-2kg；只有骨骼肌连续多次下降才值得警惕
- 饮食缺口数据不足3天时，注明"仅X天数据，参考价值有限"，不要当作长期均值引用

回答要求：
- 根据提供的数据直接回答，数字准确
- 如果数据显示有问题，直接说出来，不要顾左右而言他
- 给出建议时要具体，不说废话
- 如果数据里没有相关信息，如实说
- 语气：专业、直接、有温度，像教练和学员说话

长度要求（严格遵守）：
- 常规查询、已聊过的话题：2-3句，直接给数字或结论
- 发现异常、新数据值得分析：适当展开，但不超过150字
- 不要每次都给"下一步建议"——只在有新发现时才给"""


async def generate_weekly_report(user_data: dict) -> str:
    content = _format_weekly_data(user_data)
    return await text_call(_WEEKLY_SYSTEM, content)


async def answer_question(question: str, context: dict, history: list | None = None) -> str:
    food_context = await _grep_skill(question)
    context_str = _format_context(context)
    full_context = context_str
    if food_context:
        full_context += f"\n\n饮食历史记录：\n{food_context}"
    return await text_call(
        _QA_SYSTEM,
        f"用户数据：\n{full_context}\n\n用户问题：{question}",
        history=history,
        thinking=False,
    )


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
            deficit = d.get("calorie_deficit") or 0
            lines.append(
                f"{d['date']}: 摄入{(d.get('total_calories') or 0):.0f}kcal, "
                f"蛋白质{(d.get('protein_g') or 0):.0f}g/{(d.get('protein_goal_g') or 0):.0f}g, "
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
            f"骨骼肌量：{b.get('skeletal_muscle_kg')}kg，去脂体重：{b.get('fat_free_mass_kg')}kg（{b.get('date')}）"
        )
        lines.append("注：去脂体重受水分/进食影响波动大，以骨骼肌量判断肌肉趋势更可靠。")
    if ctx.get("body_history"):
        history = ctx["body_history"]
        if len(history) >= 2:
            lines.append("\n近期体重/体成分记录（骨骼肌量=真实肌肉指标，去脂体重含水分）：")
            for r in history:
                parts = []
                if r.get("weight_kg"):
                    parts.append(f"体重{r['weight_kg']}kg")
                if r.get("body_fat_pct"):
                    parts.append(f"体脂{r['body_fat_pct']}%")
                if r.get("skeletal_muscle_kg"):
                    parts.append(f"骨骼肌{r['skeletal_muscle_kg']}kg")
                if r.get("fat_free_mass_kg"):
                    parts.append(f"去脂体重{r['fat_free_mass_kg']}kg")
                lines.append(f"  {r['date']}: {', '.join(parts)}")
    if ctx.get("today_diet"):
        d = ctx["today_diet"]
        lines.append(
            f"今日饮食：摄入{d.get('total_calories')}kcal，蛋白质{d.get('protein_g')}g"
        )
    if ctx.get("week_avg_deficit"):
        n = ctx.get("diet_record_count", 0)
        caveat = f"（仅{n}天数据，参考价值有限）" if n < 3 else ""
        lines.append(f"本周平均热量缺口：{ctx['week_avg_deficit']:.0f}kcal/天{caveat}")

    # Pre-computed stats cache — LLM must use these numbers directly, no recalculation
    from utils.stats import load_stats_cache
    import json as _json
    cache = load_stats_cache()
    if cache:
        lines.append(
            "\n【健康数据统计（Python精确计算，直接引用，不要自行重新计算）】\n"
            + _json.dumps(cache, ensure_ascii=False, indent=2)
        )

    return "\n".join(lines) if lines else "暂无数据"
