#!/usr/bin/env python3
"""Run parse_nutrition_label on several images, robustly."""
import asyncio
import base64
import json
import sys
import time
import traceback

sys.path.insert(0, "/opt/health-bot")
from dotenv import load_dotenv
load_dotenv("/opt/health-bot/.env")

from llm import nutrition


async def one(path):
    print(f"\n{'='*60}\n{path}\n{'='*60}")
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    t0 = time.time()
    try:
        res = await nutrition.parse_nutrition_label(b64, column="pack")
        print(f"[{time.time()-t0:.1f}s]")
        print("CANONICAL:", json.dumps(res["table"], ensure_ascii=False))
        print("RATIO:", res["serving_ratio"])
        print("WARNINGS:", res["warnings"])
        print("HEALTHKIT:", json.dumps(res["healthkit"], ensure_ascii=False))
        print("\n--- reply ---\n" + nutrition.format_reply(res))
    except Exception:
        print(f"[{time.time()-t0:.1f}s] FAILED")
        traceback.print_exc()


async def main():
    for p in sys.argv[1:]:
        await one(p)


asyncio.run(main())
