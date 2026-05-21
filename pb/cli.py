"""Click CLI for the PersonalBudget app."""

from __future__ import annotations

from datetime import date

import click

from . import core, db, goals as goals_mod, plan as plan_mod
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
    db.apply_schema(conn)
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


@cli.group()
def plan() -> None:
    """Manage percentage-based budget allocations."""


@plan.command("set")
@click.argument("category")
@click.argument("percent", type=click.FloatRange(0, 100))
@click.pass_context
def plan_set(ctx: click.Context, category: str, percent: float) -> None:
    """Set CATEGORY's allocation to PERCENT (0..100)."""
    conn = _open(ctx)
    try:
        alloc = plan_mod.set_allocation(conn, category, percent)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{alloc.category_name}: {alloc.percent}%  ({alloc.category_kind})")


@plan.command("show")
@click.pass_context
def plan_show(ctx: click.Context) -> None:
    conn = _open(ctx)
    allocs = plan_mod.get_plan(conn)
    if not allocs:
        click.echo("No allocations set. Try: budget plan set Save 60")
        return
    name_w = max(len(a.category_name) for a in allocs)
    for a in allocs:
        click.echo(
            f"  {a.category_name.ljust(name_w)}  {a.percent:>5.1f}%  {a.category_kind}"
        )
    total = sum(a.percent for a in allocs)
    click.echo(f"  {'Total'.ljust(name_w)}  {total:>5.1f}%")
    if abs(total - 100) > 0.01:
        click.echo(
            f"  ⚠ allocations sum to {total:.1f}%, not 100%.", err=True
        )


@plan.command("remove")
@click.argument("category")
@click.pass_context
def plan_remove(ctx: click.Context, category: str) -> None:
    conn = _open(ctx)
    if plan_mod.remove_allocation(conn, category):
        click.echo(f"Removed allocation for {category}.")
    else:
        click.echo(f"No allocation found for {category}.")


@plan.command("clear")
@click.confirmation_option(prompt="Clear all allocations?")
@click.pass_context
def plan_clear(ctx: click.Context) -> None:
    conn = _open(ctx)
    n = plan_mod.clear_plan(conn)
    click.echo(f"Cleared {n} allocation(s).")


@cli.command()
@click.option("--month", default=None, help="YYYY-MM (default: current month)")
@click.pass_context
def report(ctx: click.Context, month: str | None) -> None:
    """Plan vs. actual for a month."""
    conn = _open(ctx)
    r = plan_mod.report(conn, month=month)
    click.echo(f"Plan vs. actual for {r['month']}")
    click.echo(f"Income this month: {core.format_money(r['income_cents'])}\n")

    if not r["lines"]:
        click.echo("No allocations set. Try: budget plan set Save 60")
    else:
        header = f"  {'Category'.ljust(14)}  {'%':>6}  {'Allocated':>12}  {'Spent':>12}  {'Remaining':>12}"
        click.echo(header)
        for line in r["lines"]:
            cat = line["category"][:14].ljust(14)
            pct = f"{line['percent']:.1f}%"
            allocated = core.format_money(line["allocated_cents"])
            spent = core.format_money(line["spent_cents"])
            remaining = core.format_money(line["remaining_cents"])
            warn = "  ⚠" if line["remaining_cents"] < 0 else ""
            click.echo(
                f"  {cat}  {pct:>6}  {allocated:>12}  {spent:>12}  {remaining:>12}{warn}"
            )
        total_alloc = sum(l["allocated_cents"] for l in r["lines"])
        total_spent = sum(l["spent_cents"] for l in r["lines"])
        click.echo(
            f"  {'Total'.ljust(14)}  {r['total_percent']:>5.1f}%  "
            f"{core.format_money(total_alloc):>12}  "
            f"{core.format_money(total_spent):>12}  "
            f"{core.format_money(total_alloc - total_spent):>12}"
        )

    if r["unbudgeted"]:
        click.echo("\nUnbudgeted spending:")
        for u in r["unbudgeted"]:
            click.echo(
                f"  {u['category']:<14}  {u['kind']:<8}  {core.format_money(u['spent_cents'])}"
            )


@cli.group()
def goal() -> None:
    """Manage savings goals (target purchases)."""


