"""SQLite connection and schema management."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(os.environ.get("BUDGET_DB", "budget.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS category (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('income','expense','savings'))
);

CREATE TABLE IF NOT EXISTS txn (
    id INTEGER PRIMARY KEY,
    occurred_on TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
    category_id INTEGER NOT NULL REFERENCES category(id),
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_txn_occurred ON txn(occurred_on);
CREATE INDEX IF NOT EXISTS idx_txn_category ON txn(category_id);
"""

DEFAULT_CATEGORIES: list[tuple[str, str]] = [
    ("Salary", "income"),
    ("Other Income", "income"),
    ("Save", "savings"),
    ("Food", "expense"),
    ("Rent", "expense"),
    ("Transport", "expense"),
    ("Utilities", "expense"),
    ("Entertainment", "expense"),
    ("Other", "expense"),
]


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create schema and seed default categories. Idempotent."""
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT OR IGNORE INTO category(name, kind) VALUES (?, ?)",
        DEFAULT_CATEGORIES,
    )
    conn.commit()
