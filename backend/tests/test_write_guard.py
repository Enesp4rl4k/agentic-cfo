"""Every write of company data passes the erasure tombstone (app/services/privacy/write_guard.py): proven by structure.

* every organisation-scoped table (the erasure's own derived scope) resolves to its organisation, and an INSERT, an
  UPDATE and an ORM add for an erased organisation are refused there, table by table: a new org-scoped table is
  covered or fails here by name;
* a DELETE is never refused; the erasure's own writes (exempt) are not;
* every Redis write call in app/ checks the tombstone first (`redis_write_allowed` / `org_erased_now`) or is listed in
  `REDIS_EXEMPT` with the reason: a new Redis write of company data without the check fails here by file and function.
"""
from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete, insert, update

import app.models  # noqa: F401
from app.database import Base
from app.models.erasure_record import OrgErasureRecord
from app.services.privacy import write_guard
from app.services.privacy.tombstone import OrgErasedError, org_hash
from tests.db_helpers import gecici_veritabani
from tests.test_org_erasure import _insert

APP = Path(__file__).resolve().parents[1] / "app"
T = Base.metadata.tables
SCOPE = write_guard.covered_tables()


@pytest_asyncio.fixture
async def maker():
    async with gecici_veritabani() as m:
        yield m


async def _erased_company(db: Any) -> str:
    org = str(uuid.uuid4())
    with write_guard.exempt(db):
        await _insert(db, T["organizations"], "A", id=org, slug=f"wg-{org[:8]}", is_active=False, is_demo_guest=False,
                      country_code="TR", base_currency="TRY", locale="tr-TR", plan="free", subscription_plan="free",
                      subscription_status="inactive", max_members=5, max_jobs_per_month=5, regional_packs=[])
        db.add(OrgErasureRecord(seq=1, org_hash=org_hash(org), mode="anonymise", executed_at=datetime.now(UTC),
                                counts={}, prev_hash="0" * 64, record_hash="x" * 64))
        await db.commit()
    return org


async def _parent_chain(db: Any, org: str, table: str) -> dict[str, Any]:
    """The values that tie a row of `table` to `org`: its own org_id, or a parent row (created) it links to."""
    how = SCOPE[table]
    if how == "org_id":
        return {"org_id": org}
    column, target = how.split(" -> ")
    parent = target.split(".")[0]
    with write_guard.exempt(db):
        parent_values = await _parent_chain(db, org, parent)
        pid = await _insert(db, T[parent], "A", **parent_values)
        await db.commit()
    return {column: pid}


def test_every_org_scoped_table_resolves_to_its_organisation() -> None:
    from app.services.org_erasure import derive_scope

    assert set(SCOPE) == set(derive_scope()), "the guard and the erasure must cover the same tables"
    unresolved = sorted(t for t, how in SCOPE.items() if how == "unresolved")
    assert not unresolved, f"org-scoped tables a write to which cannot be tied to an organisation: {unresolved}"
    assert all(why.strip() for why in write_guard.EXEMPT_TABLES.values())
    assert set(write_guard.EXEMPT_TABLES) <= set(SCOPE), "an exempt table that is not organisation-scoped"
    assert write_guard.installed()
    for entry in ("app/main.py", "app/worker.py"):
        assert "_write_guard.install()" in (APP.parent / entry).read_text(encoding="utf-8"), entry


@pytest.mark.parametrize("table", sorted(t for t, how in SCOPE.items() if not how.startswith("exempt")))
async def test_inserts_updates_and_orm_adds_for_an_erased_organisation_are_refused(maker, table: str) -> None:
    async with maker() as db:
        org = await _erased_company(db)
        tie = await _parent_chain(db, org, table)
        t = T[table]
        with pytest.raises(OrgErasedError):
            await db.execute(insert(t).values(**tie))
        await db.rollback()
        col = next(iter(tie))
        with pytest.raises(OrgErasedError):
            await db.execute(update(t).where(t.c[col] == tie[col]).values(**{col: tie[col]}))
        await db.rollback()
        mapper = next((m for m in Base.registry.mappers if getattr(m.class_, "__table__", None) is t), None)
        if mapper is not None:
            obj = mapper.class_()
            for k, v in tie.items():
                setattr(obj, k, v)
            db.add(obj)
            with pytest.raises(OrgErasedError):
                await db.flush()
            await db.rollback()
        await db.execute(delete(t).where(t.c[col] == tie[col]))  # removing is never refused
        await db.rollback()


