"""Plan v9 §K1 — the company's picture is read from its ledger, not from the last file.

Live: one March 2025 invoice of ₺1,180 replaced a 2024 view, so the company's
revenue read ₺1,180 while its ledger held ₺9.8M. The view now comes from every
period the ledger holds.

Expected figures are summed from `demo/data/logo_tiger_2024.csv` without the
pipeline (`_file_revenue`), plus amounts written here by hand.
"""
from __future__ import annotations

from typing import Any

import pytest_asyncio
from sqlalchemy import select

import app.database as database
from app.core.dates import parse_transaction_date
from app.models.agent_job import AgentJob, AgentJobStatus
from app.models.agent_run import AgentRun
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.open_item_match import OpenItemMatch
from app.models.transaction import Transaction
from app.services.company_context import get_company_context
from app.services.ledger import ledger_summary
from tests.api_helpers import arka_plan_bitsin, bellek_istemcisi, kullanici
from tests.test_bank_reconciliation import _bank, _sale
from tests.test_ledger import _demo_rows, _file_revenue

ALL_MONTHS = {f"{m:02d}" for m in range(1, 13)}
INVOICE = 1_180_00


@pytest_asyncio.fixture
async def ortam(monkeypatch):
    async with bellek_istemcisi() as c:
        monkeypatch.setattr(database, "get_session_factory", lambda eng=None: c._maker)
        monkeypatch.setattr(database, "session_factory", lambda: c._maker)
        monkeypatch.setattr(database, "engine", lambda: None)
        chained: list[str] = []
        monkeypatch.setattr("app.worker.spawn_auto_chain",
                            lambda job_id, org_id, chain: chained.append(job_id))
        monkeypatch.setattr("app.worker._job_side_effects", lambda *a, **k: None)
        headers, org_id, _ = await kullanici(c, "defter@example.com", role="owner")
        c.headers_of_owner = headers
        yield c, org_id, chained
        await arka_plan_bitsin()


def _march_invoice() -> dict[str, Any]:
    return _sale("MARCH-2025", amount=INVOICE, no="GIB2025000000001", issued="2025-03-01", due=None)


