#!/usr/bin/env python3
"""Run the full nutrition pipeline on an image and print result + token cost."""
import asyncio
import base64
import json
import sys
import time

sys.path.insert(0, "/opt/health-bot")
from dotenv import load_dotenv
load_dotenv("/opt/health-bot/.env")

from llm import nutrition
from llm.client import get_client


async def main():
    img = sys.argv[1]
    b64 = base64.b64encode(open(img, "rb").read()).decode()

    # measure token usage of the (downscaled) vision call directly
    small = nutrition._downscale(b64)
    client = get_client()
    t0 = time.time()
    resp = await client.chat.completions.create(
        model=nutrition.VISION_MODEL,
        messages=[
            {"role": "system", "content": nutrition._EXTRACT_SYSTEM},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{small}"}},
                {"type": "text", "text": "Extract this UK nutrition label faithfully as JSON (both columns, every row)."},
            ]},
        ],
        temperature=0.1,
    )
    dt = time.time() - t0
    u = resp.usage
    # qwen3.7-plus high tier: $0.96/M in, $3.84/M out
    cost = (u.prompt_tokens * 0.96 + u.completion_tokens * 3.84) / 1e6
    print(f"[downscaled image | {dt:.1f}s | in {u.prompt_tokens} / out {u.completion_tokens} tok | ~${cost:.5f} ≈ ¥{cost*7.2:.3f}]\n")

    # full pipeline (does its own vision call)
    res = await nutrition.parse_nutrition_label(b64, column="pack")
    print(json.dumps(res, ensure_ascii=False, indent=2))


asyncio.run(main())
