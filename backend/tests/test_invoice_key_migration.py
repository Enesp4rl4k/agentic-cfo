"""Migration 065: old `doc:<number>` identities become `inv:` keys, everywhere, without losing a row.

The data functions take a plain connection, so they run here on a SQLite database built from the
models (the chain itself needs Postgres: CI's migrations job runs `upgrade`, drift and `downgrade`).
"""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main  # noqa: F401
from app.core import invoice_identity as live
from app.database import Base
from app.models.analysis_job import AnalysisJob
from app.models.transaction import Transaction
from app.services import ledger

_PATH = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "065_invoice_key_counterparty.py"
_spec = importlib.util.spec_from_file_location("m065", _PATH)
assert _spec and _spec.loader
m065 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m065)

NOW = datetime(2024, 3, 5, tzinfo=UTC)
ORG, OTHER = "org-mig-1", "org-mig-2"
JOB = "job-mig-1"


@pytest.fixture
def engine(tmp_path):
    eng = sa.create_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _ledger_row(conn, *, org=ORG, srid, direction="expense", cents=100_000, corrects=None, source_type="fingerprint",
                job=JOB, status="active", id_=None, created=NOW) -> str:
    id_ = id_ or str(uuid.uuid4())
    conn.execute(sa.text(
        "INSERT INTO canonical_transactions (id, org_id, source_type, source_record_id, source_job_id,"
        " transaction_date, date_is_estimated, amount_cents, currency, direction, category, ledger_status, basis,"
        " corrects_id, created_at, updated_at) VALUES (:id, :org, :st, :srid, :job, :d, 0, :c, 'TRY', :dir, 'cogs',"
        " :status, 'document', :corrects, :created, :created)"
    ), {"id": id_, "org": org, "st": source_type, "srid": srid, "job": job, "d": NOW, "c": cents, "dir": direction,
        "status": status, "corrects": corrects, "created": created})
    return id_


def _item(conn, *, org=ORG, document_id, counterparty, direction="payable", cents=100_000):
    conn.execute(sa.text(
        "INSERT INTO open_items (id, org_id, direction, instrument, document_id, counterparty, amount_cents,"
        " paid_cents, currency, issue_date, status, created_at) VALUES (:id, :org, :dir, 'invoice', :doc, :cp, :c,"
        " 0, 'TRY', :d, 'open', :now)"
    ), {"id": str(uuid.uuid4()), "org": org, "dir": direction, "doc": document_id, "cp": counterparty, "c": cents,
        "d": date(2024, 3, 1), "now": NOW})


def _override(conn, *, org=ORG, srid, category="rent"):
    conn.execute(sa.text(
        "INSERT INTO category_overrides (id, org_id, source_record_id, category, updated_at)"
        " VALUES (:id, :org, :srid, :cat, :now)"
    ), {"id": str(uuid.uuid4()), "org": org, "srid": srid, "cat": category, "now": NOW})


def _job(conn, *, job_id=JOB, org=ORG, status="completed"):
    conn.execute(AnalysisJob.__table__.insert().values(
        id=job_id, org_id=org, status=status, filename="f.csv", file_path="/f", file_type="csv",
    ))


def _tx(conn, *, job_id=JOB, document_id, counterparty, type_="expense", cents=100_000):
    conn.execute(Transaction.__table__.insert().values(
        id=str(uuid.uuid4()), job_id=job_id, amount_kurus=cents, currency="TRY", type=type_, category="cogs",
        transaction_date=NOW, date_is_estimated=False, document_id=document_id, counterparty=counterparty,
    ))


def _srids(conn, table="canonical_transactions", col="source_record_id", org=ORG) -> list[str]:
    return sorted(r[0] for r in conn.execute(sa.text(f"SELECT {col} FROM {table} WHERE org_id = :o"), {"o": org}))


def _state(engine) -> tuple[list[str], list[str], list[str]]:
    with engine.connect() as conn:
        return (_srids(conn), _srids(conn, "open_items", "document_id"), _srids(conn, "category_overrides"))


