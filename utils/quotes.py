import os
import random
import re

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_BOOKS_DIR = os.path.join(_DATA_DIR, "books")
_ZARATHUSTRA_QUOTES = os.path.join(_DATA_DIR, "zarathustra_quotes.txt")

# Minimum / maximum char length for an ad-hoc quote from book files
_MIN_LEN = 15
_MAX_LEN = 120


def _pick_from_zarathustra() -> tuple[str, str] | None:
    if not os.path.exists(_ZARATHUSTRA_QUOTES):
        return None
    with open(_ZARATHUSTRA_QUOTES, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    if not lines:
        return None
    return random.choice(lines), "尼采《查拉图斯特拉如是说》"


def _pick_from_books() -> tuple[str, str] | None:
    if not os.path.isdir(_BOOKS_DIR):
        return None
    book_files = [
        f for f in os.listdir(_BOOKS_DIR) if f.endswith(".txt")
    ]
    if not book_files:
        return None

    random.shuffle(book_files)
    for fname in book_files:
        fpath = os.path.join(_BOOKS_DIR, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue

        # Split on sentence-ending punctuation
        segments = re.split(r"[。！？；\n]", text)
        candidates = []
        for seg in segments:
            seg = seg.strip()
            seg = seg.strip("「」『』《》〈〉【】—…·•※★○●▲△■□◆◇☆*\"'")
            seg = seg.strip()
            if _MIN_LEN <= len(seg) <= _MAX_LEN:
                # Must have enough Chinese characters
                if len(re.findall(r"[一-鿿]", seg)) >= 8:
                    candidates.append(seg)

        if candidates:
            display = fname.replace(".txt", "").replace("_", " ")
            return random.choice(candidates), display

    return None


def get_random_quote() -> tuple[str, str] | None:
    """
    Return (quote_text, source_name) from a random book, or None if unavailable.
    Prefers the curated Zarathustra quotes file 50% of the time when available.
    """
    has_zarathustra = os.path.exists(_ZARATHUSTRA_QUOTES)
    has_books = os.path.isdir(_BOOKS_DIR) and bool(
        [f for f in os.listdir(_BOOKS_DIR) if f.endswith(".txt")]
        if os.path.isdir(_BOOKS_DIR) else []
    )

    if has_zarathustra and has_books:
        picker = _pick_from_zarathustra if random.random() < 0.5 else _pick_from_books
    elif has_zarathustra:
        picker = _pick_from_zarathustra
    elif has_books:
        picker = _pick_from_books
    else:
        return None

    return picker()
