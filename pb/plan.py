"""Percentage-based budget plan + actual-vs-planned reporting."""

from __future__ import annotations

import sqlite3
from datetime import date

from . import core
from .models import Allocation


def set_allocation(
    conn: sqlite3.Connection, category_name: str, percent: float
) -> Allocation:
    """Upsert a single category allocation. Income categories are not allocatable."""
    if not 0 <= percent <= 100:
        raise ValueError(f"percent must be 0..100, got {percent}")
    cat = core.find_category(conn, category_name)
    if cat is None:
        raise ValueError(f"Unknown category: {category_name!r}")
    if cat.kind == "income":
        raise ValueError(
            f"Cannot allocate to income category {cat.name!r}; allocate to expense/savings."
        )
    with conn:
        conn.execute(
            "INSERT INTO plan_allocation(category_id, percent) VALUES (?, ?) "
            "ON CONFLICT(category_id) DO UPDATE SET percent = excluded.percent",
            (cat.id, percent),
        )
    return Allocation(cat.id, cat.name, cat.kind, percent)


def remove_allocation(conn: sqlite3.Connection, category_name: str) -> bool:
    cat = core.find_category(conn, category_name)
    if cat is None:
        return False
    with conn:
        cur = conn.execute(
            "DELETE FROM plan_allocation WHERE category_id = ?", (cat.id,)
        )
    return cur.rowcount > 0


def clear_plan(conn: sqlite3.Connection) -> int:
    with conn:
        cur = conn.execute("DELETE FROM plan_allocation")
    return cur.rowcount


def get_plan(conn: sqlite3.Connection) -> list[Allocation]:
    rows = conn.execute(
        "SELECT c.id, c.name, c.kind, p.percent "
        "FROM plan_allocation p JOIN category c ON c.id = p.category_id "
        "ORDER BY p.percent DESC, c.name"
    ).fetchall()
    return [Allocation(r["id"], r["name"], r["kind"], r["percent"]) for r in rows]


def _current_month() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def report(conn: sqlite3.Connection, month: str | None = None) -> dict:
    """Plan vs. actual for a given month (defaults to current month).

    Returns:
        {
          'month': 'YYYY-MM',
          'income_cents': int,
          'total_percent': float,
          'lines': [  # one per allocation
            {'category', 'kind', 'percent', 'allocated_cents', 'spent_cents', 'remaining_cents'},
            ...
          ],
          'unbudgeted': [  # categories with spending but no allocation
            {'category', 'kind', 'spent_cents'},
            ...
          ],
        }
    """
    month = month or _current_month()
    start, end = core._month_bounds(month)

    income_row = conn.execute(
        "SELECT COALESCE(SUM(t.amount_cents), 0) AS total "
        "FROM txn t JOIN category c ON c.id = t.category_id "
        "WHERE c.kind = 'income' AND t.occurred_on >= ? AND t.occurred_on < ?",
        (start, end),
    ).fetchone()
    income_cents = income_row["total"]

    spent_rows = conn.execute(
        "SELECT c.id, c.name, c.kind, SUM(t.amount_cents) AS total "
        "FROM txn t JOIN category c ON c.id = t.category_id "
        "WHERE c.kind IN ('expense','savings') "
        "AND t.occurred_on >= ? AND t.occurred_on < ? "
        "GROUP BY c.id",
        (start, end),
    ).fetchall()
    spent_by_cat: dict[int, dict] = {
        r["id"]: {"name": r["name"], "kind": r["kind"], "total": r["total"]}
        for r in spent_rows
    }

    allocations = get_plan(conn)
    allocated_ids = {a.category_id for a in allocations}

    lines = []
    for a in allocations:
        allocated_cents = int(income_cents * a.percent / 100)
        spent = spent_by_cat.get(a.category_id, {}).get("total", 0)
        lines.append(
            {
                "category": a.category_name,
                "kind": a.category_kind,
                "percent": a.percent,
                "allocated_cents": allocated_cents,
                "spent_cents": spent,
                "remaining_cents": allocated_cents - spent,
            }
        )

    unbudgeted = [
        {"category": v["name"], "kind": v["kind"], "spent_cents": v["total"]}
        for cat_id, v in spent_by_cat.items()
        if cat_id not in allocated_ids
    ]
    unbudgeted.sort(key=lambda x: -x["spent_cents"])

    return {
        "month": month,
        "income_cents": income_cents,
        "total_percent": sum(a.percent for a in allocations),
        "lines": lines,
        "unbudgeted": unbudgeted,
    }
