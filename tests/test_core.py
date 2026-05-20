from datetime import date

import pytest

from pb import core, db


@pytest.fixture()
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    try:
        yield c
    finally:
        c.close()


class TestMoney:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1", 100),
            ("1.00", 100),
            ("12.34", 1234),
            ("1,234.56", 123456),
            ("$5", 500),
            (" 7.5 ", 750),
        ],
    )
    def test_parse(self, raw, expected):
        assert core.parse_money(raw) == expected

    @pytest.mark.parametrize("raw", ["", "abc", "0", "-5", "0.00"])
    def test_parse_rejects(self, raw):
        with pytest.raises(ValueError):
            core.parse_money(raw)

    def test_format(self):
        assert core.format_money(0) == "$0.00"
        assert core.format_money(50) == "$0.50"
        assert core.format_money(123456) == "$1,234.56"
        assert core.format_money(-100) == "-$1.00"


class TestSchema:
    def test_seeded_categories(self, conn):
        cats = core.list_categories(conn)
        names = {c.name for c in cats}
        assert {"Salary", "Save", "Food", "Rent"} <= names

    def test_init_is_idempotent(self, conn):
        db.init_db(conn)  # second call should not fail or duplicate
        assert len(core.list_categories(conn)) == len(db.DEFAULT_CATEGORIES)


class TestTransactions:
    def test_add_and_list(self, conn):
        core.add_transaction(
            conn, amount_cents=300000, category="Salary", occurred_on=date(2026, 5, 1)
        )
        core.add_transaction(
            conn, amount_cents=1250, category="Food", occurred_on=date(2026, 5, 3),
            note="lunch",
        )
        txns = core.list_transactions(conn)
        assert len(txns) == 2
        assert txns[0].category_name == "Food"  # most recent first
        assert txns[0].note == "lunch"

    def test_unknown_category_rejected(self, conn):
        with pytest.raises(ValueError):
            core.add_transaction(conn, amount_cents=100, category="DoesNotExist")

    def test_filter_by_month(self, conn):
        core.add_transaction(conn, amount_cents=100, category="Food",
                             occurred_on=date(2026, 4, 15))
        core.add_transaction(conn, amount_cents=200, category="Food",
                             occurred_on=date(2026, 5, 15))
        core.add_transaction(conn, amount_cents=400, category="Food",
                             occurred_on=date(2026, 5, 30))
        may = core.list_transactions(conn, month="2026-05")
        assert {t.amount_cents for t in may} == {200, 400}

    def test_filter_by_category_case_insensitive(self, conn):
        core.add_transaction(conn, amount_cents=100, category="Food")
        core.add_transaction(conn, amount_cents=200, category="Rent")
        results = core.list_transactions(conn, category="food")
        assert len(results) == 1
        assert results[0].category_name == "Food"

    def test_month_bounds_december(self, conn):
        core.add_transaction(conn, amount_cents=100, category="Food",
                             occurred_on=date(2026, 12, 31))
        core.add_transaction(conn, amount_cents=200, category="Food",
                             occurred_on=date(2027, 1, 1))
        dec = core.list_transactions(conn, month="2026-12")
        assert len(dec) == 1
        assert dec[0].amount_cents == 100


class TestBalance:
    def test_empty(self, conn):
        b = core.balance(conn)
        assert b == {
            "income_cents": 0,
            "expense_cents": 0,
            "savings_cents": 0,
            "net_cents": 0,
            "by_category": [],
        }

    def test_net_math(self, conn):
        core.add_transaction(conn, amount_cents=500000, category="Salary")
        core.add_transaction(conn, amount_cents=120000, category="Rent")
        core.add_transaction(conn, amount_cents=30000, category="Food")
        core.add_transaction(conn, amount_cents=100000, category="Save")
        b = core.balance(conn)
        assert b["income_cents"] == 500000
        assert b["expense_cents"] == 150000
        assert b["savings_cents"] == 100000
        assert b["net_cents"] == 250000  # 500k - 150k - 100k

    def test_month_scope(self, conn):
        core.add_transaction(conn, amount_cents=100, category="Food",
                             occurred_on=date(2026, 4, 1))
        core.add_transaction(conn, amount_cents=900, category="Food",
                             occurred_on=date(2026, 5, 1))
        may = core.balance(conn, month="2026-05")
        assert may["expense_cents"] == 900


class TestAddCategory:
    def test_add_and_use(self, conn):
        core.add_category(conn, "Coffee", "expense")
        core.add_transaction(conn, amount_cents=450, category="Coffee")
        b = core.balance(conn)
        assert b["expense_cents"] == 450

    def test_invalid_kind_rejected(self, conn):
        with pytest.raises(ValueError):
            core.add_category(conn, "Bogus", "nonsense")
