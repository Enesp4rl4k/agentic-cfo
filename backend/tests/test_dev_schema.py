"""Bir geliştiricinin eski veritabanı yeni kolonlarla açılabilmeli.

`create_all` makes missing tables and leaves existing ones alone, so a
developer's `aicfo_dev.db` created before `transactions.kdv_kurus` existed
would fail on the first query naming it. These tests build such a database —
an older `transactions` with rows in it — and check the startup sync repairs
it by adding, and only by adding.
"""
from __future__ import annotations

import sqlalchemy as sa

import app.main  # noqa: F401 — registers every model on Base.metadata
from app.core.dev_schema import sync_dev_schema
from app.database import Base


def _old_database(tmp_path) -> sa.Engine:
    """`transactions` as it was before the tax columns, with a row in it."""
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    old = sa.MetaData()
    sa.Table(
        "transactions", old,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("amount_kurus", sa.Integer, nullable=False),
        sa.Column("legacy_note", sa.Text, nullable=True),   # not in the model any more
    )
    old.create_all(engine)
    with engine.begin() as conn:
        conn.execute(old.tables["transactions"].insert().values(id="t1", job_id="j1", amount_kurus=100))
    return engine


def _columns(engine: sa.Engine, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def test_missing_nullable_columns_are_added(tmp_path) -> None:
    engine = _old_database(tmp_path)
    with engine.begin() as conn:
        result = sync_dev_schema(conn, Base.metadata)
    cols = _columns(engine, "transactions")
    assert {"kdv_kurus", "stopaj_kurus", "raw_text"} <= cols
    assert "transactions.kdv_kurus" in result.added


def test_existing_rows_survive_and_read_null_for_new_columns(tmp_path) -> None:
    engine = _old_database(tmp_path)
    with engine.begin() as conn:
        sync_dev_schema(conn, Base.metadata)
    with engine.connect() as conn:
        row = conn.execute(sa.text("select id, amount_kurus, kdv_kurus from transactions")).one()
    assert tuple(row) == ("t1", 100, None)


def test_a_column_with_a_server_default_is_added_with_it(tmp_path) -> None:
    """date_is_estimated is NOT NULL with server_default "0" — addable, and
    the existing row reads False, not an invented value."""
    engine = _old_database(tmp_path)
    with engine.begin() as conn:
        sync_dev_schema(conn, Base.metadata)
    with engine.connect() as conn:
        assert conn.execute(sa.text("select date_is_estimated from transactions")).scalar() == 0


def test_not_null_without_default_is_reported_not_forced(tmp_path) -> None:
    engine = _old_database(tmp_path)
    with engine.begin() as conn:
        result = sync_dev_schema(conn, Base.metadata)
    assert "transactions.type" in result.skipped
    assert "type" not in _columns(engine, "transactions")


def test_nothing_is_dropped(tmp_path) -> None:
    engine = _old_database(tmp_path)
    with engine.begin() as conn:
        sync_dev_schema(conn, Base.metadata)
    assert "legacy_note" in _columns(engine, "transactions")


def test_an_up_to_date_database_is_left_alone(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'new.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        result = sync_dev_schema(conn, Base.metadata)
    assert result.added == [] and result.skipped == []


def test_startup_runs_it_in_sqlite_mode() -> None:
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert "sync_dev_schema" in src
