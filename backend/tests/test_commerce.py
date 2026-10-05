from decimal import Decimal
from pathlib import Path

import pytest
from pglast import parse_sql

from backend.commerce import CommerceError, amount_to_minor_units


def test_currency_conversion_uses_minor_units():
    assert amount_to_minor_units(Decimal("18.25"), "usd") == 1825
    assert amount_to_minor_units(Decimal("500"), "jpy") == 500
    with pytest.raises(CommerceError):
        amount_to_minor_units(Decimal("1.25"), "jpy")


def test_migrations_are_valid_postgresql_sql_and_keep_order_snapshots():
    migration_dir = Path(__file__).resolve().parents[1] / "migrations"
    for migration in sorted(migration_dir.glob("*.sql")):
        assert parse_sql(migration.read_text(encoding="utf-8"))

    commerce_sql = (migration_dir / "002_commerce.sql").read_text(encoding="utf-8")
    assert "product_id INTEGER REFERENCES products(id) ON DELETE SET NULL" in commerce_sql
    assert "product_name TEXT NOT NULL" in commerce_sql
    assert "unit_price NUMERIC(12, 2)" in commerce_sql
    assert "UNIQUE (user_id, idempotency_key)" in commerce_sql
    assert "stripe_session_id TEXT UNIQUE" in commerce_sql
    assert "event_id TEXT PRIMARY KEY" in commerce_sql