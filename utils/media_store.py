"""Timestamped media storage for images and documents.

All files land in data/media/ with names like 20260603_143022_diet.jpg
so Hermes can scan and read them chronologically.
"""
import base64
import io
import os
from datetime import datetime
from pathlib import Path

from PIL import Image

_MEDIA_DIR = Path(__file__).parent.parent / "data" / "media"
_MAX_DIM = 1200
_QUALITY = 85


def _ensure() -> Path:
    _MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return _MEDIA_DIR


def save_image(image_bytes: bytes, category: str) -> tuple[str, str]:
    """Save image to data/media/ with timestamp. Returns (path, base64)."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = _ensure() / f"{ts}_{category}.jpg"

    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size
    if max(w, h) > _MAX_DIM:
        scale = _MAX_DIM / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(dest, "JPEG", quality=_QUALITY)

    b64 = base64.b64encode(dest.read_bytes()).decode()
    return str(dest), b64


def save_document(content: bytes, original_filename: str) -> str:
    """Save uploaded document to data/media/ with timestamp. Returns path."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = original_filename.replace(" ", "_")
    dest = _ensure() / f"{ts}_{safe}"
    dest.write_bytes(content)
    return str(dest)
