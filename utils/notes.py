from datetime import date, timedelta
from pathlib import Path

NOTES_DIR = Path(__file__).parent.parent / "data" / "notes"

CATEGORY_ICONS = {
    "work": "💼 工作",
    "study": "📚 学习",
    "programming": "💻 编程",
    "idea": "💡 想法",
    "other": "📝 其他",
}


def save_note(entry_date: date, category: str, content: str, summary: str = "") -> Path:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    filepath = NOTES_DIR / f"{entry_date.isoformat()}.md"
    existing = filepath.read_text(encoding="utf-8") if filepath.exists() else f"# {entry_date}\n"
    new_content = existing.rstrip() + f"\n- {content}\n"
    filepath.write_text(new_content, encoding="utf-8")
    return filepath


def get_week_notes(start: date, end: date) -> str:
    """Return all notes from start to end as combined text."""
    all_notes = []
    current = start
    while current <= end:
        filepath = NOTES_DIR / f"{current.isoformat()}.md"
        if filepath.exists():
            all_notes.append(filepath.read_text(encoding="utf-8"))
        current += timedelta(days=1)
    return "\n\n---\n\n".join(all_notes)


def get_today_notes(target_date: date) -> str:
    filepath = NOTES_DIR / f"{target_date.isoformat()}.md"
    return filepath.read_text(encoding="utf-8") if filepath.exists() else ""
