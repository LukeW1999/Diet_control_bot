"""Periodic cleanup of old media files and conversation logs."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_MEDIA_DIR = _DATA_DIR / "media"
_FEED_DIR = _DATA_DIR / "hermes_feed"
_CONV_LOG = _DATA_DIR / "conversation_log.jsonl"

_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
_DOC_EXTS = {".md", ".txt", ".docx", ".pdf"}


def cleanup_media(image_days: int = 30, doc_days: int = 60) -> dict:
    now = datetime.now()
    counts = {"images": 0, "documents": 0}
    if not _MEDIA_DIR.exists():
        return counts
    for f in _MEDIA_DIR.iterdir():
        if not f.is_file():
            continue
        age = (now - datetime.fromtimestamp(f.stat().st_mtime)).days
        ext = f.suffix.lower()
        if ext in _IMAGE_EXTS and age > image_days:
            f.unlink()
            counts["images"] += 1
        elif ext in _DOC_EXTS and age > doc_days:
            f.unlink()
            counts["documents"] += 1
    return counts


def cleanup_conversation_log(days: int = 90) -> int:
    if not _CONV_LOG.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept, removed = [], 0
    with open(_CONV_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                ts = datetime.fromisoformat(event.get("ts", ""))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    kept.append(line)
                else:
                    removed += 1
            except Exception:
                kept.append(line)
    with open(_CONV_LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(kept) + ("\n" if kept else ""))
    return removed


def cleanup_hermes_feed(days: int = 180) -> int:
    if not _FEED_DIR.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=days)
    removed = 0
    for f in _FEED_DIR.iterdir():
        if f.is_file() and datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            f.unlink()
            removed += 1
    return removed


def run_all() -> dict:
    media = cleanup_media()
    return {
        "images_deleted": media["images"],
        "docs_deleted": media["documents"],
        "log_lines_removed": cleanup_conversation_log(),
        "feed_files_removed": cleanup_hermes_feed(),
    }
