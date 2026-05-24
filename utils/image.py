import base64
import os
from datetime import date
from pathlib import Path
from PIL import Image
import io


MAX_DIMENSION = 1200
QUALITY = 85


def save_and_encode(image_bytes: bytes, category: str, record_date: date = None) -> tuple[str, str]:
    """Save image to disk and return (file_path, base64_string)."""
    if record_date is None:
        record_date = date.today()

    base_dir = Path(__file__).parent.parent / "data" / "images" / category
    base_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{record_date.isoformat()}.jpg"
    filepath = base_dir / filename

    img = Image.open(io.BytesIO(image_bytes))
    img = _resize(img)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(filepath, "JPEG", quality=QUALITY)

    b64 = base64.b64encode(filepath.read_bytes()).decode()
    return str(filepath), b64


def encode_existing(filepath: str) -> str:
    return base64.b64encode(Path(filepath).read_bytes()).decode()


def _resize(img: Image.Image) -> Image.Image:
    w, h = img.size
    if max(w, h) <= MAX_DIMENSION:
        return img
    if w >= h:
        new_w = MAX_DIMENSION
        new_h = int(h * MAX_DIMENSION / w)
    else:
        new_h = MAX_DIMENSION
        new_w = int(w * MAX_DIMENSION / h)
    return img.resize((new_w, new_h), Image.LANCZOS)