async def test_a_live_organisation_writes_and_the_erasure_itself_is_exempt(maker) -> None:
    async with maker() as db:
        live = str(uuid.uuid4())
        await _insert(db, T["in_app_notifications"], "A", org_id=live)  # no tombstone: allowed
        erased = await _erased_company(db)
        with write_guard.exempt(db):
            await _insert(db, T["in_app_notifications"], "A", org_id=erased)
        await db.commit()


# ── Redis ─────────────────────────────────────────────────────────────────────

GUARDS = ("redis_write_allowed", "org_erased_now")
REDIS_WRITES = {"set", "setex", "hset", "mset", "lpush", "rpush", "sadd", "zadd", "xadd"}
RECEIVERS = {"redis", "pool", "client", "r", "_redis"}

# file:function -> why the write needs no tombstone check (no company data, or keyed by something the erasure
# sweeps and expires by itself).
REDIS_EXEMPT = {
    "agents/orchestration/proactive_alerts.py:_set_cooldown": "a cooldown flag (`1`): no company data",
    "api/analysis.py:_idempotency_seized": "an idempotency lock: no company data",
    "core/distributed_lock.py:distributed_lock": "a lock token: no company data",
    "core/heartbeat.py:beat": "a worker heartbeat: no company data",
    "scheduler.py:_exclusive": "the scheduler's lock (the write is in its inner `_run`): no company data",
    "scheduler.py:_run": "the scheduler's lock: no company data",
    "services/sso.py:_save_state": "a sign-in state of a person, minutes; no company data",
    "services/tcmb_macro.py:_save_redis_cache": "public central-bank figures: no company data",
    "services/benchmark.py:_set_cached": "sector benchmarks: no company data",
    "services/conversation_memory.py:append_turn": "chat history keyed by person (conv:<user>:...): erased with the "
                                                   "person and by the erasure's Redis sweep of its members; 7 days",
    "api/alerts.py:acknowledge_alert": "an acknowledgement keyed by job (ack:<job>:...): the erasure's Redis sweep "
                                       "matches the organisation's job ids; no company figures; a member's request "
                                       "(no member of an erased company can sign in)",
    "api/efatura.py:sync_efatura": "invoices of a request being queued, keyed by job, 1 hour: a member's request "
                                   "(no member of an erased company can sign in)",
    "worker.py:enqueue_semantic_rebuild_job": "a lock: no company data",
    "worker.py:enqueue_maintenance_job": "a lock: no company data",
    "worker.py:enqueue_ceo_analysis": "the `pending` marker of a job just queued: no company data",
    "worker.py:record_ceo_job_owner": "who owns a CEO job (ids only): no company figures",
}


def _redis_write_sites() -> list[tuple[str, str, bool]]:
    """(file, enclosing function, whether that function checks the tombstone) for every Redis write call in app/."""
    out: list[tuple[str, str, bool]] = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            src = ast.unparse(fn)
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in REDIS_WRITES):
                    continue
                recv = node.func.value
                name = recv.attr if isinstance(recv, ast.Attribute) else getattr(recv, "id", "")
                if name not in RECEIVERS or not node.args:
                    continue
                out.append((rel, fn.name, any(g in src for g in GUARDS)))
    return out


def test_every_redis_write_of_company_data_checks_the_tombstone_or_is_exempt_with_a_reason() -> None:
    sites = _redis_write_sites()
    assert len(sites) >= 10, "the scan found too few Redis writes: the pattern no longer matches the code"
    unguarded = sorted({f"{f}:{fn}" for f, fn, guarded in sites if not guarded} - REDIS_EXEMPT.keys())
    assert not unguarded, (
        f"Redis writes without the erasure check: {unguarded}. Call privacy.tombstone.redis_write_allowed(<org id or "
        "key>) right before the write, or add the site to REDIS_EXEMPT with the reason it holds no company data."
    )
    stale = sorted(REDIS_EXEMPT.keys() - {f"{f}:{fn}" for f, fn, _ in sites})
    assert not stale, f"REDIS_EXEMPT names sites that no longer write to Redis: {stale}"
    assert all(REDIS_EXEMPT.values())


async def test_a_redis_write_naming_an_erased_organisation_is_refused(maker, monkeypatch) -> None:
    from app.services.privacy import tombstone

    erased, live = str(uuid.uuid4()), str(uuid.uuid4())

    async def fake(org: str | None) -> bool:
        return org == erased

    monkeypatch.setattr(tombstone, "org_erased_now", fake)
    assert await tombstone.redis_write_allowed(f"company_context:{erased}") is False
    assert await tombstone.redis_write_allowed(erased.upper()) is False
    assert await tombstone.redis_write_allowed(f"analytics:{live}:monthly") is True
    assert await tombstone.redis_write_allowed("scheduler:lock:x", None) is True