def _seed(engine) -> dict[str, str]:
    """A company as the old code left it (ids are the ledger rows' UUIDs)."""
    ids: dict[str, str] = {}
    with engine.begin() as conn:
        _job(conn)
        # Alfa's A-1: a ledger row, an open item, a kept override, and a closed-month correction pair.
        ids["alfa"] = _ledger_row(conn, srid="doc:A-1", cents=100_000)
        _item(conn, document_id="A-1", counterparty="Alfa Gıda A.Ş.")
        _override(conn, srid="doc:A-1", category="rent")
        _ledger_row(conn, srid="doc:A-1~k1-iptal", cents=-100_000, corrects=ids["alfa"], source_type="correction")
        _ledger_row(conn, srid="doc:A-1~k1-yeni", cents=100_000, corrects=ids["alfa"], source_type="correction")
        # A return: no open item, the job's own row names the counterparty.
        ids["iade"] = _ledger_row(conn, srid="doc:IADE-3", cents=-5_000)
        _tx(conn, document_id="IADE-3", counterparty="Beta Tekstil Ltd.", cents=-5_000)
        # Nobody names the counterparty: kept as it is.
        ids["nobody"] = _ledger_row(conn, srid="doc:C-9", cents=30_000)
        # A GİB number and a content fingerprint are not touched.
        ids["gib"] = _ledger_row(conn, srid="doc:GIB2024000000001", cents=70_000)
        ids["fp"] = _ledger_row(conn, srid="fp:abc#1", cents=900)
        # Another company with the same number keeps its own.
        ids["other"] = _ledger_row(conn, org=OTHER, srid="doc:A-1", cents=44_000, job="job-x")
        _item(conn, org=OTHER, document_id="A-1", counterparty="Gamma Ltd")
        # Merged by the old key: Beta's A-1 was dropped (only its job row remains).
        _tx(conn, document_id="A-1", counterparty="Beta Tekstil Ltd.", cents=250_000)
    return ids


def _figures(engine) -> dict[str, Any]:
    with engine.connect() as conn:
        money = conn.execute(sa.text(
            "SELECT org_id, direction, COUNT(*), SUM(amount_cents) FROM canonical_transactions"
            " GROUP BY org_id, direction ORDER BY 1, 2"
        )).all()
        items = conn.execute(sa.text(
            "SELECT org_id, direction, COUNT(*), SUM(amount_cents - paid_cents) FROM open_items"
            " GROUP BY org_id, direction ORDER BY 1, 2"
        )).all()
    return {"ledger": [tuple(r) for r in money], "items": [tuple(r) for r in items]}


def _read(engine, work):
    """Run an async reader (the app's own functions) against the migrated file."""
    async def run():
        eng = create_async_engine(f"sqlite+aiosqlite:///{engine.url.database}")
        try:
            async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                return await work(db)
        finally:
            await eng.dispose()

    return asyncio.run(run())


def test_every_place_the_old_identity_lived_is_rewritten_together(engine):
    ids = _seed(engine)
    with engine.begin() as conn:
        result = m065.rewrite_identities(conn)
    key = live.document_key(ORG, "A-1", "Alfa Gıda A.Ş.", "expense")
    assert key.startswith("inv:p:n")
    assert result["ledger_rows"] == 3 and result["correction_rows"] == 2 and result["overrides"] == 1
    assert result["open_items"] == 2        # Alfa's, and Gamma's in the other company
    with engine.connect() as conn:
        assert _srids(conn) == sorted([
            key, f"{key}~k1-iptal", f"{key}~k1-yeni",
            live.document_key(ORG, "IADE-3", "Beta Tekstil Ltd.", "expense"),
            "doc:C-9", "doc:GIB2024000000001", "fp:abc#1",
        ])
        assert _srids(conn, "category_overrides") == [key]
        assert _srids(conn, "open_items", "document_id") == [key]
        # The pointer between a correction and its row is the row's UUID: untouched, still right.
        pointed = conn.execute(sa.text(
            "SELECT corrects_id, source_record_id FROM canonical_transactions WHERE corrects_id IS NOT NULL"
        )).all()
        assert {p[0] for p in pointed} == {ids["alfa"]}
        assert all(p[1].startswith(key + "~k1-") for p in pointed)
        # The other company's identity is its own.
        assert _srids(conn, org=OTHER) == [live.document_key(OTHER, "A-1", "Gamma Ltd", "expense")]


