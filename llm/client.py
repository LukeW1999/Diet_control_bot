import logging
import os
import json
import re
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )
    return _client


async def text_call(
    system_prompt: str,
    user_text: str,
    model: str = None,
    history: list[dict] | None = None,
    thinking: bool = False,
    search: bool = False,
) -> str:
    client = get_client()
    model = model or os.getenv("QWEN_TEXT_MODEL", "qwen3.6-plus")

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    extra: dict = {"enable_thinking": bool(thinking)}
    if search:
        extra["enable_search"] = True  # DashScope web search for grounded answers
    kwargs: dict = dict(model=model, messages=messages, extra_body=extra)
    kwargs["temperature"] = 1.0 if thinking else 0.7

    logger.debug("[LLM] model=%s thinking=%s prompt_head=%.80s", model, thinking, user_text)

    response = await client.chat.completions.create(**kwargs)
    msg = response.choices[0].message

    reasoning = getattr(msg, "reasoning_content", None)
    if reasoning:
        logger.info("[THINKING %.60s] %s", user_text, reasoning[:300])

    answer = msg.content or ""
    logger.debug("[LLM reply] %.120s", answer)
    return answer


def extract_json(text: str) -> dict | list:
    """Extract JSON from LLM response that may contain markdown fences."""
    text = text.strip()
    # Try to find JSON block in markdown fences
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()
    return json.loads(text)