@goal.command("add")
@click.argument("name")
@click.argument("target")
@click.option("--by", "target_date", default=None, help="Target date YYYY-MM-DD")
@click.pass_context
def goal_add(
    ctx: click.Context, name: str, target: str, target_date: str | None
) -> None:
    conn = _open(ctx)
    try:
        cents = core.parse_money(target)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="TARGET") from exc
    td = _parse_date(target_date)
    try:
        g = goals_mod.add_goal(conn, name, cents, td)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    by = f" by {g.target_date}" if g.target_date else ""
    click.echo(f"Added goal {g.name}: target {core.format_money(g.target_cents)}{by}")


@goal.command("list")
@click.pass_context
def goal_list(ctx: click.Context) -> None:
    conn = _open(ctx)
    goals = goals_mod.list_goals(conn)
    if not goals:
        click.echo("No goals yet. Try: budget goal add Laptop 2000 --by 2026-12-31")
        return
    name_w = max(len(g.name) for g in goals)
    for g in goals:
        click.echo(f"  {g.name.ljust(name_w)}  {_progress_line(g)}")


@goal.command("show")
@click.argument("name")
@click.pass_context
def goal_show(ctx: click.Context, name: str) -> None:
    conn = _open(ctx)
    g = goals_mod.get_goal(conn, name)
    if g is None:
        raise click.ClickException(f"No goal named {name!r}")
    click.echo(g.name)
    click.echo(f"  Target:     {core.format_money(g.target_cents)}")
    click.echo(
        f"  Saved:      {core.format_money(g.contributed_cents)}  ({g.percent:.1f}%)"
    )
    click.echo(f"  Remaining:  {core.format_money(g.remaining_cents)}")
    if g.target_date:
        delta = (g.target_date - date.today()).days
        if g.contributed_cents >= g.target_cents:
            status = "(achieved!)"
        elif delta >= 0:
            status = f"({delta} days away)"
        else:
            status = f"({abs(delta)} days overdue ⚠)"
        click.echo(f"  Target date: {g.target_date}  {status}")
    click.echo(f"  Progress:   {_progress_bar(g.percent)}")

    contribs = goals_mod.list_contributions(conn, goal_name=g.name)
    if contribs:
        click.echo("\nContributions:")
        for c in contribs:
            line = f"  {c.occurred_on}  {core.format_money(c.amount_cents)}  txn #{c.txn_id}"
            if c.note:
                line += f"  — {c.note}"
            click.echo(line)


@goal.command("contribute")
@click.argument("name")
@click.argument("amount")
@click.option("--category", "-c", default="Save", show_default=True,
              help="Savings category to draw from")
@click.option("--date", "occurred_on", default=None, help="YYYY-MM-DD (default: today)")
@click.option("--note", "-n", default=None)
@click.pass_context
def goal_contribute(
    ctx: click.Context,
    name: str,
    amount: str,
    category: str,
    occurred_on: str | None,
    note: str | None,
) -> None:
    """Save AMOUNT toward goal NAME (creates a linked savings transaction)."""
    conn = _open(ctx)
    try:
        cents = core.parse_money(amount)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="AMOUNT") from exc
    try:
        contrib = goals_mod.contribute(
            conn,
            name,
            cents,
            category=category,
            occurred_on=_parse_date(occurred_on),
            note=note,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    progress = goals_mod.get_goal(conn, contrib.goal_name)
    click.echo(
        f"Contributed {core.format_money(contrib.amount_cents)} to "
        f"{contrib.goal_name} (txn #{contrib.txn_id}, {category})"
    )
    if progress:
        click.echo(f"  → {_progress_line(progress)}")


@goal.command("delete")
@click.argument("name")
@click.confirmation_option(prompt="Delete this goal and all its contribution links?")
@click.pass_context
def goal_delete(ctx: click.Context, name: str) -> None:
    """Delete a goal. Underlying savings transactions are kept."""
    conn = _open(ctx)
    if goals_mod.delete_goal(conn, name):
        click.echo(f"Deleted goal {name}.")
    else:
        click.echo(f"No goal named {name!r}.")


def _progress_bar(percent: float, width: int = 20) -> str:
    filled = max(0, min(width, int(round(width * percent / 100))))
    return "[" + "█" * filled + "░" * (width - filled) + f"] {percent:.0f}%"


def _progress_line(g) -> str:
    base = (
        f"{core.format_money(g.contributed_cents)} / "
        f"{core.format_money(g.target_cents)}  {_progress_bar(g.percent, 14)}"
    )
    if g.target_date:
        base += f"  by {g.target_date}"
    return base


if __name__ == "__main__":
    cli()