def test_the_company_counts_the_same_before_and_after(engine):
    _seed(engine)
    before_figures = _figures(engine)
    before_summary = _read(engine, lambda db: ledger.ledger_summary(db, ORG))
    with engine.begin() as conn:
        m065.rewrite_identities(conn)
    assert _figures(engine) == before_figures
    after_summary = _read(engine, lambda db: ledger.ledger_summary(db, ORG))
    for field in ("rows", "revenue_cents", "expense_cents", "possible_duplicates", "months", "open_items"):
        assert after_summary[field] == before_summary[field], field
    assert before_summary["open_items"]["payable_cents"] == 100_000


def test_a_correction_still_belongs_to_its_row(engine):
    ids = _seed(engine)
    assert _read(engine, lambda db: ledger.effective_categories(db, ORG)) == {ids["alfa"]: "cogs"}
    with engine.begin() as conn:
        m065.rewrite_identities(conn)
    assert _read(engine, lambda db: ledger.effective_categories(db, ORG)) == {ids["alfa"]: "cogs"}


def test_running_it_twice_changes_nothing_more(engine):
    _seed(engine)
    with engine.begin() as conn:
        m065.rewrite_identities(conn)
    once = _state(engine)
    with engine.begin() as conn:
        again = m065.rewrite_identities(conn)
    assert _state(engine) == once
    assert not {k: v for k, v in again.items() if k in ("ledger_rows", "correction_rows", "overrides", "open_items")}


def test_a_row_with_no_counterparty_is_reported_not_guessed(engine):
    _seed(engine)
    with engine.begin() as conn:
        result = m065.rewrite_identities(conn)
    assert result["unattributed"] == 1                      # doc:C-9
    with engine.connect() as conn:
        assert "doc:C-9" in _srids(conn)


def test_documents_the_old_key_merged_are_counted_not_invented(engine):
    _seed(engine)
    with engine.begin() as conn:
        result = m065.rewrite_identities(conn)
    # Beta's A-1 (a purchase invoice) has a transaction row and no ledger row. ledger.backfill writes
    # it under its own key; the migration only counts it.
    assert result["merged_documents_missing_from_ledger"] == 1 and result["orgs_with_merged_documents"] == 1
    with engine.connect() as conn:
        count = conn.execute(sa.text("SELECT COUNT(*) FROM canonical_transactions WHERE org_id = :o"), {"o": ORG})
        assert count.scalar() == 7


def test_a_new_key_that_is_already_taken_leaves_the_old_row_alone(engine):
    """Two old rows that are one document once the number is folded: the second keeps its key."""
    with engine.begin() as conn:
        _job(conn)
        _ledger_row(conn, srid="doc:A-1", created=datetime(2024, 1, 1, tzinfo=UTC))
        _ledger_row(conn, srid="doc:a-1", created=datetime(2024, 1, 2, tzinfo=UTC))
        _item(conn, document_id="A-1", counterparty="Alfa Ltd")
        _item(conn, document_id="a-1", counterparty="Alfa Ltd")
        result = m065.rewrite_identities(conn)
    assert result["ledger_rows"] == 1 and result["kept_old_key_collision"] == 1
    assert result["open_items"] == 1 and result["items_kept_old_key_collision"] == 1
    with engine.connect() as conn:
        rows = [r[0] for r in conn.execute(sa.text("SELECT source_record_id FROM canonical_transactions"))]
        assert len(rows) == 2 and len(set(rows)) == 2           # no unique index touched, no row lost
        assert sum(r.startswith("inv:") for r in rows) == 1 and sum(r.startswith("doc:") for r in rows) == 1


