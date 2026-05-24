import os
import random

_QUOTES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "zarathustra_quotes.txt"
)


def get_random_quote() -> str | None:
    """Return a random line from zarathustra_quotes.txt, or None if unavailable."""
    if not os.path.exists(_QUOTES_PATH):
        return None
    with open(_QUOTES_PATH, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    return random.choice(lines) if lines else None
