import os

from utils import tenant


def _memory_path() -> str:
    return str(tenant.data_dir() / "psych_memory.txt")


def load_psych_memory() -> str:
    if not os.path.exists(_memory_path()):
        return ""
    with open(_memory_path(), encoding="utf-8") as f:
        return f.read().strip()


def save_psych_memory(text: str) -> None:
    os.makedirs(os.path.dirname(_memory_path()), exist_ok=True)
    with open(_memory_path(), "w", encoding="utf-8") as f:
        f.write(text.strip())
