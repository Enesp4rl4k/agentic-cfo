"""The decision record: append-only, consistent, in the caller's transaction, tenant-scoped."""
from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, delete, inspect, select, update
from sqlalchemy.exc import IntegrityError

from app.database import Base
from app.models.decision import AppendOnlyError, Decision, DecisionKind
from app.services import decisions as svc
from app.services.decisions import DecisionError, record_decision
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.db_helpers import gecici_oturum, gecici_veritabani

ORG = "org-a"
USER = "user-1"


def human(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "org_id": ORG, "kind": DecisionKind.CATEGORY_CORRECTION, "target_type": "ledger_row",
        "target_id": "row-1", "outcome": "recategorised", "decided_via": "human", "decided_by": USER,
    }
    return base | over


@pytest_asyncio.fixture
async def maker():
    async with gecici_veritabani() as m:
        yield m


# ── Writing ──────────────────────────────────────────────────────────────────

async def test_a_decision_is_stored_with_everything_it_was_given() -> None:
    async with gecici_oturum() as db:
        at = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)
        row = await record_decision(
            db, **human(
                reason="vendor is a software supplier", decided_at=at,
                evidence_refs=[{"type": "document", "id": "d1"}, {"type": "open_item", "id": "oi1"}],
                before={"category": "other", "amount_cents": 12050},
                after={"category": "software", "amount_cents": 12050},
            ),
        )
        await db.commit()
        got = (await db.execute(select(Decision))).scalar_one()
        assert got.id == row.id and got.kind == "category_correction" and got.decided_via == "human"
        assert got.evidence_refs == [{"type": "document", "id": "d1"}, {"type": "open_item", "id": "oi1"}]
        assert got.after == {"category": "software", "amount_cents": 12050} and got.reason
        assert got.decided_at.replace(tzinfo=UTC) == at


async def test_decided_at_defaults_to_now_and_a_naive_time_is_refused() -> None:
    async with gecici_oturum() as db:
        row = await record_decision(db, **human())
        assert abs((row.decided_at.replace(tzinfo=UTC) - datetime.now(UTC)).total_seconds()) < 30
        with pytest.raises(DecisionError, match="timezone-aware"):
            await record_decision(db, **human(decided_at=datetime(2026, 1, 1)))


@pytest.mark.parametrize(
    ("via", "by", "rule", "ok"),
    [
        ("human", USER, None, True), ("human", None, None, False), ("human", USER, "r1", False),
        ("rule", None, "r1", True), ("rule", None, None, False), ("rule", USER, "r1", False),
        ("system", None, None, True), ("system", USER, None, False), ("system", None, "r1", False),
        ("robot", None, None, False),
    ],
)
async def test_decided_via_decided_by_rule_id_must_agree(via: str, by: str | None, rule: str | None, ok: bool) -> None:
    async with gecici_oturum() as db:
        call = record_decision(db, **human(decided_via=via, decided_by=by, rule_id=rule))
        if ok:
            assert (await call).decided_via == via
        else:
            with pytest.raises(DecisionError):
                await call
            assert (await db.execute(select(Decision))).first() is None  # nothing was written


async def test_unknown_kind_and_malformed_inputs_are_refused() -> None:
    async with gecici_oturum() as db:
        with pytest.raises(DecisionError):
            await record_decision(db, **human(kind="whim"))
        with pytest.raises(DecisionError, match="evidence_refs"):
            await record_decision(db, **human(evidence_refs=[{"type": "document"}]))
        with pytest.raises(DecisionError, match="integer cents"):
            await record_decision(db, **human(after={"amount_cents": 12.5}))
        with pytest.raises(DecisionError, match="integer cents"):
            await record_decision(db, **human(before={"lines": [{"paid_kurus": "100"}]}))
        with pytest.raises(DecisionError, match="small"):
            await record_decision(db, **human(after={"note": "x" * 5000}))
        with pytest.raises(DecisionError, match="required"):
            await record_decision(db, **human(outcome=""))
        # a string, or a float outside a money key, is fine
        await record_decision(db, **human(after={"confidence": 0.93, "amount_cents": None}))


async def test_the_database_enforces_the_rule_id_pairing_too() -> None:
    async with gecici_oturum() as db:
        db.add(Decision(org_id=ORG, kind="x", target_type="t", target_id="1", outcome="o",
                        decided_via="rule", rule_id=None, evidence_refs=[]))
        with pytest.raises(IntegrityError):
            await db.flush()


# ── Append-only ──────────────────────────────────────────────────────────────

