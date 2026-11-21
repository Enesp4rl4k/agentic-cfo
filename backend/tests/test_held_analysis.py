"""A held analysis is a decision waiting for a person, and the statement it holds still proves a balance.

Found by the pilot-flow browser test (frontend/e2e/pilot-flow.spec.ts, steps 3b, 3d, 3e):
  - a statement without a currency column is held whole; the owner confirms the company
    currency and approves, yet the radar had no starting cash: the closing balance was proven
    only over the rows that were *booked* (none), never over the file;
  - nothing listed the held analyses, and approving one left no decision record;
  - the setup page could not tell "waiting for approval" from "no balance column".
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.database as database
from app.agents.data_ingestion import _uncertain_rows_wait
from app.agents.state import SkillResult
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.decision import Decision
from app.services import held_analysis
from tests.api_helpers import arka_plan_bitsin, bellek_istemcisi, kullanici

pytestmark = pytest.mark.real_currency

NL = chr(10)
LAST_DAY = "19.11.2026"


def statement_csv(*, currency_column: bool) -> str:
    """Six rows whose running balances chain (120.000 opening, 116.500 closing); rent in three months."""
    rows = [
        ("15.09.2026", "Ofis kirası", "-12.000,00", "108.000,00"),
        ("20.09.2026", "Satış tahsilatı - Mavi Tekstil", "50.000,00", "158.000,00"),
        ("15.10.2026", "Ofis kirası", "-12.000,00", "146.000,00"),
        ("01.11.2026", "Personel maaş ödemesi", "-30.000,00", "116.000,00"),
        ("15.11.2026", "Ofis kirası", "-12.000,00", "104.000,00"),
        (LAST_DAY, "Danışmanlık geliri - Kara Holding", "12.500,00", "116.500,00"),
    ]
    head = "Tarih;Açıklama;Tutar;Bakiye" + (";Para Birimi" if currency_column else "")
    lines = [head] + [
        f'{d};{text};"{amount}";"{balance}"' + (";TRY" if currency_column else "")
        for d, text, amount, balance in rows
    ]
    return NL.join(lines) + NL


@pytest_asyncio.fixture
async def ortam(monkeypatch, tmp_path):
    async with bellek_istemcisi() as c:
        monkeypatch.setattr(database, "get_session_factory", lambda eng=None: c._maker)
        monkeypatch.setattr(database, "session_factory", lambda: c._maker)
        monkeypatch.setattr(database, "engine", lambda: None)
        from app.services import review_continuation as rc

        async def devam_yok(job_id: str) -> str:
            return "skipped"

        monkeypatch.setattr(rc, "devami_baslat", devam_yok)
        yield c, tmp_path
        await arka_plan_bitsin()


async def upload_statement(client, tmp_path: Path, org_id: str | None, *, currency_column: bool) -> str:
    from app.worker import run_cfo_analysis

    f = tmp_path / "ekstre.csv"
    f.write_text(statement_csv(currency_column=currency_column), encoding="utf-8")
    async with client._maker() as db:
        job = AnalysisJob(filename="ekstre.csv", file_path=str(f), file_type="csv",
                          org_id=org_id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = job.id
    out = await run_cfo_analysis({}, job_id)
    assert out.get("ok") is True, out
    return job_id


async def radar(client, headers) -> dict[str, Any]:
    res = await client.get("/api/v1/ledger/cash-radar", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["data"]


# ── 3e: the radar starts from the statement a person released ────────────────

async def test_radar_starts_from_the_statement_after_currency_is_confirmed_and_the_run_approved(ortam):
    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "owner@x.com")
    job_id = await upload_statement(client, tmp_path, org_id, currency_column=False)

    status = (await client.get(f"/api/v1/analysis/{job_id}", headers=headers)).json()["data"]
    assert status["status"] == "awaiting_review"
    assert status["ingest"]["processed"] == 0 and status["ingest"]["held"] == 6
    assert (await radar(client, headers))["starting_cash_cents"] is None   # nothing approved yet

    # The file proves its balance although every row waits: the held run says so.
    held = (await client.get("/api/v1/analyses/held", headers=headers)).json()["data"]
    assert [h["id"] for h in held] == [job_id]
    assert held[0]["proves_balance"] is True
    assert held[0]["reasons"][0]["code"] == "rows_waiting" and held[0]["reasons"][0]["all_rows"] is True

    confirmed = await client.post("/api/v1/org/base-currency", json={"currency": "TRY"}, headers=headers)
    assert confirmed.status_code == 200 and confirmed.json()["data"]["released"]["resolved"] == 6
    approved = await client.post(f"/api/v1/analysis/{job_id}/approve", json={}, headers=headers)
    assert approved.status_code == 200, approved.text

    start = await radar(client, headers)
    assert start["starting_cash_cents"] == 11_650_000
    assert start["starting_cash_as_of"] == "2026-11-19"
    assert start["opening_cash"]["source_job_id"] == job_id


async def test_a_statement_with_a_currency_column_still_proves_the_same_balance(ortam):
    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "withcur@x.com")
    job_id = await upload_statement(client, tmp_path, org_id, currency_column=True)
    status = (await client.get(f"/api/v1/analysis/{job_id}", headers=headers)).json()["data"]
    if status["status"] == "awaiting_review":
        await client.post(f"/api/v1/analysis/{job_id}/approve", json={}, headers=headers)
    assert (await radar(client, headers))["starting_cash_cents"] == 11_650_000


# ── 3d: held analyses are listed, approved or rejected, and each answer is recorded ──

async def test_approving_a_held_analysis_records_who_decided_and_why_it_was_held(ortam):
    client, tmp_path = ortam
    headers, org_id, owner_id = await kullanici(client, "decider@x.com")
    job_id = await upload_statement(client, tmp_path, org_id, currency_column=False)
    await client.post("/api/v1/org/base-currency", json={"currency": "TRY"}, headers=headers)
    assert (await client.post(f"/api/v1/analysis/{job_id}/approve", json={}, headers=headers)).status_code == 200

    async with client._maker() as db:
        rows = (await db.execute(select(Decision).where(Decision.kind == "held_run_release"))).scalars().all()
    assert len(rows) == 1
    d = rows[0]
    assert (d.target_type, d.target_id, d.outcome) == ("analysis_job", job_id, "approved")
    assert d.decided_via == "human" and d.decided_by == owner_id and d.org_id == org_id
    assert d.before["reasons"] == ["rows_waiting"] and d.after == {"status": "completed"}
    assert (await client.get("/api/v1/analyses/held", headers=headers)).json()["data"] == []
    # A second approval is refused and records nothing more.
    assert (await client.post(f"/api/v1/analysis/{job_id}/approve", json={}, headers=headers)).status_code == 409
    async with client._maker() as db:
        assert len((await db.execute(select(Decision).where(Decision.kind == "held_run_release"))).scalars().all()) == 1


async def test_rejecting_a_held_analysis_keeps_it_on_record_and_out_of_the_radar(ortam):
    client, tmp_path = ortam
    headers, org_id, owner_id = await kullanici(client, "rejecter@x.com")
    job_id = await upload_statement(client, tmp_path, org_id, currency_column=False)
    await client.post("/api/v1/org/base-currency", json={"currency": "TRY"}, headers=headers)

    res = await client.post(f"/api/v1/analysis/{job_id}/reject", json={"reason": "yanlış dönem"}, headers=headers)
    assert res.status_code == 200, res.text
    status = (await client.get(f"/api/v1/analysis/{job_id}", headers=headers)).json()["data"]
    assert status["status"] == "failed" and status["error"] == "yanlış dönem"
    assert (await radar(client, headers))["starting_cash_cents"] is None
    async with client._maker() as db:
        d = (await db.execute(select(Decision).where(Decision.kind == "held_run_release"))).scalar_one()
    assert (d.outcome, d.reason, d.decided_by) == ("rejected", "yanlış dönem", owner_id)
    assert (await client.post(f"/api/v1/analysis/{job_id}/reject", json={}, headers=headers)).status_code == 409


async def test_a_viewer_neither_approves_nor_rejects_a_held_analysis(ortam):
    client, tmp_path = ortam
    _, org_id, _ = await kullanici(client, "own@x.com")
    job_id = await upload_statement(client, tmp_path, org_id, currency_column=False)
    viewer, _, _ = await kullanici(client, "view@x.com", attach_org=False, role="viewer")
    async with client._maker() as db:
        from app.models.user import User

        user = (await db.execute(select(User).where(User.email == "view@x.com"))).scalar_one()
        user.org_id = org_id
        await db.commit()
    viewer, _, _ = await kullanici(client, "view@x.com", attach_org=False, role="viewer")
    assert (await client.post(f"/api/v1/analysis/{job_id}/approve", json={}, headers=viewer)).status_code == 403
    assert (await client.post(f"/api/v1/analysis/{job_id}/reject", json={}, headers=viewer)).status_code == 403
    # They may read what waits.
    assert [h["id"] for h in (await client.get("/api/v1/analyses/held", headers=viewer)).json()["data"]] == [job_id]


async def test_the_held_list_is_the_companys_own(ortam):
    client, tmp_path = ortam
    mine, org_a, _ = await kullanici(client, "a@x.com")
    theirs, _, _ = await kullanici(client, "b@x.com")
    job_a = await upload_statement(client, tmp_path, org_a, currency_column=False)
    assert [h["id"] for h in (await client.get("/api/v1/analyses/held", headers=mine)).json()["data"]] == [job_a]
    assert (await client.get("/api/v1/analyses/held", headers=theirs)).json()["data"] == []
    assert (await client.post(f"/api/v1/analysis/{job_a}/approve", json={}, headers=theirs)).status_code in (403, 404)


# ── 3b: what the setup page is told ──────────────────────────────────────────

async def test_the_setup_facts_say_waiting_for_approval_with_the_reason_and_the_balance(ortam):
    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "setup@x.com")
    job_id = await upload_statement(client, tmp_path, org_id, currency_column=False)
    facts = (await client.get("/api/v1/baslangic", headers=headers)).json()["data"]
    assert facts["analizler"] == {"calisan": 0, "onay_bekleyen": 1, "tamamlanan": 0, "basarisiz": 0}
    [waiting] = facts["onay_bekleyen"]
    assert waiting["id"] == job_id and waiting["bakiye_kanitli"] is True
    assert waiting["nedenler"][0]["code"] == "rows_waiting"

    await client.post("/api/v1/org/base-currency", json={"currency": "TRY"}, headers=headers)
    await client.post(f"/api/v1/analysis/{job_id}/approve", json={}, headers=headers)
    facts = (await client.get("/api/v1/baslangic", headers=headers)).json()["data"]
    assert facts["analizler"] == {"calisan": 0, "onay_bekleyen": 0, "tamamlanan": 1, "basarisiz": 0}
    assert facts["onay_bekleyen"] == []


# ── units ────────────────────────────────────────────────────────────────────

def _row(date: str, amount: int, kind: str, balance: int, **kw: Any) -> dict[str, Any]:
    return {"transaction_date": date, "amount_cents": amount, "type": kind, "balance_cents": balance,
            "currency": "TRY", "confidence": 0.95, **kw}


def test_the_closing_balance_is_proven_over_the_whole_file_in_file_order_when_rows_are_held():
    rows = [
        _row("2026-11-01", 1_000, "expense", 9_000),
        _row("2026-11-02", 500, "income", 9_500, currency=""),      # no currency: held
        _row("2026-11-03", 200, "expense", 9_300),
    ]
    out = _uncertain_rows_wait(SkillResult(ok=True, patch={"transactions": rows}, confidence=0.95, detail="x"))
    assert [t["transaction_date"] for t in out.patch["transactions"]] == ["2026-11-01", "2026-11-03"]
    assert out.patch["statement_closing_balance"] == {"date": "2026-11-03", "balance_cents": 9_300}


def test_a_file_whose_balances_do_not_chain_proves_nothing_even_with_rows_held():
    rows = [_row("2026-11-01", 1_000, "expense", 9_000), _row("2026-11-02", 500, "income", 1, currency="")]
    out = _uncertain_rows_wait(SkillResult(ok=True, patch={"transactions": rows}, confidence=0.95, detail="x"))
    assert "statement_closing_balance" not in out.patch


def _job(**kw: Any) -> AnalysisJob:
    return AnalysisJob(filename="f.csv", file_path="/f", file_type="csv", status=JobStatus.AWAITING_REVIEW, **kw)


def test_a_run_below_the_gate_says_the_number_and_the_threshold():
    reasons = held_analysis.why_held(_job(min_confidence=0.62))
    assert reasons[0] == {"code": "confidence_low", "min_confidence": 0.62, "threshold": 0.80}


def test_a_run_above_the_gate_is_explained_by_its_weakest_step_not_by_a_confidence_it_does_not_have():
    held = held_analysis.held_by({"confidence_breakdown": {
        "binding_constraint": "forecast",
        "components": [{"step": "forecast", "confidence": 0.83, "detail": "baz runway=1 ay"}],
    }})
    reasons = held_analysis.why_held(_job(min_confidence=0.83, result_metadata={"held_by": held}))
    assert [r["code"] for r in reasons] == ["weakest_step"]
    assert reasons[0]["step"] == "forecast" and reasons[0]["detail"] == "baz runway=1 ay"


def test_a_hold_with_nothing_recorded_says_so_instead_of_inventing_a_reason():
    assert held_analysis.why_held(_job()) == [{"code": "unspecified"}]
