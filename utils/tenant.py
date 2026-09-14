"""Whose data the current request touches.

Every table is keyed by date alone, so two people sharing one database would
overwrite each other's weigh-ins and daily totals. Rather than add a user column
to six tables, each person gets their own SQLite file and their own data files,
which leaves every existing query untouched.

The primary user keeps the original `data/` layout, so nothing moves for them.
"""
import os
from contextvars import ContextVar
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent / "data"

_current: ContextVar[str] = ContextVar("tenant", default="")


def primary() -> str:
    """Read at call time so tests and `.env` reloads are not baked in at import."""
    return (os.getenv("WECOM_USER_ID") or "primary").lower()


def known() -> set[str]:
    """Everyone allowed to own data here. A name outside this set is a typo or an
    intruder, and either way must not quietly get a fresh empty database."""
    extra = (os.getenv("EXTRA_USERS") or "").replace(",", " ").split()
    return {primary(), *(u.strip().lower() for u in extra if u.strip())}


def set_current(user: str | None) -> None:
    _current.set((user or "").lower())


def current() -> str:
    return _current.get() or primary()


def data_dir() -> Path:
    if current() == primary():
        return _ROOT
    path = _ROOT / f"u-{current()}"
    path.mkdir(parents=True, exist_ok=True)
    return path
