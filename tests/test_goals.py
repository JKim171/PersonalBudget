from datetime import date

import pytest

from pb import core, db, goals


@pytest.fixture()
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    try:
        yield c
    finally:
        c.close()


class TestGoalCRUD:
    def test_add_and_get(self, conn):
        goals.add_goal(conn, "Laptop", 200000, target_date=date(2026, 12, 31))
        g = goals.get_goal(conn, "Laptop")
        assert g.name == "Laptop"
        assert g.target_cents == 200000
        assert g.target_date == date(2026, 12, 31)
        assert g.contributed_cents == 0

    def test_get_case_insensitive(self, conn):
        goals.add_goal(conn, "Laptop", 200000)
        assert goals.get_goal(conn, "laptop") is not None

    def test_no_target_date(self, conn):
        goals.add_goal(conn, "Emergency", 500000)
        g = goals.get_goal(conn, "Emergency")
        assert g.target_date is None

    def test_unique_name(self, conn):
        goals.add_goal(conn, "Laptop", 100000)
        with pytest.raises(Exception):
            goals.add_goal(conn, "Laptop", 200000)

    def test_reject_nonpositive_target(self, conn):
        with pytest.raises(ValueError):
            goals.add_goal(conn, "Bogus", 0)
        with pytest.raises(ValueError):
            goals.add_goal(conn, "Bogus", -100)

    def test_delete(self, conn):
        goals.add_goal(conn, "Laptop", 100000)
        assert goals.delete_goal(conn, "Laptop") is True
        assert goals.get_goal(conn, "Laptop") is None
        assert goals.delete_goal(conn, "Laptop") is False

    def test_list_sorts_by_target_date(self, conn):
        goals.add_goal(conn, "C-NoDate", 100000)
        goals.add_goal(conn, "A-Later", 100000, target_date=date(2027, 1, 1))
        goals.add_goal(conn, "B-Sooner", 100000, target_date=date(2026, 6, 1))
        names = [g.name for g in goals.list_goals(conn)]
        # dated first (chronologically), then undated
        assert names == ["B-Sooner", "A-Later", "C-NoDate"]


class TestContribute:
    def test_creates_txn_and_link(self, conn):
        goals.add_goal(conn, "Laptop", 200000)
        c = goals.contribute(conn, "Laptop", 30000, occurred_on=date(2026, 5, 1))
        assert c.amount_cents == 30000
        assert c.goal_name == "Laptop"

        # Underlying txn exists and is savings-kind
        txns = core.list_transactions(conn)
        assert len(txns) == 1
        assert txns[0].id == c.txn_id
        assert txns[0].category_kind == "savings"
        assert txns[0].amount_cents == 30000

    def test_progress_updates(self, conn):
        goals.add_goal(conn, "Laptop", 200000)
        goals.contribute(conn, "Laptop", 50000)
        goals.contribute(conn, "Laptop", 30000)
        g = goals.get_goal(conn, "Laptop")
        assert g.contributed_cents == 80000
        assert g.contribution_count == 2
        assert g.percent == 40.0
        assert g.remaining_cents == 120000

    def test_unknown_goal_rejected(self, conn):
        with pytest.raises(ValueError, match="Unknown goal"):
            goals.contribute(conn, "Nope", 100)

    def test_non_savings_category_rejected(self, conn):
        goals.add_goal(conn, "Laptop", 100000)
        with pytest.raises(ValueError, match="savings"):
            goals.contribute(conn, "Laptop", 100, category="Food")

    def test_over_saving_allowed(self, conn):
        goals.add_goal(conn, "Laptop", 100000)
        goals.contribute(conn, "Laptop", 150000)
        g = goals.get_goal(conn, "Laptop")
        assert g.contributed_cents == 150000
        assert g.percent == 150.0
        assert g.remaining_cents == 0  # clamped at 0, not negative

    def test_nonpositive_amount_rejected(self, conn):
        goals.add_goal(conn, "Laptop", 100000)
        with pytest.raises(ValueError):
            goals.contribute(conn, "Laptop", 0)
        with pytest.raises(ValueError):
            goals.contribute(conn, "Laptop", -50)

    def test_default_note(self, conn):
        goals.add_goal(conn, "Laptop", 100000)
        goals.contribute(conn, "Laptop", 100)
        txn = core.list_transactions(conn)[0]
        assert txn.note == "Goal: Laptop"

    def test_custom_savings_category(self, conn):
        core.add_category(conn, "VacationFund", "savings")
        goals.add_goal(conn, "Trip", 100000)
        c = goals.contribute(conn, "Trip", 5000, category="VacationFund")
        txn = next(t for t in core.list_transactions(conn) if t.id == c.txn_id)
        assert txn.category_name == "VacationFund"


class TestCascade:
    def test_delete_goal_removes_contributions_but_keeps_txn(self, conn):
        goals.add_goal(conn, "Laptop", 100000)
        c = goals.contribute(conn, "Laptop", 30000)
        goals.delete_goal(conn, "Laptop")

        # contribution row is gone
        assert goals.list_contributions(conn) == []
        # underlying savings txn is still there — money was actually saved
        remaining = core.list_transactions(conn)
        assert len(remaining) == 1
        assert remaining[0].id == c.txn_id

    def test_delete_txn_removes_contribution(self, conn):
        goals.add_goal(conn, "Laptop", 100000)
        c = goals.contribute(conn, "Laptop", 30000)
        with conn:
            conn.execute("DELETE FROM txn WHERE id = ?", (c.txn_id,))
        g = goals.get_goal(conn, "Laptop")
        assert g.contributed_cents == 0
        assert g.contribution_count == 0


class TestContributionsListing:
    def test_filter_by_goal(self, conn):
        goals.add_goal(conn, "Laptop", 100000)
        goals.add_goal(conn, "Vacation", 100000)
        goals.contribute(conn, "Laptop", 100)
        goals.contribute(conn, "Vacation", 200)
        goals.contribute(conn, "Laptop", 300)
        laptop = goals.list_contributions(conn, goal_name="Laptop")
        assert {c.amount_cents for c in laptop} == {100, 300}

    def test_all_contributions(self, conn):
        goals.add_goal(conn, "Laptop", 100000)
        goals.contribute(conn, "Laptop", 100)
        goals.contribute(conn, "Laptop", 200)
        assert len(goals.list_contributions(conn)) == 2