async def _analysed(client, org_id: str, rows: list[dict[str, Any]]) -> str:
    async with client._maker() as db:
        job = AnalysisJob(filename="x", file_path="/x", file_type="csv", org_id=org_id,
                          status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        for r in rows:
            when, estimated = parse_transaction_date(r["transaction_date"])
            db.add(Transaction(
                job_id=job.id, amount_kurus=r["amount_cents"], currency="TRY", type=r["type"],
                category=r["category"], description=r.get("description"), vendor=r.get("vendor"),
                transaction_date=when, date_is_estimated=estimated, document_id=r.get("document_id"),
                due_date=r.get("due_date"), counterparty=r.get("counterparty"),
                account_code=r.get("account_code"),
            ))
        await db.commit()
        return job.id


async def _continue(client, job_id: str, org_id: str) -> None:
    from app.worker import continue_after_completion

    # The file's own dashboard says only what that file says.
    file_result = {"dashboard_json": {"pnl": {"revenue": 1.0}, "cashflow": {}}}
    async with client._maker() as db:
        await continue_after_completion(job_id, org_id, file_result, db)


async def _upload(client, org_id: str, rows: list[dict[str, Any]]) -> str:
    """A completed analysis of these rows, and what the worker does next."""
    job_id = await _analysed(client, org_id, rows)
    await _continue(client, job_id, org_id)
    return job_id


async def _view(client, org_id: str) -> dict[str, Any]:
    async with client._maker() as db:
        return (await get_company_context(org_id, db)).last_cfo_result or {}


async def _note(client, job_id: str) -> dict[str, Any]:
    async with client._maker() as db:
        return (await db.get(AnalysisJob, job_id)).result_metadata["company_view"]


async def _revenue(client, org_id: str) -> float:
    return (await _view(client, org_id))["dashboard"]["pnl"]["revenue"]


async def _waiting(client, org_id: str) -> list[AgentJob]:
    async with client._maker() as db:
        return list((await db.execute(select(AgentJob).where(
            AgentJob.org_id == org_id, AgentJob.status == AgentJobStatus.AWAITING_REVIEW,
        ))).scalars().all())


def _hold_every_view(monkeypatch) -> Any:
    import app.agents.orchestrator as orchestrator

    real = orchestrator.run_cfo_pipeline

    async def held(*args: Any, **kwargs: Any) -> Any:
        return {**await real(*args, **kwargs), "awaiting_review": True}

    monkeypatch.setattr(orchestrator, "run_cfo_pipeline", held)
    return real


async def test_one_invoice_does_not_replace_the_year(ortam):
    client, org_id, _ = ortam
    await _upload(client, org_id, _demo_rows())
    year_revenue = _file_revenue(ALL_MONTHS)
    assert year_revenue == 9_799_500_00

    await _upload(client, org_id, [_march_invoice()])

    view = await _view(client, org_id)
    assert view["dashboard"]["pnl"]["revenue"] == (year_revenue + INVOICE) / 100
    assert view["dashboard"]["source"] == "ledger"
    assert view["dashboard"]["period"] == {"start": "2024-01", "end": "2025-03", "months": 13}


async def test_the_view_and_the_ledger_card_say_the_same_number(ortam):
    client, org_id, _ = ortam
    await _upload(client, org_id, _demo_rows("01", "02"))
    await _upload(client, org_id, [_march_invoice()])

    view = await _view(client, org_id)
    async with client._maker() as db:
        summary = await ledger_summary(db, org_id)
    assert view["dashboard"]["pnl"]["revenue"] == summary["revenue_cents"] / 100
    series = {m["month"]: m for m in view["dashboard"]["cashflow"]["monthly_series"]}
    for month in summary["months"]:
        if month["cash_in_cents"] or month["cash_out_cents"]:
            assert series[month["month"]]["in"] == month["cash_in_cents"]
            assert series[month["month"]]["out"] == month["cash_out_cents"]


async def test_an_invoice_is_not_cash_and_its_receipt_is_not_revenue_again(ortam):
    client, org_id, _ = ortam
    sale = _sale("F1", no="GIB2024000000001", issued="2024-03-01", due=None)
    await _upload(client, org_id, [sale])
    view = await _view(client, org_id)
    assert view["dashboard"]["pnl"]["revenue"] == 285_000.0
    assert view["dashboard"]["cashflow"]["monthly_series"] == []

    await _upload(client, org_id, [_bank("EFT GIB2024000000001 ODEME", 285_000_00, "2024-04-16")])
    view = await _view(client, org_id)
    assert view["dashboard"]["pnl"]["revenue"] == 285_000.0
    assert view["dashboard"]["cashflow"]["monthly_series"] == [
        {"month": "2024-04", "in": 285_000_00, "out": 0, "net": 285_000_00}]


async def test_the_same_file_again_changes_nothing_and_runs_nothing(ortam):
    client, org_id, chained = ortam
    rows = _demo_rows("01")
    first = await _upload(client, org_id, rows)
    before = await _view(client, org_id)

    again = await _upload(client, org_id, rows)

    assert await _note(client, again) == {"applied": False, "reason": "ledger_unchanged"}
    status = await client.get(f"/api/v1/analysis/{again}", headers=client.headers_of_owner)
    assert status.json()["data"]["company_view"]["reason"] == "ledger_unchanged"
    after = await _view(client, org_id)
    assert after["dashboard"]["generated_at"] == before["dashboard"]["generated_at"]
    assert after["job_id"] == first
    assert chained == [first]


async def test_cash_read_from_postings_says_so(ortam):
    client, org_id, _ = ortam
    await _upload(client, org_id, _demo_rows("01"))
    alerts = (await _view(client, org_id))["dashboard"]["cashflow"]["alerts"]
    assert any("banka ekstresi" in a["message"].lower() for a in alerts)


async def test_a_doubtful_row_waits_outside_the_view(ortam):
    client, org_id, _ = ortam
    await _upload(client, org_id, [_bank("Tahsilat A", 40_000_00, "2024-05-02")])
    await _upload(client, org_id, [_bank("Baska metin B", 40_000_00, "2024-05-03")])
    assert await _revenue(client, org_id) == 40_000.0


async def test_a_persons_no_on_a_settlement_reaches_the_view(ortam):
    client, org_id, _ = ortam
    await _upload(client, org_id, [_sale("F1", no="GIB2024000000002", issued="2024-03-01", due=None)])
    await _upload(client, org_id, [_bank("Gelen EFT", 285_000_00, "2024-04-10")])
    assert await _revenue(client, org_id) == 285_000.0
    async with client._maker() as db:
        match = (await db.execute(select(OpenItemMatch))).scalars().one()
        assert match.status == "proposed"
        match_id = match.id

    response = await client.post(f"/api/v1/ledger/settlements/{match_id}/resolve",
                                 headers=client.headers_of_owner, json={"action": "reject"})
    assert response.status_code == 200, response.text
    await arka_plan_bitsin()

    assert await _revenue(client, org_id) == 570_000.0


async def test_a_held_view_waits_for_the_owner_and_the_old_one_stands(ortam, monkeypatch):
    client, org_id, _ = ortam
    await _upload(client, org_id, _demo_rows("01"))
    standing = await _revenue(client, org_id)
    _hold_every_view(monkeypatch)

    job = await _upload(client, org_id, [_march_invoice()])
    # The same ledger prompts it again: one question, not two.
    again = await _upload(client, org_id, [_march_invoice()])

    assert await _revenue(client, org_id) == standing
    assert (await _note(client, job))["reason"] == "ledger_view_held"
    assert (await _note(client, again))["reason"] == "ledger_view_held"
    queued = await _waiting(client, org_id)
    assert [q.agent_type for q in queued] == ["cfo"]
    assert queued[0].result_json["dashboard"]["pnl"]["revenue"] == standing + INVOICE / 100

    response = await client.post(f"/api/v1/agent-jobs/{queued[0].id}/approve",
                                 headers=client.headers_of_owner, json={})
    assert response.status_code == 200, response.text
    await arka_plan_bitsin()

    view = await _view(client, org_id)
    assert view["dashboard"]["pnl"]["revenue"] == standing + INVOICE / 100
    assert view["job_id"] == job


async def test_a_newer_ledger_retires_the_question_about_the_older_one(ortam, monkeypatch):
    import app.agents.orchestrator as orchestrator

    client, org_id, _ = ortam
    await _upload(client, org_id, _demo_rows("01"))
    real = _hold_every_view(monkeypatch)
    await _upload(client, org_id, [_march_invoice()])
    assert len(await _waiting(client, org_id)) == 1

    monkeypatch.setattr(orchestrator, "run_cfo_pipeline", real)
    later = _sale("LATER", amount=2_000_00, no="GIB2025000000002", issued="2025-04-01", due=None)
    await _upload(client, org_id, [later])

    assert await _waiting(client, org_id) == []
    assert await _revenue(client, org_id) == (_file_revenue({"01"}) + INVOICE + 2_000_00) / 100


async def test_the_ledger_run_is_on_record(ortam):
    client, org_id, _ = ortam
    await _upload(client, org_id, _demo_rows("01"))
    async with client._maker() as db:
        runs = (await db.execute(
            select(AgentRun).where(AgentRun.pipeline == "cfo_ledger")
        )).scalars().all()
    assert [r.status for r in runs] == ["completed"]


async def test_a_ledger_that_moved_during_the_run_leaves_the_write_to_the_later_run(ortam, monkeypatch):
    import app.agents.orchestrator as orchestrator

    client, org_id, _ = ortam
    real = orchestrator.run_cfo_pipeline
    other = await _analysed(client, org_id, [_march_invoice()])

    async def overtaken(*args: Any, **kwargs: Any) -> Any:
        monkeypatch.setattr(orchestrator, "run_cfo_pipeline", real)
        await _continue(client, other, org_id)
        return await real(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "run_cfo_pipeline", overtaken)
    first = await _upload(client, org_id, _demo_rows("01"))

    assert (await _note(client, first))["reason"] == "ledger_moved"
    view = await _view(client, org_id)
    assert view["job_id"] == other
    assert view["dashboard"]["pnl"]["revenue"] == (_file_revenue({"01"}) + INVOICE) / 100


async def test_with_nothing_dated_the_files_own_result_still_gives_a_first_view(ortam):
    client, org_id, _ = ortam
    job = await _upload(client, org_id, [])
    assert (await _note(client, job))["reason"] == "no_current_view"
    assert (await _view(client, org_id))["job_id"] == job
