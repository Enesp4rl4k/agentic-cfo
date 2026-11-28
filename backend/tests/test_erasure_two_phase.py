"""Erasure is two-phase: ONE transaction for everything transactional (and the durable cleanup plan), then the
irreversible, retryable cleanup (files, caches, Redis).

Proves: a failing transactional step touches no file and no row; a failing cleanup is retried and never cancellable;
a request whose org id is gone never runs anything for "None"; Redis sweeps cannot reach another tenant; a live run is
not released; retries are capped and visible."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.database import Base
from app.models.erasure_record import OrgErasureRecord, OrgErasureRequest
from app.models.organization import Organization
from app.services import org_erasure as svc
from app.services.privacy import ephemeral, erasure_cleanup, erasure_flow
from app.services.privacy.ephemeral import AgentMemoryDeleteError
from tests.test_erasure_flow import ORG, _owner_company, _scheduled
from tests.test_org_erasure import _insert

T = Base.metadata.tables
UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def alerts(monkeypatch) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []

    async def fake(code: str, *, dedupe: str = "", detail: str = "") -> None:
        seen.append((code, dedupe))

    monkeypatch.setattr("app.services.operator_alerts.alert_in_own_session", fake)
    return seen


async def _company_with_file(client: Any, email: str, root: Path) -> tuple[dict[str, str], str, str, Path]:
    hdr, org, _ = await _owner_company(client, email)
    path = root / "uploads" / f"{org}-job" / "statement.csv"
    path.parent.mkdir(parents=True)
    path.write_text("ZZPII statement")
    async with client._maker() as db:
        await _insert(db, T["analysis_jobs"], "A", org_id=org, status="completed", file_path=str(path))
        await db.commit()
    rid, _ = await _scheduled(client, hdr)
    async with client._maker() as db:
        (await db.get(OrgErasureRequest, rid)).execute_after = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    return hdr, org, rid, path


async def _intact(client: Any, org: str) -> int:
    async with client._maker() as db:
        return int((await db.execute(select(func.count()).select_from(Organization).where(
            Organization.id == org, Organization.name != "[erased]"))).scalar_one())


async def _records(client: Any) -> int:
    async with client._maker() as db:
        return int((await db.execute(select(func.count()).select_from(OrgErasureRecord))).scalar_one())


# ── blocker 1: nothing irreversible before the commit ────────────────────────

async def test_a_failing_agent_memory_delete_deletes_no_file_and_no_row_and_cancel_keeps_the_company_whole(
    client, tmp_path: Path, monkeypatch, alerts
) -> None:
    hdr, org, rid, path = await _company_with_file(client, "tp1@example.com", tmp_path)

    async def boom(db, org_id):
        raise AgentMemoryDeleteError("x")

    monkeypatch.setattr("app.services.privacy.ephemeral._agent_memory_delete", boom)
    for _ in range(2):  # two hourly attempts
        async with client._maker() as db:
            assert (await erasure_flow.execute_due(db))["failed"] == 1
    assert path.exists(), "a file was deleted although the erasure failed"
    assert await _intact(client, org) == 1 and await _records(client) == 0
    async with client._maker() as db:
        req = await db.get(OrgErasureRequest, rid)
        assert (req.status, req.failure_code, req.attempts) == ("failed", "agent_memory_delete_failed", 2)
        assert req.cleanup_plan is None
    r = await client.post(f"{ORG}/{rid}/cancel", headers=hdr)  # the owner sees the failure and cancels
    assert r.status_code == 200 and path.exists() and await _intact(client, org) == 1  # whole company, files included


# ── blocker 1/2: after the commit the cleanup is durable, retried, never cancellable ─────────────────

async def test_a_cleanup_failure_after_the_commit_is_retried_and_the_request_is_never_cancellable(
    client, tmp_path: Path, monkeypatch, alerts
) -> None:
    _hdr, org, rid, path = await _company_with_file(client, "tp2@example.com", tmp_path)
    real = erasure_cleanup.run_cleanup
    calls: list[int] = []

    async def flaky(plan, root=None):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("volume unavailable")
        return await real(plan, root)

    monkeypatch.setattr("app.services.privacy.erasure_cleanup.run_cleanup", flaky)
    async with client._maker() as db:
        assert (await erasure_flow.execute_due(db))["cleanup_pending"] == 1
    assert await _intact(client, org) == 0 and path.exists()  # rows gone (committed), the file waits for its retry
    async with client._maker() as db:
        req = await db.get(OrgErasureRequest, rid)
        assert req.status == "cleanup_pending" and req.cleanup_plan["org_id"] == org and req.target_org_id is None
        assert req.failure_code == "cleanup_failed" and req.claimed_at is None
    async with client._maker() as db:  # the owner's account is erased with the company; the flow itself still refuses
        with pytest.raises(ValueError, match="cleanup_pending"):
            await erasure_flow.cancel(db, await db.get(OrgErasureRequest, rid), by_hash="h", decided_by=None, role="platform_operator")
        assert (await db.get(OrgErasureRequest, rid)).status == "cleanup_pending"  # never reported as cancelled
    assert ("job_failed", f"erasure:{rid}:cleanup_failed") in alerts
    async with client._maker() as db:
        assert (await erasure_flow.execute_due(db))["executed"] == 1  # the retry runs the stored plan only
    # the failed try, the retry of the stored plan, the final sweep's cleanup; no second proof record
    assert not path.exists() and len(calls) == 3 and await _records(client) == 1
    async with client._maker() as db:
        req = await db.get(OrgErasureRequest, rid)
        assert req.status == "executed" and req.cleanup_plan is None and req.post_commit_counts["_files"]["deleted"] >= 1


# ── blocker 2: a missing org id never runs anything ──────────────────────────

async def test_a_retry_without_an_org_id_finishes_from_the_proof_record_and_runs_nothing(
    client, tmp_path: Path, monkeypatch, alerts
) -> None:
    _hdr, _org, rid, _path = await _company_with_file(client, "tp3@example.com", tmp_path)
    async with client._maker() as db:
        assert (await erasure_flow.execute_due(db))["executed"] == 1
    # the reviewer's window: the erasure committed, then the request went back to `failed` with no org id
    async with client._maker() as db:
        req = await db.get(OrgErasureRequest, rid)
        req.status, req.target_org_id, req.execute_after, req.record_id = "failed", None, datetime.now(UTC) - timedelta(minutes=1), None
        await db.commit()

    async def never(*_a, **_k):
        raise AssertionError("something ran for a request without an organisation id")

    monkeypatch.setattr("app.services.privacy.erasure_cleanup.run_cleanup", never)
    monkeypatch.setattr("app.services.privacy.ephemeral.sweep_org_redis", never)
    monkeypatch.setattr(svc, "erase_org", never)
    monkeypatch.setattr(erasure_flow, "erase_org", never)
    async with client._maker() as db:
        assert (await erasure_flow.execute_due(db))["executed"] == 1
        req = await db.get(OrgErasureRequest, rid)
        assert req.status == "executed" and req.record_id is not None
    assert await _records(client) == 1  # no junk record


async def test_a_request_with_no_org_id_and_no_proof_record_is_blocked_and_alerted(client, alerts) -> None:
    _hdr, _org, _ = await _owner_company(client, "tp4@example.com")
    async with client._maker() as db:
        rid = await _insert(db, T["org_erasure_requests"], "A", target_org_id=None, status="failed", mode="anonymise", scope="org",
                            execute_after=datetime.now(UTC) - timedelta(minutes=1), attempts=1)
        await db.commit()
    async with client._maker() as db:
        assert (await erasure_flow.execute_due(db))["blocked"] == 1
        req = await db.get(OrgErasureRequest, rid)
        assert (req.status, req.blocked_reason) == ("blocked", "no_target")
    assert ("job_failed", f"erasure:{rid}:no_target") in alerts and await _records(client) == 0


@pytest.mark.parametrize("bad", [None, "None", "", "null", "abc", "1234", "x" * 36])
def test_every_guard_refuses_an_id_that_is_not_a_uuid(bad: Any) -> None:
    with pytest.raises(erasure_cleanup.InvalidTargetError):
        ephemeral._matcher(bad, [], [])
    with pytest.raises(erasure_cleanup.InvalidTargetError):
        ephemeral._matcher(UUID_A, [bad], [])
    with pytest.raises(erasure_cleanup.InvalidTargetError):
        ephemeral._matcher(UUID_A, [], [bad])
    with pytest.raises(erasure_cleanup.InvalidTargetError):
        ephemeral._memory_delete(bad, [], [])
    with pytest.raises(erasure_cleanup.InvalidTargetError):
        erasure_cleanup.build_plan(Path("."), bad, [], [], [], [])


async def test_erase_org_and_the_sweeps_refuse_a_bad_id_before_touching_anything(maker_db, tmp_path: Path, redis_fake) -> None:
    redis_fake.data.update({"cache:None": "a", f"x:{UUID_A}": "b"})
    for bad in (None, "None", ""):
        with pytest.raises(ValueError):
            await svc.erase_org(maker_db, bad, storage_root=tmp_path)  # type: ignore[arg-type]
        with pytest.raises(erasure_cleanup.InvalidTargetError):
            await ephemeral.sweep_org_redis(bad, [], [])  # type: ignore[arg-type]
    assert set(redis_fake.data) == {"cache:None", f"x:{UUID_A}"}
    assert (await maker_db.execute(select(func.count()).select_from(OrgErasureRecord))).scalar_one() == 0


async def test_the_redis_sweep_deletes_one_tenants_keys_and_no_others(redis_fake) -> None:
    job_a, user_a = "33333333-3333-4333-8333-333333333333", "44444444-4444-4444-8444-444444444444"
    mine = [f"company_context:{UUID_A}", f"cache:analytics:{UUID_A}:kpis", f"ceo:{job_a}", f"conv:{user_a}:s1"]
    theirs = [f"company_context:{UUID_B}", "cache:None:x", "None", "ceo:None", f"conv:{UUID_B}:s1", "conv:None:s", "plain"]
    for k in mine + theirs:
        redis_fake.data[k] = "v"
    counts = await ephemeral.sweep_org_redis(UUID_A, [user_a], [job_a])
    assert counts["redis_deleted"] == len(mine)
    assert set(redis_fake.data) == set(theirs)


# ── (a) a live run is not released; two erasures of one org cannot both run ──

async def test_a_live_erasure_keeps_renewing_its_claim_and_is_not_released(client, tmp_path: Path, monkeypatch) -> None:
    hdr, org, rid, _path = await _company_with_file(client, "tp5@example.com", tmp_path)
    monkeypatch.setattr(erasure_flow, "STALE_CLAIM", timedelta(seconds=0.6))
    monkeypatch.setattr(erasure_flow, "HEARTBEAT", timedelta(seconds=0.05))
    real = erasure_flow.erase_org
    seen: dict[str, Any] = {}

    async def slow(db, org_id, **kw):
        await asyncio.sleep(1.2)  # twice the stale limit: only the heartbeat keeps the claim fresh
        async with client._maker() as other:
            seen["counts"] = await erasure_flow.execute_due(other)  # another executor looks in
            seen["status"] = (await other.get(OrgErasureRequest, rid)).status
        r = await client.post(f"{ORG}/{rid}/cancel", headers=hdr)
        seen["cancel"] = r.status_code
        return await real(db, org_id, **kw)

    monkeypatch.setattr(erasure_flow, "erase_org", slow)
    async with client._maker() as executor:
        assert (await erasure_flow.execute_due(executor))["executed"] == 1
    assert seen["status"] == "executing" and seen["counts"]["failed"] == 0  # not released, not re-run
    assert seen["cancel"] == 409
    assert await _intact(client, org) == 0 and await _records(client) == 1


async def test_a_dead_workers_claim_is_released_and_the_erasure_runs_once(client, tmp_path: Path) -> None:
    _hdr, _org, rid, path = await _company_with_file(client, "tp6@example.com", tmp_path)
    async with client._maker() as db:
        assert await erasure_flow._claim(db, rid, datetime.now(UTC)) is True
        (await db.get(OrgErasureRequest, rid)).claimed_at = datetime.now(UTC) - erasure_flow.STALE_CLAIM - timedelta(minutes=1)
        await db.commit()
        assert (await erasure_flow.execute_due(db))["executed"] == 1
    assert await _records(client) == 1 and not path.exists()


async def test_two_requests_for_one_company_produce_one_erasure(client, tmp_path: Path) -> None:
    _hdr, org, rid, _path = await _company_with_file(client, "tp7@example.com", tmp_path)
    async with client._maker() as db:
        second = await _insert(db, T["org_erasure_requests"], "A", target_org_id=org, org_hash=svc.hash_id("org", org),
                               status="scheduled", mode="anonymise", scope="org", initiated_by="operator",
                               execute_after=datetime.now(UTC) - timedelta(minutes=1), attempts=0)
        await db.commit()
    async with client._maker() as db:
        counts = await erasure_flow.execute_due(db)
        assert counts["executed"] == 2 and counts["failed"] == 0
        assert {(await db.get(OrgErasureRequest, i)).status for i in (rid, second)} == {"executed"}
    assert await _records(client) == 1


# ── (b) retries are capped, alerted and visible ──────────────────────────────

async def test_failed_retries_are_capped_alerted_and_listed_for_the_owner(client, tmp_path: Path, monkeypatch, alerts) -> None:
    hdr, org, rid, path = await _company_with_file(client, "tp8@example.com", tmp_path)

    async def boom(db, org_id):
        raise AgentMemoryDeleteError("x")

    monkeypatch.setattr("app.services.privacy.ephemeral._agent_memory_delete", boom)
    async with client._maker() as db:
        await erasure_flow.execute_due(db)
    listed = (await client.get("/api/v1/privacy/erasure-requests", headers=hdr)).json()["data"]["requests"]
    row = next(r for r in listed if r["request_id"] == rid)
    assert row["status"] == "failed" and row["failure_code"] == "agent_memory_delete_failed" and row["cancellable"] is True
    async with client._maker() as db:
        (await db.get(OrgErasureRequest, rid)).attempts = erasure_flow.MAX_ATTEMPTS
        await db.commit()
    async with client._maker() as db:
        assert (await erasure_flow.execute_due(db))["blocked"] == 1
        req = await db.get(OrgErasureRequest, rid)
        assert (req.status, req.blocked_reason) == ("blocked", "retries_exhausted")
    assert ("job_failed", f"erasure:{rid}:retries_exhausted") in alerts and path.exists()
    async with client._maker() as db:
        assert (await erasure_flow.execute_due(db))["failed"] == 0  # it is not tried again
    assert await _intact(client, org) == 1


# ── fixtures local to the Redis / session tests ──────────────────────────────

class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def scan_iter(self, match: str = "*", count: int = 100) -> AsyncIterator[str]:
        for key in list(self.data):
            yield key

    async def delete(self, *keys: str) -> int:
        return sum(1 for k in keys if self.data.pop(k, None) is not None)


@pytest.fixture
def redis_fake(monkeypatch) -> _FakeRedis:
    fake = _FakeRedis()

    async def _get() -> _FakeRedis:
        return fake

    monkeypatch.setattr("app.core.redis_client.get_redis", _get)
    return fake


@pytest.fixture
async def maker_db():
    from tests.db_helpers import gecici_veritabani

    async with gecici_veritabani() as m, m() as db:
        yield db
