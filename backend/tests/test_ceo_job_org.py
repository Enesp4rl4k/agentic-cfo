"""A CEO job's follow-up work runs for the job's COMPANY, never for its job id.

`worker.run_ceo_analysis` handed `org_id=job_id` to the auto-chain (`on_agent_complete`). Everything there is keyed
by company: the CompanyContext (Redis key and DB snapshot), the conductor plan, the semantic snapshot and the
decision brief (`rebuild_semantic_snapshot`). With a job id, those were read and written for a company that does
not exist (orphan rows and keys) and the real company's were never refreshed after a CEO run. The LLM calls were
not affected (they take the tenant context, which was the owner's), but any future step that passes `org_id` to
the gateway would have opened a masking session for a company with no names and no data-mode choice.
"""
from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def ceo_job(monkeypatch):
    import app.agents.ceo.orchestrator as ceo
    import app.agents.orchestration.auto_chain as auto_chain
    import app.core.background as background
    from app import worker
    from app.core.tenancy import get_current_tenant, set_current_tenant

    seen: dict[str, Any] = {"chain": [], "pipeline": [], "tenant": []}

    async def pipeline(**kwargs: Any) -> dict:
        seen["pipeline"].append(kwargs.get("org_id"))
        seen["tenant"].append(get_current_tenant())
        return {"financial_summary": {"ok": True}, "logs": []}

    async def on_agent_complete(agent: str, org_id: str, result: dict, db: Any = None) -> None:
        seen["chain"].append((agent, org_id))

    def spawn(coro, name: str | None = None):  # run the background task's coroutine where we can see it
        seen.setdefault("spawned", []).append(coro)

    class _Pool:
        async def set(self, *_: Any, **__: Any) -> None:
            return None

    async def pool() -> _Pool:
        return _Pool()

    monkeypatch.setattr(ceo, "run_ceo_pipeline", pipeline)
    monkeypatch.setattr(auto_chain, "on_agent_complete", on_agent_complete)
    monkeypatch.setattr(background, "spawn", spawn)
    monkeypatch.setattr(worker, "get_arq_pool", pool)

    async def run(owner_org: str | None, enqueued_org: str | None) -> dict[str, Any]:
        async def owner(job_id: str) -> dict | None:
            return None if owner_org is None else {"org_id": owner_org, "user_id": "u"}

        monkeypatch.setattr(worker, "get_ceo_job_owner", owner)
        try:
            out = await worker.run_ceo_analysis({}, "job-7f3a9c", org_id=enqueued_org, cfo_transactions=[{}])
        finally:
            set_current_tenant(None)
        for coro in seen.pop("spawned", []):
            await coro
        seen["out"] = out
        return seen

    return run


async def test_the_auto_chain_gets_the_jobs_org_not_the_job_id(ceo_job) -> None:
    seen = await ceo_job("org-owner-1", "org-owner-1")
    assert seen["out"]["ok"]
    assert seen["chain"] == [("ceo", "org-owner-1")]
    assert seen["pipeline"] == ["org-owner-1"] and seen["tenant"] == ["org-owner-1"]


async def test_the_recorded_owner_is_the_authority(ceo_job) -> None:
    seen = await ceo_job("org-owner-1", None)  # the enqueued arguments did not carry the org
    assert seen["chain"] == [("ceo", "org-owner-1")]
    assert seen["pipeline"] == ["org-owner-1"]


async def test_no_company_known_no_auto_chain(ceo_job) -> None:
    seen = await ceo_job(None, None)
    assert seen["out"]["ok"]
    assert seen["chain"] == [], "nothing keyed by company may run without one (and never under the job id)"
