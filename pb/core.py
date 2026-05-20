"""Business logic over the SQLite store. UI-agnostic."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation

from .models import Category, Transaction


def parse_money(s: str) -> int:
    """Parse a human amount string into positive integer cents."""
    cleaned = s.strip().replace(",", "").replace("$", "")
    try:
        d = Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount: {s!r}") from exc
    if d <= 0:
        raise ValueError("Amount must be positive")
    return int(d * 100)


def format_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def list_categories(conn: sqlite3.Connection) -> list[Category]:
    rows = conn.execute(
        "SELECT id, name, kind FROM category ORDER BY kind, name"
    ).fetchall()
    return [Category(r["id"], r["name"], r["kind"]) for r in rows]


def find_category(conn: sqlite3.Connection, name: str) -> Category | None:
    row = conn.execute(
        "SELECT id, name, kind FROM category WHERE name = ? COLLATE NOCASE",
        (name,),
    ).fetchone()
    return Category(row["id"], row["name"], row["kind"]) if row else None


def add_category(conn: sqlite3.Connection, name: str, kind: str) -> Category:
    if kind not in ("income", "expense", "savings"):
        raise ValueError(f"Invalid kind: {kind!r}")
    with conn:
        cur = conn.execute(
            "INSERT INTO category(name, kind) VALUES (?, ?)", (name, kind)
        )
    return Category(cur.lastrowid, name, kind)


def add_transaction(
    conn: sqlite3.Connection,
    *,
    amount_cents: int,
    category: str,
    occurred_on: date | None = None,
    note: str | None = None,
) -> Transaction:
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    cat = find_category(conn, category)
    if cat is None:
        raise ValueError(f"Unknown category: {category!r}. Run `budget categories` to see options.")
    occurred_on = occurred_on or date.today()
    with conn:
        cur = conn.execute(
            "INSERT INTO txn(occurred_on, amount_cents, category_id, note) "
            "VALUES (?, ?, ?, ?)",
            (occurred_on.isoformat(), amount_cents, cat.id, note),
        )
    return Transaction(
        id=cur.lastrowid,
        occurred_on=occurred_on,
        amount_cents=amount_cents,
        category_id=cat.id,
        category_name=cat.name,
        category_kind=cat.kind,
        note=note,
    )


def _month_bounds(month: str) -> tuple[str, str]:
    """Given 'YYYY-MM', return ('YYYY-MM-01', 'YYYY-(MM+1)-01')."""
    year_s, mo_s = month.split("-")
    year, mo = int(year_s), int(mo_s)
    if not 1 <= mo <= 12:
        raise ValueError(f"Invalid month: {month!r}")
    start = f"{year:04d}-{mo:02d}-01"
    end_year, end_mo = (year + 1, 1) if mo == 12 else (year, mo + 1)
    end = f"{end_year:04d}-{end_mo:02d}-01"
    return start, end


def list_transactions(
    conn: sqlite3.Connection,
    *,
    month: str | None = None,
    category: str | None = None,
    limit: int | None = None,
) -> list[Transaction]:
    sql = (
        "SELECT t.id, t.occurred_on, t.amount_cents, t.category_id, t.note, "
        "c.name AS category_name, c.kind "
        "FROM txn t JOIN category c ON c.id = t.category_id"
    )
    where: list[str] = []
    params: list[object] = []
    if month:
        start, end = _month_bounds(month)
        where.append("t.occurred_on >= ? AND t.occurred_on < ?")
        params.extend([start, end])
    if category:
        where.append("c.name = ? COLLATE NOCASE")
        params.append(category)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.occurred_on DESC, t.id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [
        Transaction(
            id=r["id"],
            occurred_on=date.fromisoformat(r["occurred_on"]),
            amount_cents=r["amount_cents"],
            category_id=r["category_id"],
            category_name=r["category_name"],
            category_kind=r["kind"],
            note=r["note"],
        )
        for r in rows
    ]


def balance(
    conn: sqlite3.Connection, *, month: str | None = None
) -> dict:
    """Aggregate totals by kind and category. Optionally scoped to a month."""
    sql = (
        "SELECT c.kind, c.name, SUM(t.amount_cents) AS total "
        "FROM txn t JOIN category c ON c.id = t.category_id"
    )
    params: list[object] = []
    if month:
        start, end = _month_bounds(month)
        sql += " WHERE t.occurred_on >= ? AND t.occurred_on < ?"
        params.extend([start, end])
    sql += " GROUP BY c.kind, c.name"
    rows = conn.execute(sql, params).fetchall()

    by_kind = {"income": 0, "expense": 0, "savings": 0}
    by_category: list[dict] = []
    for r in rows:
        by_kind[r["kind"]] += r["total"]
        by_category.append(
            {"category": r["name"], "kind": r["kind"], "total_cents": r["total"]}
        )

    net = by_kind["income"] - by_kind["expense"] - by_kind["savings"]
    return {
        "income_cents": by_kind["income"],
        "expense_cents": by_kind["expense"],
        "savings_cents": by_kind["savings"],
        "net_cents": net,
        "by_category": sorted(
            by_category, key=lambda x: (x["kind"], -x["total_cents"])
        ),
    }
