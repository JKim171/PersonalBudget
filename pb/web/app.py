"""FastAPI web UI over the PersonalBudget domain layer.

Routes are thin: they parse the request, call into pb.core/plan/goals,
and render templates. No business logic lives here.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pb import core, goals as goals_mod, plan as plan_mod
from pb.web.deps import get_db

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["money"] = core.format_money

app = FastAPI(title="PersonalBudget")

ConnDep = Annotated[sqlite3.Connection, Depends(get_db)]


def _parse_optional_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid date: {s!r}") from exc


def _current_month() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


# ---------- Dashboard ----------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, conn: ConnDep, month: str | None = None):
    month = month or _current_month()
    report = plan_mod.report(conn, month=month)
    summary = core.balance(conn, month=month)
    goal_progress = goals_mod.list_goals(conn)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "month": month,
            "report": report,
            "summary": summary,
            "goals": goal_progress,
            "active": "dashboard",
        },
    )


# ---------- Transactions ----------

@app.get("/transactions", response_class=HTMLResponse)
def transactions_page(
    request: Request,
    conn: ConnDep,
    month: str | None = None,
    category: str | None = None,
):
    txns = core.list_transactions(conn, month=month, category=category, limit=100)
    categories = core.list_categories(conn)
    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "transactions": txns,
            "categories": categories,
            "filter_month": month or "",
            "filter_category": category or "",
            "active": "transactions",
        },
    )


@app.post("/transactions")
def create_transaction(
    conn: ConnDep,
    amount: Annotated[str, Form()],
    category: Annotated[str, Form()],
    kind: Annotated[str, Form()],  # 'income' | 'expense' | 'savings'
    occurred_on: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
):
    try:
        cents = core.parse_money(amount)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    cat = core.find_category(conn, category)
    if cat is None:
        raise HTTPException(400, f"Unknown category {category!r}")
    if cat.kind != kind:
        raise HTTPException(
            400, f"Category {cat.name!r} is {cat.kind!r}, form said {kind!r}"
        )
    try:
        core.add_transaction(
            conn,
            amount_cents=cents,
            category=cat.name,
            occurred_on=_parse_optional_date(occurred_on),
            note=note or None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/transactions", status_code=status.HTTP_303_SEE_OTHER)


# ---------- Plan ----------

@app.get("/plan", response_class=HTMLResponse)
def plan_page(request: Request, conn: ConnDep):
    allocations = plan_mod.get_plan(conn)
    categories = [c for c in core.list_categories(conn) if c.kind != "income"]
    total = sum(a.percent for a in allocations)
    return templates.TemplateResponse(
        request,
        "plan.html",
        {
            "allocations": allocations,
            "categories": categories,
            "total_percent": total,
            "active": "plan",
        },
    )


@app.post("/plan/allocations", response_class=HTMLResponse)
def set_allocation(
    request: Request,
    conn: ConnDep,
    category: Annotated[str, Form()],
    percent: Annotated[float, Form()],
):
    try:
        plan_mod.set_allocation(conn, category, percent)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    allocations = plan_mod.get_plan(conn)
    total = sum(a.percent for a in allocations)
    return templates.TemplateResponse(
        request,
        "_plan_table.html",
        {"allocations": allocations, "total_percent": total},
    )


@app.post("/plan/allocations/{category}/delete", response_class=HTMLResponse)
def remove_allocation(request: Request, conn: ConnDep, category: str):
    plan_mod.remove_allocation(conn, category)
    allocations = plan_mod.get_plan(conn)
    total = sum(a.percent for a in allocations)
    return templates.TemplateResponse(
        request,
        "_plan_table.html",
        {"allocations": allocations, "total_percent": total},
    )


# ---------- Goals ----------

@app.get("/goals", response_class=HTMLResponse)
def goals_page(request: Request, conn: ConnDep):
    return templates.TemplateResponse(
        request,
        "goals.html",
        {
            "goals": goals_mod.list_goals(conn),
            "active": "goals",
        },
    )


@app.post("/goals")
def create_goal(
    conn: ConnDep,
    name: Annotated[str, Form()],
    target: Annotated[str, Form()],
    target_date: Annotated[str, Form()] = "",
):
    try:
        cents = core.parse_money(target)
        goals_mod.add_goal(conn, name, cents, _parse_optional_date(target_date))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(400, f"Goal {name!r} already exists") from exc
    return RedirectResponse(f"/goals/{name}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/goals/{name}", response_class=HTMLResponse)
def goal_detail(request: Request, conn: ConnDep, name: str):
    g = goals_mod.get_goal(conn, name)
    if g is None:
        raise HTTPException(404, f"No goal named {name!r}")
    contribs = goals_mod.list_contributions(conn, goal_name=g.name)
    savings_cats = [c for c in core.list_categories(conn) if c.kind == "savings"]
    days_label = _days_label(g)
    return templates.TemplateResponse(
        request,
        "goal_detail.html",
        {
            "goal": g,
            "contributions": contribs,
            "savings_categories": savings_cats,
            "days_label": days_label,
            "active": "goals",
        },
    )


@app.post("/goals/{name}/contributions")
def contribute(
    conn: ConnDep,
    name: str,
    amount: Annotated[str, Form()],
    category: Annotated[str, Form()] = "Save",
    occurred_on: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
):
    try:
        cents = core.parse_money(amount)
        goals_mod.contribute(
            conn,
            name,
            cents,
            category=category,
            occurred_on=_parse_optional_date(occurred_on),
            note=note or None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/goals/{name}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/goals/{name}/delete")
def delete_goal(conn: ConnDep, name: str):
    goals_mod.delete_goal(conn, name)
    return RedirectResponse("/goals", status_code=status.HTTP_303_SEE_OTHER)


def _days_label(g) -> str | None:
    if g.target_date is None:
        return None
    if g.contributed_cents >= g.target_cents:
        return "achieved!"
    delta = (g.target_date - date.today()).days
    if delta >= 0:
        return f"{delta} days away"
    return f"{abs(delta)} days overdue"


# ---------- Categories ----------

@app.get("/categories", response_class=HTMLResponse)
def categories_page(request: Request, conn: ConnDep):
    return templates.TemplateResponse(
        request,
        "categories.html",
        {
            "categories": core.list_categories(conn),
            "active": "categories",
        },
    )


@app.post("/categories")
def create_category(
    conn: ConnDep,
    name: Annotated[str, Form()],
    kind: Annotated[str, Form()],
):
    try:
        core.add_category(conn, name, kind)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(400, f"Category {name!r} already exists") from exc
    return RedirectResponse("/categories", status_code=status.HTTP_303_SEE_OTHER)
