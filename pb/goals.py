"""Savings goals (target purchases) backed by real savings transactions."""

from __future__ import annotations

import sqlite3
from datetime import date

from . import core
from .models import Contribution, Goal, GoalProgress


def add_goal(
    conn: sqlite3.Connection,
    name: str,
    target_cents: int,
    target_date: date | None = None,
) -> Goal:
    if target_cents <= 0:
        raise ValueError("target_cents must be positive")
    with conn:
        cur = conn.execute(
            "INSERT INTO goal(name, target_cents, target_date) VALUES (?, ?, ?)",
            (name, target_cents, target_date.isoformat() if target_date else None),
        )
    return Goal(cur.lastrowid, name, target_cents, target_date)


def _find_goal(conn: sqlite3.Connection, name: str) -> Goal | None:
    row = conn.execute(
        "SELECT id, name, target_cents, target_date FROM goal "
        "WHERE name = ? COLLATE NOCASE",
        (name,),
    ).fetchone()
    if row is None:
        return None
    td = date.fromisoformat(row["target_date"]) if row["target_date"] else None
    return Goal(row["id"], row["name"], row["target_cents"], td)


def delete_goal(conn: sqlite3.Connection, name: str) -> bool:
    g = _find_goal(conn, name)
    if g is None:
        return False
    with conn:
        conn.execute("DELETE FROM goal WHERE id = ?", (g.id,))
    return True


def list_goals(conn: sqlite3.Connection) -> list[GoalProgress]:
    rows = conn.execute(
        "SELECT g.id, g.name, g.target_cents, g.target_date, "
        "       COALESCE(SUM(c.amount_cents), 0) AS contributed, "
        "       COUNT(c.id) AS n "
        "FROM goal g "
        "LEFT JOIN goal_contribution c ON c.goal_id = g.id "
        "GROUP BY g.id "
        "ORDER BY g.target_date IS NULL, g.target_date, g.name"
    ).fetchall()
    return [_row_to_progress(r) for r in rows]


def get_goal(conn: sqlite3.Connection, name: str) -> GoalProgress | None:
    row = conn.execute(
        "SELECT g.id, g.name, g.target_cents, g.target_date, "
        "       COALESCE(SUM(c.amount_cents), 0) AS contributed, "
        "       COUNT(c.id) AS n "
        "FROM goal g "
        "LEFT JOIN goal_contribution c ON c.goal_id = g.id "
        "WHERE g.name = ? COLLATE NOCASE "
        "GROUP BY g.id",
        (name,),
    ).fetchone()
    return _row_to_progress(row) if row else None


def _row_to_progress(row: sqlite3.Row) -> GoalProgress:
    td = date.fromisoformat(row["target_date"]) if row["target_date"] else None
    return GoalProgress(
        id=row["id"],
        name=row["name"],
        target_cents=row["target_cents"],
        target_date=td,
        contributed_cents=row["contributed"],
        contribution_count=row["n"],
    )


def contribute(
    conn: sqlite3.Connection,
    goal_name: str,
    amount_cents: int,
    *,
    category: str = "Save",
    occurred_on: date | None = None,
    note: str | None = None,
) -> Contribution:
    """Create a savings transaction AND link it to the goal, atomically."""
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    goal = _find_goal(conn, goal_name)
    if goal is None:
        raise ValueError(f"Unknown goal: {goal_name!r}")
    cat = core.find_category(conn, category)
    if cat is None:
        raise ValueError(f"Unknown category: {category!r}")
    if cat.kind != "savings":
        raise ValueError(
            f"Category {cat.name!r} is kind {cat.kind!r}; contributions require a savings category."
        )

    occurred_on = occurred_on or date.today()
    contrib_note = note or f"Goal: {goal.name}"
    with conn:
        txn_cur = conn.execute(
            "INSERT INTO txn(occurred_on, amount_cents, category_id, note) "
            "VALUES (?, ?, ?, ?)",
            (occurred_on.isoformat(), amount_cents, cat.id, contrib_note),
        )
        txn_id = txn_cur.lastrowid
        contrib_cur = conn.execute(
            "INSERT INTO goal_contribution(goal_id, txn_id, amount_cents) "
            "VALUES (?, ?, ?)",
            (goal.id, txn_id, amount_cents),
        )
    return Contribution(
        id=contrib_cur.lastrowid,
        goal_id=goal.id,
        goal_name=goal.name,
        txn_id=txn_id,
        amount_cents=amount_cents,
        occurred_on=occurred_on,
        note=note,
    )


def list_contributions(
    conn: sqlite3.Connection, goal_name: str | None = None
) -> list[Contribution]:
    sql = (
        "SELECT c.id, c.goal_id, g.name AS goal_name, c.txn_id, c.amount_cents, "
        "       t.occurred_on, t.note "
        "FROM goal_contribution c "
        "JOIN goal g ON g.id = c.goal_id "
        "JOIN txn t ON t.id = c.txn_id"
    )
    params: list[object] = []
    if goal_name:
        sql += " WHERE g.name = ? COLLATE NOCASE"
        params.append(goal_name)
    sql += " ORDER BY t.occurred_on DESC, c.id DESC"
    rows = conn.execute(sql, params).fetchall()
    return [
        Contribution(
            id=r["id"],
            goal_id=r["goal_id"],
            goal_name=r["goal_name"],
            txn_id=r["txn_id"],
            amount_cents=r["amount_cents"],
            occurred_on=date.fromisoformat(r["occurred_on"]),
            note=r["note"],
        )
        for r in rows
    ]
