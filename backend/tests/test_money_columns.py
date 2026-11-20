"""Every money column holds 64-bit kuruş.

Amounts are integer kuruş (CLAUDE.md), and every such column was a 32-bit
INTEGER: on Postgres a single row above ₺21,474,836.47 overflowed. Migration
056 widened them; this keeps a new `*_kurus` / `*_cents` column from arriving
as INTEGER again.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import BigInteger

import app.main  # noqa: F401 — registers every model on the metadata
from app.database import Base

MONEY_SUFFIXES = ("_kurus", "_cents")


def _money_columns():
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if column.name.endswith(MONEY_SUFFIXES):
                yield table.name, column


def test_the_walk_finds_the_money_columns() -> None:
    names = {(t, c.name) for t, c in _money_columns()}
    assert ("transactions", "amount_kurus") in names
    assert ("open_items", "paid_cents") in names


def test_every_money_column_is_bigint() -> None:
    narrow = [
        f"{t}.{c.name} ({c.type})" for t, c in _money_columns()
        if not isinstance(c.type, BigInteger)
    ]
    assert not narrow, (
        "32-bit para kolonu — BigInteger kullanın ve migration ekleyin:\n  " + "\n  ".join(narrow)
    )


def test_the_migration_widens_every_money_column_the_models_have() -> None:
    """Every column 056 widens exists; a typo would make the migration fail on Postgres only."""
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "056_money_bigint.py"
    spec = importlib.util.spec_from_file_location("m056", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    widened = {(t, c) for t, c, _ in module.MONEY_COLUMNS}
    in_models = {(t, c.name) for t, c in _money_columns()}
    assert widened <= in_models
