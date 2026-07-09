#!/usr/bin/env python3
"""Benchmark Qwen vision models on English nutrition-facts label reading.

Usage:  python nutrition_model_test.py <image1.jpg> [image2.jpg ...]
Reads QWEN_API_KEY from /opt/health-bot/.env
"""
import base64, json, os, sys, time
from pathlib import Path

sys.path.insert(0, "/opt/health-bot")
from dotenv import load_dotenv
load_dotenv("/opt/health-bot/.env")
from openai import OpenAI

MODELS = ["qwen3-vl-plus", "qwen3.7-plus", "qwen-vl-ocr", "qwen-vl-max"]

# price per 1M tokens (input, output) — rough, for relative comparison
PRICE = {
    "qwen3-vl-plus": (0.6, 4.8),
    "qwen3.7-plus":  (0.96, 3.84),
    "qwen-vl-ocr":   (0.07, 0.16),
    "qwen-vl-max":   (0.8, 3.2),
}

SYSTEM = """You are an OCR extraction engine for UK/EU nutrition labels. Read the table
FAITHFULLY and return JSON only — do NOT convert, infer, or normalise anything.
Copy every number exactly as printed. UK labels usually have TWO columns
(e.g. "per 100g" and "per pack/serving"); capture BOTH.

Return this shape:
{
  "columns": ["<header of col 1>", "<header of col 2>"],   // e.g. ["per 100g","per pack"]
  "rows": [
    {"label": "<row name exactly as printed>", "values": [<col1>, <col2>]}
  ],
  "confidence": "high/medium/low"
}

Rules:
- Include EVERY row: Energy (kJ), Energy (kcal), Fat, of which saturates,
  Carbohydrate, of which sugars, Fibre, Protein, Salt, etc.
- Keep kJ and kcal as separate rows.
- If a column has no value for a row, use null.
- Numbers only in "values" (strip units). Preserve decimals exactly.
- Do not add rows that are not on the label."""

client = OpenAI(
    api_key=os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY"),
    base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    timeout=90,
    max_retries=1,
)

def b64(p):
    return base64.b64encode(Path(p).read_bytes()).decode()

def run(model, img_b64):
    t0 = time.time()
    r = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                {"type": "text", "text": "Extract this UK nutrition label faithfully as JSON (both columns, every row)."},
            ]},
        ],
        temperature=0.1,
    )
    dt = time.time() - t0
    u = r.usage
    pin, pout = PRICE.get(model, (0, 0))
    cost = (u.prompt_tokens * pin + u.completion_tokens * pout) / 1_000_000
    return r.choices[0].message.content, dt, u, cost

def main():
    if len(sys.argv) < 2:
        print("usage: nutrition_model_test.py <image ...>"); sys.exit(1)
    for img in sys.argv[1:]:
        print(f"\n{'='*70}\nIMAGE: {img}\n{'='*70}")
        ib = b64(img)
        for m in MODELS:
            print(f"\n----- {m} -----")
            try:
                out, dt, u, cost = run(m, ib)
                print(f"[{dt:.1f}s | in {u.prompt_tokens} / out {u.completion_tokens} tok | ~${cost:.5f}]")
                print(out.strip())
            except Exception as e:
                print(f"ERROR: {e}")

if __name__ == "__main__":
    main()
