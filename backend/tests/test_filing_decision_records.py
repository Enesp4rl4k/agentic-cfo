"""Compliance filings, the confirmed column mapping and company identity leave a decision; the log is role-gated."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.analysis_job import AnalysisJob
from app.models.compliance_extended import BreachNotification, ComplianceCertification
from app.models.organization import Organization
from app.services.decisions import DecisionError
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.decision_helpers import decisions_of, record_fails
from tests.test_org_vkn import _vkn

API = "/api/v1"
FILING = "compliance_filing"
_BREACH = {"description": "Müşteri listesi yanlışlıkla paylaşıldı: Ali Veli", "severity": "high", "affected_users": 12}
_SOX = {"period": "2024-Q2", "certifier_name": "Ayşe Yılmaz", "certifier_role": "CFO", "statements": [True, True, True]}


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def test_a_breach_and_its_notification_are_recorded_without_the_free_text(client):
    headers, org_id, user_id = await kullanici(client, "ihlal@example.com")
    res = await client.post(f"{API}/compliance/gdpr/breach-notification", headers=headers, json=_BREACH)
    assert res.status_code == 200, res.text
    breach_id = res.json()["data"]["breach_id"]
    (d,) = await decisions_of(client, org_id, kind=FILING)
    assert (d.target_type, d.target_id, d.outcome, d.decided_by) == ("breach_notification", breach_id, "breach_recorded", user_id)
    assert (d.after["severity"], d.after["affected_users"], d.after["status"]) == ("high", 12, "pending")
    assert d.after["acting_role"] == "owner" and "Ali Veli" not in str(d.after)

    sent = await client.post(f"{API}/compliance/gdpr/breach/{breach_id}/notify", headers=headers)
    assert sent.status_code == 200, sent.text
    notified = (await decisions_of(client, org_id, kind=FILING))[-1]
    assert (notified.outcome, notified.target_id) == ("marked_notified", breach_id)
    assert notified.before == {"status": "pending"} and notified.after["status"] == "notified"
    again = await client.post(f"{API}/compliance/gdpr/breach/{breach_id}/notify", headers=headers)
    assert again.status_code == 200 and len(await decisions_of(client, org_id, kind=FILING)) == 2


async def test_breach_filings_need_a_decider_stay_in_their_org_and_fail_closed(client, monkeypatch):
    headers, org_id, _ = await kullanici(client, "ihlal2@example.com")
    cfo, _, _ = await kullanici(client, "ihlal3@example.com", role="cfo")
    other, other_org, _ = await kullanici(client, "ihlal4@example.com")
    assert (await client.post(f"{API}/compliance/gdpr/breach-notification", headers=cfo, json=_BREACH)).status_code == 403
    breach_id = (await client.post(f"{API}/compliance/gdpr/breach-notification", headers=headers, json=_BREACH)).json()["data"]["breach_id"]
    assert (await client.post(f"{API}/compliance/gdpr/breach/{breach_id}/notify", headers=other)).status_code == 404
    assert (await client.post(f"{API}/compliance/gdpr/breach/{breach_id}/notify", headers=cfo)).status_code == 403
    assert len(await decisions_of(client, org_id)) == 1 and await decisions_of(client, other_org) == []

    record_fails(monkeypatch, "app.services.compliance_filing_decision")
    # Not a 200 with a clock that runs for nobody: the filing is refused as a whole.
    assert (await client.post(f"{API}/compliance/gdpr/breach/{breach_id}/notify", headers=headers)).status_code == 500
    assert (await client.post(f"{API}/compliance/gdpr/breach-notification", headers=headers, json=_BREACH)).status_code == 500
    monkeypatch.undo()
    async with client._maker() as db:
        rows = (await db.execute(select(BreachNotification))).scalars().all()
    assert [r.status for r in rows] == ["pending"]


async def test_a_sox_certification_records_the_signature_not_the_name_and_fails_closed(client, monkeypatch):
    headers, org_id, user_id = await kullanici(client, "sox@example.com")
    res = await client.post(f"{API}/compliance/sox/certify", headers=headers, json=_SOX)
    assert res.status_code == 200, res.text
    (d,) = await decisions_of(client, org_id, kind=FILING)
    assert (d.target_type, d.outcome, d.decided_by) == ("compliance_certification", "certified", user_id)
    assert d.after["signature_hash"] == res.json()["data"]["signature_hash"]
    assert (d.after["period"], d.after["certifier_role"], d.after["statements_confirmed"]) == ("2024-Q2", "CFO", 3)
    assert "Ayşe" not in str(d.after)
    async with client._maker() as db:
        assert (await db.execute(select(ComplianceCertification))).scalars().one().id == d.target_id

    bad = await client.post(f"{API}/compliance/sox/certify", headers=headers, json={**_SOX, "statements": [True, False, True]})
    assert bad.status_code == 400 and len(await decisions_of(client, org_id)) == 1

    record_fails(monkeypatch, "app.services.compliance_filing_decision")
    refused = await client.post(f"{API}/compliance/sox/certify", headers=headers, json={**_SOX, "period": "2024-Q3"})
    assert refused.status_code == 500                      # it used to answer "signed" with a hash and store nothing
    monkeypatch.undo()
    async with client._maker() as db:
        assert len((await db.execute(select(ComplianceCertification))).scalars().all()) == 1


# ── Accept mapping ───────────────────────────────────────────────────────────

_MAPPING = {"filename": "ekstre.csv", "column_mapping": {"date": "Tarih", "amount": "Tutar"},
            "csv_content": "Tarih,Tutar\n2024-01-01,100\n2024-01-02,-50\n"}


async def test_the_confirmed_column_mapping_is_a_decision_beside_the_job(client):
    headers, org_id, user_id = await kullanici(client, "esle@example.com", role="smmm")
    res = await client.post(f"{API}/data-quality/accept-mapping", headers=headers, json=_MAPPING)
    assert res.status_code == 200, res.text
    job_id = res.json()["data"]["job_id"]
    (d,) = await decisions_of(client, org_id, kind="column_mapping_acceptance")
    assert (d.target_type, d.target_id, d.outcome, d.decided_by) == ("analysis_job", job_id, "accepted", user_id)
    assert d.after == {"column_mapping": {"date": "Tarih", "amount": "Tutar"}, "acting_role": "smmm"}
    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
        assert job.result_metadata["column_mapping"] == {"date": "Tarih", "amount": "Tutar"}


async def test_a_refused_mapping_and_a_failed_record_leave_no_job(client, monkeypatch):
    headers, org_id, _ = await kullanici(client, "esle2@example.com")
    viewer, _, _ = await kullanici(client, "esle3@example.com", role="viewer")
    assert (await client.post(f"{API}/data-quality/accept-mapping", headers=viewer, json=_MAPPING)).status_code == 403
    assert (await client.post(f"{API}/data-quality/accept-mapping", headers=headers,
                              json={**_MAPPING, "filename": "ekstre.pdf"})).status_code == 400
    record_fails(monkeypatch, "app.api.data_quality")
    assert (await client.post(f"{API}/data-quality/accept-mapping", headers=headers, json=_MAPPING)).status_code == 500
    monkeypatch.undo()
    async with client._maker() as db:
        assert (await db.execute(select(AnalysisJob))).scalars().all() == []
    assert await decisions_of(client, org_id) == []


# ── Organisation PATCH ───────────────────────────────────────────────────────

async def test_only_identity_changes_are_decisions_and_the_tax_number_is_masked(client):
    headers, org_id, user_id = await kullanici(client, "org@example.com", role="admin")
    tax = _vkn("123456789")
    assert (await client.patch(f"{API}/org/me", headers=headers, json={"name": "Yeni Ad", "focus_mode": True})).status_code == 200
    assert await decisions_of(client, org_id) == []                      # housekeeping decides nothing

    res = await client.patch(f"{API}/org/me", headers=headers, json={"vkn": tax, "country_code": "tr", "name": "Yeni Ad 2"})
    assert res.status_code == 200, res.text
    (d,) = await decisions_of(client, org_id, kind="org_identity_change")
    assert (d.target_type, d.target_id, d.outcome, d.decided_by) == ("organization", org_id, "changed", user_id)
    assert d.before == {"country_code": "US", "vkn": None}
    assert d.after == {"country_code": "TR", "vkn": f"*******{tax[-3:]}", "acting_role": "admin"}
    assert tax not in str(d.after)

    same = await client.patch(f"{API}/org/me", headers=headers, json={"vkn": tax, "country_code": "TR"})
    assert same.status_code == 200 and len(await decisions_of(client, org_id)) == 1   # nothing changed, nothing decided


async def test_a_refused_identity_change_and_a_failed_record_change_nothing(client, monkeypatch):
    headers, org_id, _ = await kullanici(client, "org2@example.com")
    analyst, _, _ = await kullanici(client, "org3@example.com", role="analyst")
    assert (await client.patch(f"{API}/org/me", headers=headers, json={"vkn": "123"})).status_code == 422
    assert (await client.patch(f"{API}/org/me", headers=analyst, json={"vkn": _vkn("123456789")})).status_code == 403
    assert await decisions_of(client, org_id) == []

    record_fails(monkeypatch, "app.services.org_identity_decision")
    with pytest.raises(DecisionError):
        await client.patch(f"{API}/org/me", headers=headers, json={"vkn": _vkn("123456789")})
    monkeypatch.undo()
    async with client._maker() as db:
        assert (await db.get(Organization, org_id)).vkn is None


# ── The log: who may read what ───────────────────────────────────────────────

async def test_the_company_wide_log_is_for_the_books_roles_and_one_objects_history_for_members(client):
    owner, org_id, _ = await kullanici(client, "log1@example.com")
    viewer, _, _ = await kullanici(client, "log2@example.com", role="viewer")
    await client.post(f"{API}/compliance/sox/certify", headers=owner, json=_SOX)
    (d,) = await decisions_of(client, org_id)

    assert (await client.get(f"{API}/decision-records", headers=owner)).status_code == 200
    assert (await client.get(f"{API}/decision-records", headers=viewer)).status_code == 403
    assert (await client.get(f"{API}/decision-records?kind={FILING}", headers=viewer)).status_code == 403
    one = f"{API}/decision-records?target_type={d.target_type}&target_id={d.target_id}"
    assert (await client.get(one, headers=viewer)).status_code == 200      # own company only: scoped by organisation


async def test_the_log_filters_by_who_and_by_date(client):
    owner, _, user_id = await kullanici(client, "log3@example.com")
    await client.post(f"{API}/compliance/sox/certify", headers=owner, json=_SOX)
    base = f"{API}/decision-records"
    assert len((await client.get(f"{base}?decided_by={user_id}", headers=owner)).json()["data"]) == 1
    assert (await client.get(f"{base}?decided_by=someone-else", headers=owner)).json()["data"] == []
    assert len((await client.get(f"{base}?since=2020-01-01T00:00:00", headers=owner)).json()["data"]) == 1
    assert (await client.get(f"{base}?since=2999-01-01T00:00:00Z", headers=owner)).json()["data"] == []
    assert (await client.get(f"{base}?until=2020-01-01", headers=owner)).json()["data"] == []
