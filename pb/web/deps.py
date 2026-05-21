"""FastAPI dependencies — DB connection lifecycle."""

from __future__ import annotations

import sqlite3
from typing import Generator

from pb import db


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """One connection per request. Auto-applies schema (matches CLI behavior)."""
    conn = db.connect()
    db.apply_schema(conn)
    try:
        yield conn
    finally:
        conn.close()