async def test_there_is_no_update_or_delete_path() -> None:
    assert not [n for n in dir(svc) if n.startswith(("update_", "delete_", "remove_", "edit_"))]
    async with gecici_oturum() as db:
        row = await record_decision(db, **human())
        row_id = row.id
        await db.commit()

        row.outcome = "changed"  # ORM update
        with pytest.raises(AppendOnlyError):
            await db.flush()
        await db.rollback()

        await db.delete(await db.get(Decision, row_id))  # ORM delete
        with pytest.raises(AppendOnlyError):
            await db.flush()
        await db.rollback()

        with pytest.raises(AppendOnlyError):  # ORM-enabled bulk statements
            await db.execute(update(Decision).values(outcome="x"))
        with pytest.raises(AppendOnlyError):
            await db.execute(delete(Decision))
        await db.rollback()

        assert (await db.execute(select(Decision.outcome))).scalar_one() == "recategorised"


# ── Supersede chains ─────────────────────────────────────────────────────────

async def test_a_chain_is_followed_newest_first_and_only_one_may_replace_a_decision() -> None:
    async with gecici_oturum() as db:
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        first = await record_decision(db, **human(outcome="a", decided_at=t0))
        second = await record_decision(db, **human(outcome="b", supersedes_id=first.id,
                                                    decided_at=datetime(2026, 1, 2, tzinfo=UTC)))
        third = await record_decision(db, **human(outcome="c", supersedes_id=second.id, decided_via="system",
                                                   decided_by=None, decided_at=datetime(2026, 1, 3, tzinfo=UTC)))
        other = await record_decision(db, **human(target_id="row-2", outcome="z"))
        await db.commit()

        for start in (first, second, third):
            assert [d.id for d in await svc.decision_chain(db, ORG, start.id)] == [third.id, second.id, first.id]
        assert [d.id for d in await svc.decision_chain(db, ORG, other.id)] == [other.id]
        assert await svc.decision_chain(db, "org-b", first.id) == []

        rows, total = await svc.list_decisions(db, ORG)
        assert [r.id for r in rows] == [other.id, third.id, second.id, first.id] and total == 4
        standing, n = await svc.list_decisions(db, ORG, current_only=True)
        assert {r.id for r in standing} == {third.id, other.id} and n == 2
        assert await svc.superseded_ids(db, ORG, [first.id, third.id]) == {first.id: second.id}

        with pytest.raises(DecisionError, match="already superseded"):
            await record_decision(db, **human(outcome="fork", supersedes_id=first.id))


async def test_supersede_must_stay_in_the_org_and_on_the_target() -> None:
    async with gecici_oturum() as db:
        first = await record_decision(db, **human())
        with pytest.raises(DecisionError, match="this organisation"):
            await record_decision(db, **human(org_id="org-b", supersedes_id=first.id))
        with pytest.raises(DecisionError, match="same target"):
            await record_decision(db, **human(target_id="row-9", supersedes_id=first.id))
        with pytest.raises(DecisionError, match="this organisation"):
            await record_decision(db, **human(supersedes_id=str(uuid.uuid4())))


async def test_list_filters_and_paging() -> None:
    async with gecici_oturum() as db:
        for i in range(5):
            await record_decision(db, **human(target_id=f"r{i}", decided_at=datetime(2026, 1, 1 + i, tzinfo=UTC)))
        await record_decision(db, **human(kind=DecisionKind.PLAN_CHANGE, target_type="open_item", target_id="oi"))
        await record_decision(db, **human(org_id="org-b", target_id="r0"))
        await db.commit()
        rows, total = await svc.list_decisions(db, ORG, kind="category_correction", limit=2, offset=1)
        assert total == 5 and [r.target_id for r in rows] == ["r3", "r2"]
        rows, total = await svc.list_decisions(db, ORG, target_type="open_item", target_id="oi")
        assert total == 1 and rows[0].kind == "plan_change"
        assert (await svc.list_decisions(db, "org-b"))[1] == 1


# ── The caller's transaction ─────────────────────────────────────────────────

async def test_the_decision_commits_and_rolls_back_with_the_callers_transaction(maker) -> None:
    async with maker() as db:
        await record_decision(db, **human(outcome="rolled-back"))
        await db.rollback()
    async with maker() as db:
        assert (await db.execute(select(Decision))).first() is None

    async with maker() as writer, maker() as reader:
        await record_decision(writer, **human(outcome="pending"))
        assert (await reader.execute(select(Decision))).first() is None  # flushed, not committed
        await writer.commit()
        assert (await reader.execute(select(Decision.outcome))).scalar_one() == "pending"

    async with maker() as db:  # a failure after the record takes the record with it
        with pytest.raises(RuntimeError):
            await record_decision(db, **human(outcome="doomed"))
            raise RuntimeError("the change itself failed")
        await db.rollback()
    async with maker() as db:
        assert [r for r in (await db.execute(select(Decision.outcome))).scalars() if r == "doomed"] == []


