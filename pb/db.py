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

CREATE TABLE IF NOT EXISTS plan_allocation (
    category_id INTEGER PRIMARY KEY REFERENCES category(id) ON DELETE CASCADE,
    percent REAL NOT NULL CHECK(percent >= 0 AND percent <= 100)
);

CREATE TABLE IF NOT EXISTS goal (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    target_cents INTEGER NOT NULL CHECK(target_cents > 0),
    target_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS goal_contribution (
    id INTEGER PRIMARY KEY,
    goal_id INTEGER NOT NULL REFERENCES goal(id) ON DELETE CASCADE,
    txn_id INTEGER NOT NULL REFERENCES txn(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0)
);

CREATE INDEX IF NOT EXISTS idx_goal_contrib_goal ON goal_contribution(goal_id);
CREATE INDEX IF NOT EXISTS idx_goal_contrib_txn ON goal_contribution(txn_id);
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


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create/upgrade tables. Idempotent, safe to call on every connect."""
    conn.executescript(SCHEMA)
    conn.commit()


def seed_defaults(conn: sqlite3.Connection) -> None:
    """Insert default categories if not already present."""
    conn.executemany(
        "INSERT OR IGNORE INTO category(name, kind) VALUES (?, ?)",
        DEFAULT_CATEGORIES,
    )
    conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    """Schema + seed. Idempotent."""
    apply_schema(conn)
    seed_defaults(conn)
