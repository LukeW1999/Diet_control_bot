"""Bring every tenant's database up to the current schema (ADD COLUMN only)."""
import glob
import os
import sqlite3

_DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))


def _databases() -> list[str]:
    """Every person's database, not just the primary one: each tenant has its own
    file and a column added to only one of them is a crash waiting for the others."""
    found = [os.path.join(_DATA, "health.db")]
    found += sorted(glob.glob(os.path.join(_DATA, "u-*", "health.db")))
    return [p for p in found if os.path.exists(p)]

_MIGRATIONS = [
    ("daily_summaries", "is_refeed", "INTEGER DEFAULT 0"),
    ("user_profile", "refeed_bonus_notified", "INTEGER DEFAULT 0"),
    ("user_profile", "refeed_weight_baseline", "REAL"),
    ("user_profile", "monthly_loss_kg", "REAL"),
    ("user_profile", "active_eatback_pct", "REAL"),
    ("user_profile", "activity_factor", "REAL"),
    ("user_profile", "server_food_log", "INTEGER"),
    ("user_profile", "timezone", "TEXT"),
    ("user_profile", "evening_hour", "INTEGER"),
]


def main() -> None:
    for db in _databases():
        who = os.path.basename(os.path.dirname(db))
        con = sqlite3.connect(db)
        added = []
        for table, col, decl in _MIGRATIONS:
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
            if col in cols or not cols:
                continue
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            added.append(f"{table}.{col}")
        con.commit()
        con.close()
        print(f"{who}: " + (", ".join(added) if added else "up to date"))


if __name__ == "__main__":
    main()
