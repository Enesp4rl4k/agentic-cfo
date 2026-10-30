"""Plan v7 §P0 / W2 — one upload no longer wipes the company's picture.

Live audit 2026-10-24: approving a broken CSV made it the active CFO analysis
and the company snapshot lost revenue, runway and margin. A new analysis now
replaces the view only if it adds a period; otherwise the person can apply it.
"""
from __future__ import annotations

import pytest_asyncio

import app.database as database
from app.services.company_view import months_of, should_replace
from tests.api_helpers import arka_plan_bitsin, bellek_istemcisi, kullanici


def _dash(*months: str, revenue: float = 1.0) -> dict:
    return {"pnl": {"revenue": revenue},
            "cashflow": {"monthly_series": [{"month": m, "net": 1} for m in months]}}


YEAR_2024 = _dash(*(f"2024-{m:02d}" for m in range(1, 13)), revenue=9_799_500)


# ── rule ──────────────────────────────────────────────────────────────────────


def test_months_are_read_from_the_cash_flow_series():
    assert months_of(_dash("2024-02", "2024-01", "2024-01", "bad")) == ["2024-01", "2024-02"]
    assert months_of(None) == []


def test_first_analysis_always_becomes_the_view():
    assert should_replace(None, _dash("2024-01")) == (True, "no_current_view")


def test_a_narrower_period_inside_the_view_does_not_replace_it():
    assert should_replace(YEAR_2024, _dash("2024-02")) == (
        False, "narrower_period_within_current_view")


def test_an_unreadable_period_does_not_replace_a_view_that_has_one():
    assert should_replace(YEAR_2024, {"pnl": {"revenue": None}}) == (False, "period_unreadable")


def test_an_older_single_month_does_not_replace_a_year():
    """Live: a UBL-TR sample invoice from an older month took over a 2024 view."""
    assert should_replace(YEAR_2024, _dash("2009-04")) == (False, "narrower_and_not_newer")


def test_a_new_month_replaces_the_view():
    assert should_replace(YEAR_2024, _dash("2025-01"))[0] is True


def test_the_same_period_again_replaces_it():
    """A re-upload or corrected file of the same year is the newer truth."""
    assert should_replace(YEAR_2024, YEAR_2024)[0] is True


# ── flow ──────────────────────────────────────────────────────────────────────


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
        yield c, chained
        await arka_plan_bitsin()


async def _completed_job(client, org_id: str, dashboard: dict) -> str:
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.report import Report, ReportFormat, ReportType

    async with client._maker() as db:
        job = AnalysisJob(filename="x.csv", file_path="/x.csv", file_type="csv",
                          org_id=org_id, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        db.add(Report(job_id=job.id, report_type=ReportType.FULL,
                      report_format=ReportFormat.JSON, data=dashboard))
        await db.commit()
        return job.id


async def _complete(client, job_id: str, org_id: str, dashboard: dict) -> None:
    from app.worker import continue_after_completion

    async with client._maker() as db:
        await continue_after_completion(job_id, org_id, {"dashboard_json": dashboard}, db)


async def _active(client, org_id: str) -> str | None:
    from app.services.company_context import get_company_context

    async with client._maker() as db:
        return (await get_company_context(org_id, db)).active_cfo_job_id


async def test_a_single_month_or_a_broken_file_keeps_the_year_view(ortam):
    from app.models.analysis_job import AnalysisJob

    client, chained = ortam
    _, org_id, _ = await kullanici(client, "gorunum@example.com")
    year = await _completed_job(client, org_id, YEAR_2024)
    await _complete(client, year, org_id, YEAR_2024)
    assert await _active(client, org_id) == year

    month = await _completed_job(client, org_id, _dash("2024-03"))
    await _complete(client, month, org_id, _dash("2024-03"))
    broken = await _completed_job(client, org_id, {"pnl": {}})
    await _complete(client, broken, org_id, {"pnl": {}})

    assert await _active(client, org_id) == year
    assert chained == [year]  # nothing re-synthesised for an unapplied view
    async with client._maker() as db:
        m = await db.get(AnalysisJob, month)
        assert m.result_metadata["company_view"] == {
            "applied": False, "reason": "narrower_period_within_current_view"}


async def test_a_new_period_moves_the_view_and_the_person_can_apply_any(ortam):
    client, _ = ortam
    headers, org_id, _ = await kullanici(client, "uygula@example.com")
    year = await _completed_job(client, org_id, YEAR_2024)
    await _complete(client, year, org_id, YEAR_2024)

    jan25 = await _completed_job(client, org_id, _dash("2025-01"))
    await _complete(client, jan25, org_id, _dash("2025-01"))
    assert await _active(client, org_id) == jan25

    # The person chooses the year again, explicitly.
    res = await client.post(f"/api/v1/analysis/{year}/company-view", headers=headers)
    assert res.status_code == 200, res.text
    assert await _active(client, org_id) == year


async def test_only_an_owned_completed_job_with_a_dashboard_can_be_applied(ortam):
    client, _ = ortam
    headers, org_id, _ = await kullanici(client, "sahip2@example.com")
    other_headers, _, _ = await kullanici(client, "baskasi@example.com")
    job = await _completed_job(client, org_id, YEAR_2024)

    foreign = await client.post(f"/api/v1/analysis/{job}/company-view", headers=other_headers)
    assert foreign.status_code in (403, 404)

    empty = await _completed_job(client, org_id, {})
    res = await client.post(f"/api/v1/analysis/{empty}/company-view", headers=headers)
    assert res.status_code == 409