# ── Read endpoint ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def test_the_endpoint_lists_only_the_callers_organisation(client) -> None:
    a, org_a, _ = await kullanici(client, "a@example.com")
    b, org_b, _ = await kullanici(client, "b@example.com")
    assert org_a != org_b
    async with client._maker() as db:
        first = await record_decision(db, **human(org_id=org_a, target_id="x", outcome="one"))
        await record_decision(db, **human(org_id=org_a, target_id="x", outcome="two", supersedes_id=first.id))
        await record_decision(db, **human(org_id=org_a, kind="plan_change", target_type="open_item",
                                          target_id="oi", outcome="approved"))
        await record_decision(db, **human(org_id=org_b, target_id="x", outcome="secret-b"))
        await db.commit()

    r = await client.get("/api/v1/decision-records", headers=a)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meta"] == {"total": 3, "limit": 50, "offset": 0} and body["error"] is None
    assert "secret-b" not in r.text
    by_outcome = {d["outcome"]: d for d in body["data"]}
    assert by_outcome["one"]["superseded_by_id"] == by_outcome["two"]["id"]
    assert by_outcome["two"]["supersedes_id"] == first.id

    only = (await client.get("/api/v1/decision-records?kind=plan_change", headers=a)).json()
    assert [d["outcome"] for d in only["data"]] == ["approved"]
    cur = (await client.get("/api/v1/decision-records?target_id=x&current_only=true", headers=a)).json()
    assert [d["outcome"] for d in cur["data"]] == ["two"]
    page = (await client.get("/api/v1/decision-records?limit=1&offset=1", headers=a)).json()
    assert len(page["data"]) == 1 and page["meta"]["total"] == 3
    assert (await client.get("/api/v1/decision-records?limit=0", headers=a)).status_code == 422

    mine_b = (await client.get("/api/v1/decision-records", headers=b)).json()
    assert [d["outcome"] for d in mine_b["data"]] == ["secret-b"]


async def test_the_endpoint_needs_a_signed_in_member_of_an_organisation(client) -> None:
    assert (await client.get("/api/v1/decision-records")).status_code in (401, 403)
    h, _, _ = await kullanici(client, "solo@example.com", attach_org=False)
    assert (await client.get("/api/v1/decision-records", headers=h)).status_code == 400
    assert not [r for r in client._transport.app.routes  # type: ignore[attr-defined]
                if getattr(r, "path", "") == "/api/v1/decision-records"
                and r.methods - {"GET", "HEAD"}]  # read-only: no write verb on the path


# ── Migration ────────────────────────────────────────────────────────────────

def _migration() -> Any:
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "064_decisions_table.py"
    spec = importlib.util.spec_from_file_location("m064", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_round_trips_and_matches_the_model(tmp_path: Path) -> None:
    mig = _migration()
    assert mig.down_revision == "063_ledger_correction_link"
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")

    def run(fn: Any) -> None:
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            fn()

    def shape() -> tuple[dict[str, Any], set[tuple[str, tuple[str, ...], bool]]]:
        insp = inspect(engine)
        cols = {c["name"]: (str(c["type"]), c["nullable"]) for c in insp.get_columns("decisions")}
        idx = {(i["name"] or "", tuple(i["column_names"]), bool(i["unique"])) for i in insp.get_indexes("decisions")}
        return cols, idx

    run(mig.upgrade)
    migrated = shape()
    assert "decisions" in inspect(engine).get_table_names()
    run(mig.downgrade)
    assert "decisions" not in inspect(engine).get_table_names()
    run(mig.upgrade)
    assert shape() == migrated

    model = Base.metadata.tables["decisions"]
    cols, idx = migrated
    assert set(cols) == {c.name for c in model.columns}
    assert {n: nullable for n, (_, nullable) in cols.items()} == {c.name: c.nullable for c in model.columns}
    assert idx == {(i.name or "", tuple(c.name for c in i.columns), bool(i.unique)) for i in model.indexes}
    assert {c.name for c in model.constraints if c.name} == {"ck_decisions_decided_via", "ck_decisions_rule_id"}


def test_the_migration_chains_from_the_single_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[1]
    cfg = Config()
    cfg.set_main_option("script_location", str(root / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["064_decisions_table"] or len(script.get_heads()) == 1
    assert script.get_revision("064_decisions_table").down_revision == "063_ledger_correction_link"
