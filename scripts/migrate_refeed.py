"""Add refeed columns to existing DB (SQLite ADD COLUMN is a no-op if present)."""
import os
import sqlite3

_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "health.db"))

_MIGRATIONS = [
    ("daily_summaries", "is_refeed", "INTEGER DEFAULT 0"),
    ("user_profile", "refeed_bonus_notified", "INTEGER DEFAULT 0"),
    ("user_profile", "refeed_weight_baseline", "REAL"),
]


def main() -> None:
    con = sqlite3.connect(_DB)
    for table, col, decl in _MIGRATIONS:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        if col in cols:
            print(f"{table}.{col} already present, skipping")
            continue
        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        print(f"added {table}.{col}")
    con.commit()
    con.close()


if __name__ == "__main__":
    main()
