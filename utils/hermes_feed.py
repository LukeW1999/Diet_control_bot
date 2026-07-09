"""Generate weekly JSON feed for Hermes to read and analyze."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_MEDIA_DIR = _DATA_DIR / "media"
_CONV_LOG = _DATA_DIR / "conversation_log.jsonl"
_FEED_DIR = _DATA_DIR / "hermes_feed"


def generate_weekly_feed(weeks_back: int = 0) -> str:
    """Build YYYY-WNN.json for Hermes. Returns the output path."""
    _FEED_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    # Start of the target ISO week (Monday 00:00 UTC)
    week_start = (now - timedelta(days=now.weekday() + weeks_back * 7)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end = week_start + timedelta(days=7)
    year, week_num, _ = week_start.isocalendar()
    out_path = _FEED_DIR / f"{year}-W{week_num:02d}.json"

    # --- conversation events ---
    events: list[dict] = []
    if _CONV_LOG.exists():
        with open(_CONV_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    ts = datetime.fromisoformat(ev.get("ts", ""))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if week_start <= ts < week_end:
                        events.append(ev)
                except Exception:
                    pass

    # --- media files ---
    media: list[dict] = []
    if _MEDIA_DIR.exists():
        for f in sorted(_MEDIA_DIR.iterdir()):
            if not f.is_file():
                continue
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if week_start <= mtime < week_end:
                media.append({
                    "filename": f.name,
                    "path": str(f),
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "modified": mtime.isoformat(),
                })

    # --- event type summary ---
    type_counts: dict[str, int] = {}
    for ev in events:
        t = ev.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    feed = {
        "week": f"{year}-W{week_num:02d}",
        "period": {
            "start": week_start.isoformat(),
            "end": week_end.isoformat(),
        },
        "summary": {
            "total_events": len(events),
            "event_types": type_counts,
            "media_count": len(media),
        },
        "events": events,
        "media": media,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)

    return str(out_path)
