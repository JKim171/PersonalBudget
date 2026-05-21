import pytest
from fastapi.testclient import TestClient

from pb import core, db, goals, plan
from pb.web.app import app
from pb.web.deps import get_db


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "test.db"
    seed = db.connect(p)
    db.init_db(seed)
    seed.close()
    return p


@pytest.fixture()
def client(db_path):
    def override_get_db():
        conn = db.connect(db_path)
        db.apply_schema(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def direct_conn(db_path):
    """Direct connection for arrange/assert outside the request cycle."""
    conn = db.connect(db_path)
    db.apply_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


class TestPagesRender:
    @pytest.mark.parametrize(
        "path", ["/", "/transactions", "/plan", "/goals", "/categories"]
    )
    def test_returns_200_with_layout(self, client, path):
        r = client.get(path)
        assert r.status_code == 200
        assert "PersonalBudget" in r.text  # nav brand from base.html


class TestTransactions:
    def test_create_via_form(self, client, direct_conn):
        r = client.post(
            "/transactions",
            data={
                "kind": "income",
                "amount": "1500",
                "category": "Salary",
                "occurred_on": "2026-05-01",
                "note": "Test paycheck",
            },
        )
        assert r.status_code == 200  # followed 303 -> 200
        txns = core.list_transactions(direct_conn)
        assert len(txns) == 1
        assert txns[0].amount_cents == 150000
        assert txns[0].note == "Test paycheck"

    def test_kind_mismatch_rejected(self, client):
        r = client.post(
            "/transactions",
            data={"kind": "expense", "amount": "10", "category": "Salary"},
        )
        assert r.status_code == 400

    def test_filter_by_month(self, client, direct_conn):
        from datetime import date
        core.add_transaction(direct_conn, amount_cents=100, category="Food",
                             occurred_on=date(2026, 4, 1))
        core.add_transaction(direct_conn, amount_cents=200, category="Food",
                             occurred_on=date(2026, 5, 1))
        r = client.get("/transactions?month=2026-05")
        assert "$2.00" in r.text
        assert "$1.00" not in r.text


class TestPlan:
    def test_set_allocation_returns_fragment(self, client, direct_conn):
        r = client.post(
            "/plan/allocations", data={"category": "Save", "percent": "60"}
        )
        assert r.status_code == 200
        # HTMX fragment, not full page
        assert "<html" not in r.text
        assert 'id="plan-table"' in r.text
        assert "60.0%" in r.text
        # state persisted
        assert plan.get_plan(direct_conn)[0].percent == 60

    def test_remove_allocation(self, client, direct_conn):
        plan.set_allocation(direct_conn, "Save", 60)
        r = client.post("/plan/allocations/Save/delete")
        assert r.status_code == 200
        assert plan.get_plan(direct_conn) == []

    def test_reject_income_kind(self, client):
        r = client.post(
            "/plan/allocations", data={"category": "Salary", "percent": "10"}
        )
        assert r.status_code == 400


class TestGoals:
    def test_create_and_view(self, client, direct_conn):
        r = client.post(
            "/goals",
            data={"name": "Laptop", "target": "2000", "target_date": "2026-12-31"},
        )
        assert r.status_code == 200  # followed redirect to detail
        assert "Laptop" in r.text
        g = goals.get_goal(direct_conn, "Laptop")
        assert g.target_cents == 200000

    def test_contribute_updates_progress(self, client, direct_conn):
        goals.add_goal(direct_conn, "Laptop", 200000)
        r = client.post(
            "/goals/Laptop/contributions",
            data={"amount": "500", "category": "Save"},
        )
        assert r.status_code == 200
        g = goals.get_goal(direct_conn, "Laptop")
        assert g.contributed_cents == 50000

    def test_delete_goal(self, client, direct_conn):
        goals.add_goal(direct_conn, "Laptop", 200000)
        r = client.post("/goals/Laptop/delete")
        assert r.status_code == 200
        assert goals.get_goal(direct_conn, "Laptop") is None

    def test_404_on_unknown(self, client):
        r = client.get("/goals/Nope")
        assert r.status_code == 404


class TestCategories:
    def test_add_category(self, client, direct_conn):
        r = client.post("/categories", data={"name": "Coffee", "kind": "expense"})
        assert r.status_code == 200
        assert core.find_category(direct_conn, "Coffee") is not None

    def test_duplicate_rejected(self, client):
        client.post("/categories", data={"name": "Coffee", "kind": "expense"})
        r = client.post("/categories", data={"name": "Coffee", "kind": "expense"})
        assert r.status_code == 400


class TestDashboard:
    def test_shows_plan_when_set(self, client, direct_conn):
        from datetime import date
        plan.set_allocation(direct_conn, "Save", 50)
        plan.set_allocation(direct_conn, "Food", 30)
        core.add_transaction(direct_conn, amount_cents=200000, category="Salary",
                             occurred_on=date.today())
        r = client.get(f"/?month={date.today():%Y-%m}")
        assert r.status_code == 200
        # plan totals should be visible
        assert "Save" in r.text
        assert "Food" in r.text
