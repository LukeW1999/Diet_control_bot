import os

_MEMORY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "psych_memory.txt"
)


def load_psych_memory() -> str:
    if not os.path.exists(_MEMORY_PATH):
        return ""
    with open(_MEMORY_PATH, encoding="utf-8") as f:
        return f.read().strip()


def save_psych_memory(text: str) -> None:
    os.makedirs(os.path.dirname(_MEMORY_PATH), exist_ok=True)
    with open(_MEMORY_PATH, "w", encoding="utf-8") as f:
        f.write(text.strip())
