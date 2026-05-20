from datetime import date

import pytest

from pb import core, db, plan


@pytest.fixture()
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    try:
        yield c
    finally:
        c.close()


class TestAllocations:
    def test_set_and_get(self, conn):
        plan.set_allocation(conn, "Save", 60)
        plan.set_allocation(conn, "Rent", 20)
        allocs = plan.get_plan(conn)
        names = {a.category_name: a.percent for a in allocs}
        assert names == {"Save": 60, "Rent": 20}

    def test_set_upserts(self, conn):
        plan.set_allocation(conn, "Save", 60)
        plan.set_allocation(conn, "Save", 50)
        allocs = plan.get_plan(conn)
        assert len(allocs) == 1
        assert allocs[0].percent == 50

    def test_reject_income_kind(self, conn):
        with pytest.raises(ValueError, match="income"):
            plan.set_allocation(conn, "Salary", 50)

    def test_reject_out_of_range(self, conn):
        with pytest.raises(ValueError):
            plan.set_allocation(conn, "Save", 101)
        with pytest.raises(ValueError):
            plan.set_allocation(conn, "Save", -1)

    def test_reject_unknown_category(self, conn):
        with pytest.raises(ValueError, match="Unknown"):
            plan.set_allocation(conn, "Nope", 50)

    def test_remove(self, conn):
        plan.set_allocation(conn, "Save", 60)
        assert plan.remove_allocation(conn, "Save") is True
        assert plan.get_plan(conn) == []
        assert plan.remove_allocation(conn, "Save") is False

    def test_clear(self, conn):
        plan.set_allocation(conn, "Save", 60)
        plan.set_allocation(conn, "Rent", 20)
        assert plan.clear_plan(conn) == 2
        assert plan.get_plan(conn) == []


class TestReport:
    def _seed_may_2026(self, conn):
        core.add_transaction(conn, amount_cents=350000, category="Salary",
                             occurred_on=date(2026, 5, 1))
        core.add_transaction(conn, amount_cents=145000, category="Rent",
                             occurred_on=date(2026, 5, 1))
        core.add_transaction(conn, amount_cents=2125, category="Food",
                             occurred_on=date(2026, 5, 15))
        core.add_transaction(conn, amount_cents=60000, category="Save",
                             occurred_on=date(2026, 5, 20))

    def test_allocated_math(self, conn):
        self._seed_may_2026(conn)
        plan.set_allocation(conn, "Save", 60)
        plan.set_allocation(conn, "Rent", 20)
        plan.set_allocation(conn, "Food", 10)
        r = plan.report(conn, month="2026-05")

        assert r["income_cents"] == 350000
        assert r["total_percent"] == 90

        lines = {l["category"]: l for l in r["lines"]}
        assert lines["Save"]["allocated_cents"] == 210000  # 60% of 350k
        assert lines["Save"]["spent_cents"] == 60000
        assert lines["Save"]["remaining_cents"] == 150000

        assert lines["Rent"]["allocated_cents"] == 70000  # 20% of 350k
        assert lines["Rent"]["spent_cents"] == 145000
        assert lines["Rent"]["remaining_cents"] == -75000  # overspent

        assert lines["Food"]["allocated_cents"] == 35000  # 10% of 350k

    def test_unbudgeted_spending(self, conn):
        self._seed_may_2026(conn)
        plan.set_allocation(conn, "Save", 60)  # only allocate Save
        r = plan.report(conn, month="2026-05")

        unbudgeted = {u["category"]: u for u in r["unbudgeted"]}
        assert "Rent" in unbudgeted
        assert "Food" in unbudgeted
        assert unbudgeted["Rent"]["spent_cents"] == 145000
        # Save shouldn't be unbudgeted (it has an allocation)
        assert "Save" not in unbudgeted

    def test_zero_income(self, conn):
        core.add_transaction(conn, amount_cents=1000, category="Food",
                             occurred_on=date(2026, 5, 1))
        plan.set_allocation(conn, "Food", 50)
        r = plan.report(conn, month="2026-05")
        assert r["income_cents"] == 0
        assert r["lines"][0]["allocated_cents"] == 0
        assert r["lines"][0]["spent_cents"] == 1000
        assert r["lines"][0]["remaining_cents"] == -1000

    def test_empty_report(self, conn):
        r = plan.report(conn, month="2026-05")
        assert r["income_cents"] == 0
        assert r["lines"] == []
        assert r["unbudgeted"] == []
        assert r["total_percent"] == 0

    def test_defaults_to_current_month(self, conn):
        # Just verify the path works without exploding when month=None
        r = plan.report(conn)
        assert "month" in r
        assert len(r["month"]) == 7  # YYYY-MM

    def test_month_isolation(self, conn):
        # Income in April should not affect May report
        core.add_transaction(conn, amount_cents=200000, category="Salary",
                             occurred_on=date(2026, 4, 1))
        core.add_transaction(conn, amount_cents=350000, category="Salary",
                             occurred_on=date(2026, 5, 1))
        plan.set_allocation(conn, "Save", 50)
        may = plan.report(conn, month="2026-05")
        assert may["income_cents"] == 350000
        assert may["lines"][0]["allocated_cents"] == 175000


class TestSchemaAutoMigrate:
    def test_apply_schema_idempotent(self, conn):
        # Calling apply_schema repeatedly should not fail or duplicate state.
        db.apply_schema(conn)
        db.apply_schema(conn)
        plan.set_allocation(conn, "Save", 60)
        db.apply_schema(conn)
        # Allocation should still be there after re-apply.
        assert plan.get_plan(conn)[0].percent == 60