def test_the_downgrade_puts_the_old_ids_back_and_never_collides(engine):
    _seed(engine)
    with engine.begin() as conn:
        # The row `ledger.backfill` wrote for Beta's A-1 after the first upgrade.
        _ledger_row(conn, srid=live.document_key(ORG, "A-1", "Beta Tekstil Ltd.", "expense"), cents=250_000,
                    created=datetime(2024, 3, 6, tzinfo=UTC))
        m065.rewrite_identities(conn)
    with engine.begin() as conn:
        result = m065.restore_identities(conn)
    with engine.connect() as conn:
        ids = _srids(conn)
    assert {"doc:A-1", "doc:A-1~k1-iptal", "doc:A-1~k1-yeni", "doc:IADE-3"} <= set(ids)
    # Two suppliers' A-1: one takes the old key, the other keeps its own rather than collide.
    assert sum(i.startswith("inv:") for i in ids) == 1 and result["kept_new_key_collision"] >= 1
    assert len(ids) == len(set(ids)) == 8
    state = _state(engine)
    assert state[2] == ["doc:A-1"] and state[1] == ["A-1"]


def test_up_down_up_lands_where_up_did(engine):
    _seed(engine)
    with engine.begin() as conn:
        m065.rewrite_identities(conn)
    up = _state(engine)
    with engine.begin() as conn:
        m065.restore_identities(conn)
    with engine.begin() as conn:
        m065.rewrite_identities(conn)
    assert _state(engine) == up


def test_decisions_are_counted_never_rewritten(engine):
    _seed(engine)
    with engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO decisions (id, org_id, kind, target_type, target_id, outcome, decided_via, decided_at,"
            " evidence_refs) VALUES ('d1', :o, 'category_correction', 'ledger_row', 'doc:A-1', 'ok', 'human', :now,"
            " '[]')"
        ), {"o": ORG, "now": NOW})
        result = m065.rewrite_identities(conn)
        assert result["decisions_with_old_ids"] == 1
        assert conn.execute(sa.text("SELECT target_id FROM decisions")).scalar() == "doc:A-1"   # append-only


def test_an_organisation_with_nothing_to_rewrite_is_a_no_op(engine):
    with engine.begin() as conn:
        assert m065.rewrite_identities(conn).get("ledger_rows", 0) == 0
        assert m065.restore_identities(conn).get("ledger_rows", 0) == 0


# ── the migration's frozen copy is the live definition ───────────────────────────────────────

_NAMES = [None, "", "Alfa Gıda A.Ş.", "ALFA GIDA AS", "Beta Tekstil Ltd. Şti.", "İPEK Limited Şirketi", "A.Ş.",
          "Alfa 1234567890", "Kaya 10000000146", "Yıldız, Tekstil", "3M Türkiye A.Ş.", "Ltd"]
_NUMBERS = ["A-1", "a-1", "doc:a-1", "2024/15", " 12 ", "GIB2024000000050", "gib2024000000050",
            "f47ac10b-58cc-4372-a567-0e02b2c3d479", "F47AC10B-58CC-4372-A567-0E02B2C3D479", "FT/abc2024000000001", "x"]


@pytest.mark.parametrize("number", _NUMBERS)
@pytest.mark.parametrize("direction", ["income", "expense", None, "other"])
def test_the_migrations_key_equals_the_live_key(number, direction):
    canonical = live.canonical_invoice_id(number) or number
    assert m065._canonical_number(number) == canonical
    for name in _NAMES:
        assert m065._document_key("o1", canonical, name, direction) == live.document_key("o1", number, name, direction)
        assert m065._party_token("o1", name) == live.party_token("o1", name)
        assert m065._normalise_party(name) == live.normalise_party(name)
