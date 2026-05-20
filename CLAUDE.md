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
```

## Tests

```bash
.venv/bin/pytest          # all tests
.venv/bin/pytest tests/test_core.py::TestBalance::test_net_math   # single test
```

Tests use `:memory:` SQLite, so they're hermetic and fast.

## Architecture

Two-layer design — the **core** layer is UI-agnostic, the **CLI** is just a thin presentation shell. Future UIs (web, TUI) can reuse `pb/core.py` unchanged.

- `pb/db.py` — SQLite connection helper, schema, and seed. `connect()` returns a `sqlite3.Connection` with `Row` factory and foreign keys ON. `init_db()` is idempotent.
- `pb/models.py` — Frozen dataclasses (`Category`, `Transaction`). Transaction is a flattened view model that includes the joined category name + kind for display convenience.
- `pb/core.py` — Business logic: `add_transaction`, `list_transactions`, `balance`, money parse/format. All functions take an explicit `sqlite3.Connection` (no module-level state).
- `pb/cli.py` — `click` CLI group. Each command opens its own connection from `ctx.obj["db_path"]` and registers `conn.close` via `ctx.call_on_close`.
- `budget.py` — Single-line entrypoint that re-exports `pb.cli:cli`.

### Key invariants

- **Money is stored as positive integer cents** in `txn.amount_cents` (`CHECK(amount_cents > 0)`). Never floats. Sign for display comes from `category.kind`.
- **Direction is implied by the category's kind**, not the transaction. `income` adds to inflow, `expense` and `savings` are outflows. `balance.net_cents = income - expense - savings`.
- **`Save` is a category, not a separate account.** Phase 3 will layer goals on top by linking contributions to savings transactions.
- Dates are stored as ISO `YYYY-MM-DD` strings; month filters use half-open ranges `[start, next_month_start)` computed in `_month_bounds`.

## Roadmap (where this is going)

- **Phase 2** — `BudgetPlan` table with percentage allocations per category; `budget plan set` / `budget report` showing actual vs. planned per month.
- **Phase 3** — `Goal` (target purchase) + `goal_contribution` linking to savings transactions.
- **Phase 4** — Web UI (FastAPI + HTMX or Streamlit) reusing `pb/core.py`.

When extending: add to `pb/core.py` first (with tests), then surface in `pb/cli.py`. Don't put business logic in CLI commands.
