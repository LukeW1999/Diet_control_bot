"""
Search across all books in data/books/.
Returns compact snippets (book name + context) to minimise token usage.
"""
import os
import re

_BOOKS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "books")
_CONTEXT_CHARS = 250
_MAX_MATCHES_PER_BOOK = 2
_MAX_TOTAL = 5


def _list_books() -> list[tuple[str, str]]:
    """Return list of (display_name, filepath) for all books."""
    if not os.path.isdir(_BOOKS_DIR):
        return []
    results = []
    for fname in sorted(os.listdir(_BOOKS_DIR)):
        if fname.endswith(".txt"):
            display = fname.replace(".txt", "").replace("_", " ")
            results.append((display, os.path.join(_BOOKS_DIR, fname)))
    return results


def grep_books(keyword: str, context_chars: int = _CONTEXT_CHARS) -> list[dict]:
    """
    Search all books for keyword.
    Returns list of {book, snippet} dicts, capped at _MAX_TOTAL.
    """
    if not keyword or not keyword.strip():
        return []

    kw = keyword.strip()
    all_results = []

    for display, fpath in _list_books():
        try:
            with open(fpath, encoding="utf-8") as f:
                full = f.read()
        except OSError:
            continue

        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        matches = list(pattern.finditer(full))

        if not matches:
            # Fuzzy: try each character pair as substring
            for part in re.findall(r"[一-鿿]{2,}", kw):
                pattern = re.compile(re.escape(part), re.IGNORECASE)
                matches = list(pattern.finditer(full))
                if matches:
                    break

        seen_pos: list[int] = []
        book_count = 0
        for m in matches:
            if book_count >= _MAX_MATCHES_PER_BOOK:
                break
            if any(abs(m.start() - p) < context_chars for p in seen_pos):
                continue
            seen_pos.append(m.start())

            start = max(0, m.start() - context_chars)
            end = min(len(full), m.end() + context_chars)
            snippet = full[start:end].strip()
            snippet = re.sub(r"\n{2,}", "\n", snippet)
            all_results.append({"book": display, "snippet": f"…{snippet}…"})
            book_count += 1

            if len(all_results) >= _MAX_TOTAL:
                break

        if len(all_results) >= _MAX_TOTAL:
            break

    return all_results


def format_results(results: list[dict]) -> str:
    if not results:
        return ""
    parts = []
    for r in results:
        parts.append(f"[{r['book']}]\n{r['snippet']}")
    return "\n\n---\n\n".join(parts)


def list_available_books() -> list[str]:
    return [display for display, _ in _list_books()]
