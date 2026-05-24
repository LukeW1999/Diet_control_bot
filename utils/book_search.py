"""
Local grep over zarathustra_full.txt.
Returns compact passage snippets to minimise token usage.
"""
import os
import re

_FULL_TEXT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "zarathustra_full.txt"
)

_CONTEXT_CHARS = 200   # chars to show before/after match
_MAX_MATCHES = 3       # cap results to save tokens


def _load_lines() -> list[str]:
    if not os.path.exists(_FULL_TEXT_PATH):
        return []
    with open(_FULL_TEXT_PATH, encoding="utf-8") as f:
        return f.readlines()


def grep_book(keyword: str, context_chars: int = _CONTEXT_CHARS) -> str:
    """
    Search full text for keyword, return up to _MAX_MATCHES snippets
    with surrounding context. Returns empty string if not found.
    """
    if not keyword or not keyword.strip():
        return ""

    lines = _load_lines()
    if not lines:
        return ""

    full = "".join(lines)
    pattern = re.compile(re.escape(keyword.strip()), re.IGNORECASE)
    matches = list(pattern.finditer(full))

    if not matches:
        # Try fuzzy: split keyword and search for any part
        parts = keyword.strip().split()
        for part in parts:
            if len(part) >= 2:
                pattern = re.compile(re.escape(part), re.IGNORECASE)
                matches = list(pattern.finditer(full))
                if matches:
                    break

    if not matches:
        return ""

    snippets = []
    seen_positions = []
    for m in matches:
        # Skip if too close to a previously included match
        if any(abs(m.start() - p) < context_chars for p in seen_positions):
            continue
        seen_positions.append(m.start())

        start = max(0, m.start() - context_chars)
        end = min(len(full), m.end() + context_chars)
        snippet = full[start:end].strip()
        # Clean up whitespace
        snippet = re.sub(r"\n{2,}", "\n", snippet)
        snippets.append(f"…{snippet}…")

        if len(snippets) >= _MAX_MATCHES:
            break

    return "\n\n---\n\n".join(snippets)
