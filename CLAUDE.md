# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

PersonalBudget — a CLI personal-finance tracker backed by SQLite. Goal is to log income, expenses, and savings, with future phases for percentage-based budget plans and savings goals (target purchases).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Common commands

All CLI commands route through `budget.py`. The DB path defaults to `./budget.db` and can be overridden with the `BUDGET_DB` env var or `--db` flag.

```bash
.venv/bin/python budget.py init                                # create schema + seed categories
.venv/bin/python budget.py categories list
.venv/bin/python budget.py categories add Coffee --kind expense
.venv/bin/python budget.py add-income 3500 --note "May paycheck"
.venv/bin/python budget.py add-expense 12.50 Food --note "Lunch"
.venv/bin/python budget.py save 600                            # move to "Save" category
.venv/bin/python budget.py list --month 2026-05 --category Food
.venv/bin/python budget.py balance --month 2026-05

# Phase 2 — budget plan + actual-vs-planned report
.venv/bin/python budget.py plan set Save 60                    # upsert one allocation
.venv/bin/python budget.py plan show                           # warns if sum != 100
.venv/bin/python budget.py plan remove Save
.venv/bin/python budget.py report --month 2026-05              # allocated / spent / remaining per category

# Phase 3 — savings goals (target purchases)
.venv/bin/python budget.py goal add Laptop 2000 --by 2026-12-31
.venv/bin/python budget.py goal contribute Laptop 300          # creates a Save txn + links it
.venv/bin/python budget.py goal show Laptop                    # progress bar + contribution history
.venv/bin/python budget.py goal list
.venv/bin/python budget.py goal delete Laptop                  # keeps underlying savings txns

# Phase 4 — web UI
.venv/bin/python budget.py web                                  # http://127.0.0.1:8000
.venv/bin/python budget.py web --port 8765 --reload             # dev mode
```

## Tests

```bash
.venv/bin/pytest          # all tests
.venv/bin/pytest tests/test_core.py::TestBalance::test_net_math   # single test
```

Tests use `:memory:` SQLite, so they're hermetic and fast.

## Architecture

Two-layer design — the **core** layer is UI-agnostic, the **CLI** is just a thin presentation shell. Future UIs (web, TUI) can reuse `pb/core.py` unchanged.

- `pb/db.py` — SQLite connection + schema. `apply_schema()` is the lightweight idempotent migration (called on every CLI command via `_open`); `seed_defaults()` inserts the default category list; `init_db()` calls both.
- `pb/models.py` — Frozen dataclasses (`Category`, `Transaction`, `Allocation`). `Transaction` is a flattened view model that includes the joined category name + kind for display convenience.
- `pb/core.py` — Transaction-layer logic: `add_transaction`, `list_transactions`, `balance`, money parse/format, `_month_bounds`. All functions take an explicit `sqlite3.Connection` (no module-level state).
- `pb/plan.py` — Budget plan layer: `set_allocation` (upsert), `get_plan`, `remove_allocation`, `clear_plan`, `report` (plan vs. actual for a month, including unbudgeted spending).
- `pb/goals.py` — Savings goals: `add_goal`, `list_goals`/`get_goal` (return `GoalProgress` with aggregated contributions), `contribute` (atomically creates a savings txn + links it), `delete_goal`, `list_contributions`.
- `pb/cli.py` — `click` CLI group. `_open` opens a connection and applies the schema so older DBs migrate transparently. Each command registers `conn.close` via `ctx.call_on_close`. The `web` subcommand launches uvicorn against `pb.web.app:app`.
- `pb/web/` — FastAPI app (`app.py`), DB dependency (`deps.py`), and Jinja templates. Routes parse forms and call into the same `core` / `plan` / `goals` modules the CLI uses. **No business logic in routes.** Uses Starlette 1.0's `TemplateResponse(request, name, ctx)` signature. Most form posts redirect (303); HTMX endpoints return HTML fragments for in-place swaps (plan table).
- `budget.py` — Single-line entrypoint that re-exports `pb.cli:cli`.

### Key invariants

- **Money is stored as positive integer cents** in `txn.amount_cents` (`CHECK(amount_cents > 0)`). Never floats. Sign for display comes from `category.kind`.
- **Direction is implied by the category's kind**, not the transaction. `income` adds to inflow, `expense` and `savings` are outflows. `balance.net_cents = income - expense - savings`.
- **`Save` is a category, not a separate account.** Phase 3 will layer goals on top by linking contributions to savings transactions.
- Dates are stored as ISO `YYYY-MM-DD` strings; month filters use half-open ranges `[start, next_month_start)` computed in `_month_bounds`.
- **One active plan, no history.** `plan_allocation` is a flat table — one row per allocated category. The same plan is applied to every month and evaluated against that month's actual income. Income kind categories are not allocatable.
- **Schema auto-migrates.** Every CLI command runs `apply_schema()` after connect, so existing DBs pick up new tables (e.g., `plan_allocation`, `goal`) without an explicit migration step.
- **Goal contributions are always backed by a real savings transaction.** `goals.contribute` creates a `txn` row (savings kind) and a `goal_contribution` row atomically. There's no way to inflate goal progress without actually saving money. Contributions must use a `savings`-kind category (default `Save`).
- **Cascade asymmetry.** Deleting a `goal` cascades to its `goal_contribution` rows but **keeps the underlying `txn` rows** — the money was really saved and remains in your savings category. Deleting a `txn` cascades to remove its contribution (so goal progress shrinks accordingly).
- **Over-saving is allowed.** A goal at 150% of target is valid; `remaining_cents` clamps to 0 rather than going negative.

## Roadmap (where this is going)

- **Phase 1 (done)** — CLI + SQLite tracking: transactions, categories, balance.
- **Phase 2 (done)** — Percentage allocations + actual-vs-planned monthly report.
- **Phase 3 (done)** — `goal` + `goal_contribution`, linked to real savings transactions.
- **Phase 4 (done)** — FastAPI + HTMX + Jinja2 web UI reusing all domain modules unchanged.
- **Phase 5+ (ideas)** — Bank CSV import, recurring transactions, charts (Chart.js), auth if going multi-user, cloud sync.

When extending: add to the appropriate domain module (`pb/core.py` for transactions, `pb/plan.py` for plan/report logic, `pb/goals.py` for goals) **with tests**, then surface in `pb/cli.py` and/or `pb/web/`. Don't put business logic in CLI commands or route handlers.
