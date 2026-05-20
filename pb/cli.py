"""Click CLI for the PersonalBudget app."""

from __future__ import annotations

from datetime import date

import click

from . import core, db
from .models import Transaction


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise click.BadParameter(f"Expected YYYY-MM-DD, got {value!r}") from exc


def _open(ctx: click.Context):
    conn = db.connect(ctx.obj["db_path"])
    ctx.call_on_close(conn.close)
    return conn


@click.group()
@click.option(
    "--db",
    "db_path",
    envvar="BUDGET_DB",
    default="budget.db",
    show_default=True,
    type=click.Path(dir_okay=False),
    help="Path to the SQLite database file.",
)
@click.pass_context
def cli(ctx: click.Context, db_path: str) -> None:
    """Personal budget tracker."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db_path


@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Create the DB and seed default categories."""
    conn = _open(ctx)
    db.init_db(conn)
    click.echo(f"Initialized {ctx.obj['db_path']} with {len(db.DEFAULT_CATEGORIES)} default categories.")


@cli.group()
def categories() -> None:
    """Manage categories."""


@categories.command("list")
@click.pass_context
def categories_list(ctx: click.Context) -> None:
    conn = _open(ctx)
    rows = core.list_categories(conn)
    if not rows:
        click.echo("No categories. Run `budget init` first.")
        return
    width = max(len(c.name) for c in rows)
    for c in rows:
        click.echo(f"  {c.name.ljust(width)}  {c.kind}")


@categories.command("add")
@click.argument("name")
@click.option(
    "--kind",
    type=click.Choice(["income", "expense", "savings"]),
    required=True,
)
@click.pass_context
def categories_add(ctx: click.Context, name: str, kind: str) -> None:
    conn = _open(ctx)
    try:
        cat = core.add_category(conn, name, kind)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Added category {cat.name} ({cat.kind})")


@cli.command("add-income")
@click.argument("amount")
@click.option("--category", "-c", default="Salary", show_default=True)
@click.option("--date", "occurred_on", default=None, help="YYYY-MM-DD (default: today)")
@click.option("--note", "-n", default=None)
@click.pass_context
def add_income(
    ctx: click.Context,
    amount: str,
    category: str,
    occurred_on: str | None,
    note: str | None,
) -> None:
    """Record income."""
    _record(ctx, amount, category, occurred_on, note, expected_kind="income")


@cli.command("add-expense")
@click.argument("amount")
@click.argument("category")
@click.option("--date", "occurred_on", default=None, help="YYYY-MM-DD (default: today)")
@click.option("--note", "-n", default=None)
@click.pass_context
def add_expense(
    ctx: click.Context,
    amount: str,
    category: str,
    occurred_on: str | None,
    note: str | None,
) -> None:
    """Record an expense."""
    _record(ctx, amount, category, occurred_on, note, expected_kind="expense")


@cli.command("save")
@click.argument("amount")
@click.option("--category", "-c", default="Save", show_default=True)
@click.option("--date", "occurred_on", default=None, help="YYYY-MM-DD (default: today)")
@click.option("--note", "-n", default=None)
@click.pass_context
def save(
    ctx: click.Context,
    amount: str,
    category: str,
    occurred_on: str | None,
    note: str | None,
) -> None:
    """Move money into a savings category."""
    _record(ctx, amount, category, occurred_on, note, expected_kind="savings")


def _record(
    ctx: click.Context,
    amount: str,
    category: str,
    occurred_on: str | None,
    note: str | None,
    *,
    expected_kind: str,
) -> None:
    conn = _open(ctx)
    try:
        cents = core.parse_money(amount)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="AMOUNT") from exc

    cat = core.find_category(conn, category)
    if cat is None:
        raise click.ClickException(
            f"Unknown category {category!r}. Run `budget categories list` to see options."
        )
    if cat.kind != expected_kind:
        raise click.ClickException(
            f"Category {cat.name!r} is of kind {cat.kind!r}, expected {expected_kind!r}."
        )
    txn = core.add_transaction(
        conn,
        amount_cents=cents,
        category=cat.name,
        occurred_on=_parse_date(occurred_on),
        note=note,
    )
    click.echo(
        f"#{txn.id}  {txn.occurred_on}  {core.format_money(txn.amount_cents)}  "
        f"{txn.category_name}"
        + (f"  — {txn.note}" if txn.note else "")
    )


@cli.command("list")
@click.option("--month", default=None, help="Filter by month, e.g. 2026-05")
@click.option("--category", "-c", default=None, help="Filter by category name")
@click.option("--limit", "-n", default=20, show_default=True, type=int)
@click.pass_context
def list_cmd(
    ctx: click.Context,
    month: str | None,
    category: str | None,
    limit: int,
) -> None:
    """Show recent transactions."""
    conn = _open(ctx)
    txns = core.list_transactions(conn, month=month, category=category, limit=limit)
    if not txns:
        click.echo("No transactions.")
        return
    _render_txns(txns)


def _render_txns(txns: list[Transaction]) -> None:
    cat_w = max(len(t.category_name) for t in txns)
    amt_w = max(len(core.format_money(t.amount_cents)) for t in txns)
    for t in txns:
        sign = {"income": "+", "expense": "-", "savings": "→"}[t.category_kind]
        amount = core.format_money(t.amount_cents).rjust(amt_w)
        line = (
            f"  #{t.id:>4}  {t.occurred_on}  {sign}{amount}  "
            f"{t.category_name.ljust(cat_w)}"
        )
        if t.note:
            line += f"  — {t.note}"
        click.echo(line)


@cli.command()
@click.option("--month", default=None, help="Scope totals to this month, e.g. 2026-05")
@click.pass_context
def balance(ctx: click.Context, month: str | None) -> None:
    """Show income, expenses, savings, and net."""
    conn = _open(ctx)
    summary = core.balance(conn, month=month)
    scope = f" for {month}" if month else ""
    click.echo(f"Summary{scope}:")
    click.echo(f"  Income   {core.format_money(summary['income_cents'])}")
    click.echo(f"  Expenses {core.format_money(summary['expense_cents'])}")
    click.echo(f"  Savings  {core.format_money(summary['savings_cents'])}")
    click.echo(f"  Net      {core.format_money(summary['net_cents'])}")

    if not summary["by_category"]:
        return
    click.echo("\nBy category:")
    name_w = max(len(r["category"]) for r in summary["by_category"])
    for r in summary["by_category"]:
        click.echo(
            f"  {r['category'].ljust(name_w)}  {r['kind']:<8}  "
            f"{core.format_money(r['total_cents'])}"
        )


if __name__ == "__main__":
    cli()
