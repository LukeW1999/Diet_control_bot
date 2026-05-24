import os
import json
import re
from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.getenv("QWEN_API_KEY"),
            base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )
    return _client


async def vision_call(system_prompt: str, user_text: str, image_b64: str, model: str = None) -> str:
    client = get_client()
    model = model or os.getenv("QWEN_VISION_MODEL", "qwen-vl-plus")
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    {"type": "text", "text": user_text},
                ],
            },
        ],
        temperature=0.1,
    )
    return response.choices[0].message.content


async def text_call(system_prompt: str, user_text: str, model: str = None) -> str:
    client = get_client()
    model = model or os.getenv("QWEN_TEXT_MODEL", "qwen-plus")
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content


def extract_json(text: str) -> dict | list:
    """Extract JSON from LLM response that may contain markdown fences."""
    text = text.strip()
    # Try to find JSON block in markdown fences
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()
    return json.loads(text)
