"""Cancel and the hourly executor race on one status column: exactly one wins, and the loser changes nothing.

The session factory keeps `expire_on_commit=False`, so an executor holding an instance loaded before the owner pressed
Cancel sees a stale `scheduled`. These tests interleave the two in both orders and prove the invariants:
cancelled => no row was deleted; executed => cancel reports failure, never success.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from app.models.decision import Decision, DecisionKind
from app.models.erasure_record import OrgErasureRecord, OrgErasureRequest
from app.models.organization import Organization
from app.services import org_erasure as org_svc
from app.services.privacy import erasure_flow
from app.services.privacy.ephemeral import AgentMemoryDeleteError
from tests.test_erasure_flow import ORG, _owner_company, _scheduled


async def _due(client: Any, rid: str) -> None:
    async with client._maker() as db:
        (await db.get(OrgErasureRequest, rid)).execute_after = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()


async def _intact(client: Any, org: str) -> int:
    """1 while the organisation row is still the real one, 0 once it is erased."""
    async with client._maker() as db:
        return int((await db.execute(select(func.count()).select_from(Organization).where(
            Organization.id == org, Organization.name != "[erased]"))).scalar_one())


async def test_cancel_before_the_claim_wins_even_when_the_executor_holds_a_stale_row(client) -> None:
    hdr, org, _ = await _owner_company(client, "race1@example.com")
    rid, _ = await _scheduled(client, hdr)
    await _due(client, rid)
    async with client._maker() as executor:
        stale = await executor.get(OrgErasureRequest, rid)  # loaded while still `scheduled`
        assert stale.status == erasure_flow.SCHEDULED
        r = await client.post(f"{ORG}/{rid}/cancel", headers=hdr)  # the owner cancels in another session
        assert r.status_code == 200 and r.json()["data"]["status"] == "cancelled"
        outcome = await erasure_flow.run_request(executor, stale)  # the executor still believes it is scheduled
        assert outcome == {"claimed": False, "status": "cancelled"}
        assert (await erasure_flow.execute_due(executor))["executed"] == 0
    assert await _intact(client, org) == 1  # zero rows deleted, the company is intact
    async with client._maker() as db:
        assert (await db.get(OrgErasureRequest, rid)).status == "cancelled"
        assert (await db.execute(select(func.count()).select_from(OrgErasureRecord))).scalar_one() == 0


async def test_cancel_after_the_claim_is_refused_and_the_erasure_completes(client, monkeypatch) -> None:
    hdr, org, _ = await _owner_company(client, "race2@example.com")
    rid, _ = await _scheduled(client, hdr)
    await _due(client, rid)
    seen: dict[str, Any] = {}
    real = erasure_flow.erase_org

    async def erase_while_owner_cancels(db, org_id, **kw):  # the claim is committed; the owner presses Cancel now
        r = await client.post(f"{ORG}/{rid}/cancel", headers=hdr)
        seen["status"], seen["detail"] = r.status_code, r.json().get("detail") or r.text
        return await real(db, org_id, **kw)

    monkeypatch.setattr(erasure_flow, "erase_org", erase_while_owner_cancels)
    async with client._maker() as executor:
        assert (await erasure_flow.execute_due(executor))["executed"] == 1
    assert seen["status"] == 409 and "çalış" in seen["detail"]  # cancel reports failure, never success
    assert await _intact(client, org) == 0  # the company really is erased
    async with client._maker() as db:
        req = await db.get(OrgErasureRequest, rid)
        assert req.status == "executed" and req.cancelled_at is None
        outcomes = [d.outcome for d in (await db.execute(
            select(Decision).where(Decision.kind == DecisionKind.ERASURE))).scalars()]
        assert "cancelled" not in outcomes


async def test_two_executors_cannot_both_claim_one_request(client) -> None:
    hdr, _, _ = await _owner_company(client, "race3@example.com")
    rid, _ = await _scheduled(client, hdr)
    await _due(client, rid)
    now = datetime.now(UTC)
    async with client._maker() as one, client._maker() as two, client._maker() as three:
        assert await erasure_flow._claim(one, rid, now) is True
        assert await erasure_flow._claim(two, rid, now) is False
        req = await three.get(OrgErasureRequest, rid)
        with pytest.raises(ValueError):
            await erasure_flow.cancel(three, req, by_hash="h", decided_by=None, role="owner")


async def test_a_failed_agent_memory_delete_aborts_the_erasure_and_leaves_a_visible_retryable_state(
    client, monkeypatch
) -> None:
    hdr, org, _ = await _owner_company(client, "race4@example.com")
    rid, _ = await _scheduled(client, hdr)
    await _due(client, rid)

    async def boom(db, org_id):
        raise AgentMemoryDeleteError("x")

    monkeypatch.setattr("app.services.privacy.ephemeral._agent_memory_delete", boom)
    async with client._maker() as executor:
        counts = await erasure_flow.execute_due(executor)
    assert counts["failed"] == 1 and counts["executed"] == 0
    assert await _intact(client, org) == 1  # nothing partial: the whole erasure rolled back
    async with client._maker() as db:
        req = await db.get(OrgErasureRequest, rid)
        assert (req.status, req.failure_code) == ("failed", "agent_memory_delete_failed")
        assert req.target_org_id == org  # still retryable
        assert (await db.execute(select(func.count()).select_from(OrgErasureRecord))).scalar_one() == 0
    monkeypatch.undo()  # the fault is fixed: the next hourly run retries it
    async with client._maker() as executor:
        assert (await erasure_flow.execute_due(executor))["executed"] == 1
    assert await _intact(client, org) == 0
    async with client._maker() as db:
        req = await db.get(OrgErasureRequest, rid)
        assert req.status == "executed" and req.failure_code is None


async def test_an_abandoned_claim_is_released_and_retried(client) -> None:
    hdr, org, _ = await _owner_company(client, "race5@example.com")
    rid, _ = await _scheduled(client, hdr)
    await _due(client, rid)
    long_ago = datetime.now(UTC) - erasure_flow.STALE_CLAIM - timedelta(minutes=5)
    async with client._maker() as db:
        assert await erasure_flow._claim(db, rid, datetime.now(UTC)) is True  # a worker took it and died
        (await db.get(OrgErasureRequest, rid)).claimed_at = long_ago
        await db.commit()
        assert (await erasure_flow.execute_due(db))["executed"] == 1  # released to failed, then retried
    assert await _intact(client, org) == 0


async def test_the_redis_sweep_runs_after_the_commit(client, monkeypatch) -> None:
    hdr, org, _ = await _owner_company(client, "race6@example.com")
    rid, _ = await _scheduled(client, hdr)
    await _due(client, rid)
    seen: dict[str, Any] = {}

    async def sweep(org_id, users, jobs):
        seen["intact_when_swept"] = await _intact(client, org)  # a fresh connection sees committed data only
        return {"redis_deleted": 3}

    monkeypatch.setattr("app.services.privacy.ephemeral.sweep_org_redis", sweep)
    async with client._maker() as db:
        await erasure_flow.execute_due(db)
        req = await db.get(OrgErasureRequest, rid)
        assert req.post_commit_counts["_ephemeral"]["redis_deleted"] == 3
    assert seen["intact_when_swept"] == 0  # the erasure was already committed when Redis was touched
    async with client._maker() as db:
        assert await org_svc.verify_chain(db) == []


async def test_a_run_that_writes_after_the_erase_commit_is_swept_before_the_request_is_executed(client, monkeypatch) -> None:
    """The final sweep: a run in flight wrote its run-ledger and model-call rows through connections of its own after
    the erase transaction committed (while the cleanup ran). The request reaches `executed` only after they are gone."""
    from app.models.agent_run import AgentRun
    from app.models.llm_call_log import LLMCallLog
    from app.services.privacy import erasure_cleanup

    hdr, org, _ = await _owner_company(client, "race7@example.com")
    rid, _ = await _scheduled(client, hdr)
    await _due(client, rid)
    real = erasure_cleanup.run_cleanup

    finished: list[int] = []

    async def cleanup_while_a_run_finishes(plan, root=None):
        from app.services.privacy import write_guard

        if finished:  # the final sweep's own cleanup: the run is over
            return await real(plan, root)
        finished.append(1)
        async with client._maker() as late:
            with write_guard.exempt(late):  # a writer that got past the guard (its own connection, no session hooks)
                late.add(AgentRun(org_id=org, pipeline="cfo", status="completed", attempt=1))
                late.add(LLMCallLog(org_id=org, task_type="late", model="m"))
                await late.commit()
        return await real(plan, root)

    monkeypatch.setattr(erasure_cleanup, "run_cleanup", cleanup_while_a_run_finishes)
    async with client._maker() as db:
        await erasure_flow.execute_due(db)
        req = await db.get(OrgErasureRequest, rid)
        assert req.status == "executed"
        assert req.post_commit_counts["_final_sweep"]["rows"] >= 2
    async with client._maker() as db:
        for model in (AgentRun, LLMCallLog):
            n = (await db.execute(select(func.count()).select_from(model).where(model.org_id == org))).scalar_one()
            assert n == 0, model.__tablename__


async def test_the_tombstone_refuses_writes_once_the_erasure_is_claimed(client) -> None:
    """SQLite has no advisory lock; the tombstone itself is the same predicate (the Postgres test covers the lock)."""
    from app.services.privacy.tombstone import OrgErasedError, is_erased, refuse_if_erased

    hdr, org, _ = await _owner_company(client, "race8@example.com")
    rid, _ = await _scheduled(client, hdr)
    await _due(client, rid)
    async with client._maker() as db:
        assert await is_erased(db, org) is False
        assert await erasure_flow._claim(db, rid, datetime.now(UTC)) is True  # `executing`: the tombstone is set
        with pytest.raises(OrgErasedError):
            await refuse_if_erased(db, org)
        assert await is_erased(db, None) is False


def test_the_model_call_log_keeps_only_the_exception_type_and_a_safe_code() -> None:
    """`llm_call_logs.error` must not quote the prompt or the model's output that a provider message can carry."""
    from app.platform.llm_egress.audit import safe_error

    leak = "ValueError: could not parse reply 'ZZREALNAME A.Ş. IBAN TR12 0006 1005 1978 6457 8413 26'"
    assert safe_error(leak) == "ValueError"
    assert safe_error("RateLimitError: Error code: 429 - {'error': 'ZZREALNAME'}") == "RateLimitError:http_429"
    assert safe_error("openai.APIStatusError: status 503 for ZZREALNAME") == "openai.APIStatusError:http_503"
    assert safe_error("TimeoutError") == "TimeoutError"
    assert safe_error("egress_refused:no_organisation_context") == "egress_refused:no_organisation_context"
    assert safe_error("egress_refused:ZZREALNAME A.Ş.") == "egress_refused:other"
    assert safe_error("ZZREALNAME said no") == "error" and safe_error(None) is None and safe_error("") is None


def test_the_member_pseudonym_is_keyed_stable_and_not_the_plain_hash(monkeypatch) -> None:
    from app.config import get_settings
    from app.services.privacy.member_erasure import pseudonym

    uid = "00000000-0000-4000-8000-000000000001"
    settings = get_settings()
    monkeypatch.setattr(settings, "erasure_pseudonym_secret", "secret-one")
    first = pseudonym(uid)
    assert first == pseudonym(uid) and first.startswith("member-") and len(first) == len("member-") + 12
    assert first != "member-" + org_svc.hash_id("user", uid)[:12]  # not derivable from the id alone
    monkeypatch.setattr(settings, "erasure_pseudonym_secret", "secret-two")
    assert pseudonym(uid) != first  # depends on the secret
    monkeypatch.setattr(settings, "erasure_pseudonym_secret", "")
    assert pseudonym(uid).startswith("member-")  # falls back to the app secret
