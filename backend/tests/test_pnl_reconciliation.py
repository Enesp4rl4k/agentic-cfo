"""SMMM M3, first slice: measure how far the CFO's P&L and the journal agree.

Owner's order (2026-11-19): measure first, restructure after. The numbers in the
first test were MEASURED, not chosen: six ordinary bank movements run through
the real `_compute_pnl` and the real `DoubleEntryEngine`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.agents.accounting.double_entry import DoubleEntryEngine
from app.agents.pnl_agent import _compute_pnl
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.report import Report, ReportFormat, ReportType
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.services.accounting.approved_journal import uygula
from app.services.accounting.pnl_reconciliation import uzlastir
from app.services.accounting.thp_classifier import THPClassifier
from tests.api_helpers import kullanici

MIX = [
    {"id": "1", "amount_cents": 120_000, "kdv_kurus": 20_000, "type": "income", "category": "revenue",
     "description": "Satış faturası müşteri A"},
    {"id": "2", "amount_cents": 60_000, "kdv_kurus": 10_000, "type": "expense", "category": "cogs",
     "description": "Mal alımı tedarikçi B"},
    {"id": "3", "amount_cents": 500_000, "type": "expense", "category": "salary",
     "description": "Maaş ödemesi Ocak"},
    {"id": "4", "amount_cents": 100_000, "type": "expense", "category": "rent",
     "description": "Kira ödemesi ofis"},
    {"id": "5", "amount_cents": 200_000, "type": "expense", "category": "loan",
     "description": "Kredi taksit ödemesi"},
    {"id": "6", "amount_cents": 50_000, "type": "expense", "category": "tax",
     "description": "Gelir vergisi ödemesi"},
]


def _journal(txs):
    eng, clf = DoubleEntryEngine(), THPClassifier()
    return [
        eng.create_entry(
            {**t, "transaction_date": "2026-01-05T00:00:00+00:00"},
            clf.classify(t["description"], t["amount_cents"], t["type"]),
        ).to_dict()
        for t in txs
    ]


def _entry(kayit_id, *lines, hesap="770", gerek=False):
    return {
        "kayit_id": kayit_id, "thp_hesap_kodu": hesap, "aciklama": kayit_id, "onay_gerekli": gerek,
        "toplam_borc": sum(b for _, b, _ in lines),
        "satirlar": [{"hesap_kodu": k, "borc": b, "alacak": a} for k, b, a in lines],
    }


def test_measured_on_a_realistic_mix_the_two_disagree_and_the_causes_are_listed():
    entries = _journal(MIX)
    r = uzlastir(_compute_pnl(MIX), entries, [])

    # The P&L counts what was received and paid; the journal booked settlements.
    assert r["pnl"] == {"gelir_kurus": 120_000, "gider_kurus": 910_000}
    assert r["yevmiye_onayli"]["gelir_kurus"] == 20_000  # only the KDV: revenue went to 120 (receivable)
    assert r["fark"]["gelir_kurus"] == 100_000
    assert not r["tutuyor"]
    # The entries that went to balance-sheet accounts are listed as the likely cause.
    hesaplar = {b["hesap"] for b in r["bilanco_kayitlari"]}
    assert {"120", "320", "360"} <= hesaplar
    assert r["notlar"]


def test_kdv_alone_is_never_a_difference():
    # Gross 120.000 in the P&L; the journal splits 100.000 revenue + 20.000 KDV.
    e = _entry("a", ("102", 120_000, 0), ("600", 0, 100_000), ("391", 0, 20_000), hesap="600")
    r = uzlastir({"revenue": 120_000, "total_expenses": 0}, [e], [])
    assert r["fark"] == {"gelir_kurus": 0, "gider_kurus": 0} and r["tutuyor"]
    assert r["yevmiye_onayli"]["kdv_hesaplanan_kurus"] == 20_000


def test_input_kdv_on_a_cost_is_not_a_difference_either():
    e = _entry("a", ("770", 100_000, 0), ("191", 20_000, 0), ("102", 0, 120_000))
    r = uzlastir({"revenue": 0, "total_expenses": 120_000}, [e], [])
    assert r["tutuyor"]


def test_an_entry_left_out_is_its_own_line_not_an_unexplained_difference():
    onayli = _entry("a", ("102", 100_000, 0), ("600", 0, 100_000), hesap="600")
    disarida = _entry("b", ("102", 40_000, 0), ("600", 0, 40_000), hesap="600", gerek=True)
    r = uzlastir({"revenue": 140_000, "total_expenses": 0}, [onayli], [disarida])
    assert r["yevmiye_onaysiz"] == {"gelir_kurus": 40_000, "gider_kurus": 0, "kayit_sayisi": 1}
    assert r["fark"]["gelir_kurus"] == 0 and r["tutuyor"]
    assert any("onaylı yevmiyede yok" in n for n in r["notlar"])


def test_a_real_residual_is_reported_to_the_kurus():
    e = _entry("a", ("102", 99_999, 0), ("600", 0, 99_999), hesap="600")
    r = uzlastir({"revenue": 100_000, "total_expenses": 0}, [e], [])
    assert r["fark"]["gelir_kurus"] == 1 and not r["tutuyor"]


def test_a_return_reduces_both_sides_the_same_way():
    # A sale and its return (reversed lines): journal and P&L both net to 70.000.
    sale = _entry("s", ("102", 100_000, 0), ("600", 0, 100_000), hesap="600")
    ret = _entry("r", ("600", 30_000, 0), ("102", 0, 30_000), hesap="600")
    r = uzlastir({"revenue": 70_000, "total_expenses": 0}, [sale, ret], [])
    assert r["tutuyor"] and r["yevmiye_onayli"]["gelir_kurus"] == 70_000


def test_it_reads_the_approved_journal_as_the_accountant_left_it():
    entries = [
        _entry("ok", ("102", 100_000, 0), ("600", 0, 100_000), hesap="600", gerek=True),
        _entry("rejected", ("102", 40_000, 0), ("600", 0, 40_000), hesap="600", gerek=True),
    ]
    onaylar = [
        SimpleNamespace(kayit_id="ok", durum=OnayDurumu.ONAYLANDI.value),
        SimpleNamespace(kayit_id="rejected", durum=OnayDurumu.REDDEDILDI.value),
    ]
    a = uygula(entries, onaylar)
    disarida = [e for e in entries if e["kayit_id"] in a.excluded]
    r = uzlastir({"revenue": 140_000, "total_expenses": 0}, a.entries, disarida)
    assert r["tutuyor"] and r["yevmiye_onaysiz"]["kayit_sayisi"] == 1


# ── through the route ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_route_reads_the_dashboard_pnl_and_the_approved_journal(client):
    from app.models.organization import Organization

    h, org, uid = await kullanici(client, "uz@x.com", role="owner")
    async with client._maker() as db:
        (await db.get(Organization, org)).regional_packs = ["tr"]
        job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv",
                          org_id=org, user_id=uid, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        db.add(Report(job_id=job.id, report_type=ReportType.FULL, report_format=ReportFormat.JSON,
                      data={"pnl": {"revenue": 140_000, "total_expenses": 0}}))
        ok = _entry("ok", ("102", 100_000, 0), ("600", 0, 100_000), hesap="600", gerek=True)
        rej = _entry("rej", ("102", 40_000, 0), ("600", 0, 40_000), hesap="600", gerek=True)
        # Saved after the dashboard: the route must not mistake it for the dashboard.
        db.add(Report(job_id=job.id, report_type="tr_muhasebe_journal", report_format=ReportFormat.JSON,
                      data={"yevmiye_kayitlari": [ok, rej]}))
        db.add(SMMMOnayKaydi(job_id=job.id, org_id=org, kayit_id="ok", orijinal_kayit=ok,
                             durum=OnayDurumu.ONAYLANDI))
        db.add(SMMMOnayKaydi(job_id=job.id, org_id=org, kayit_id="rej", orijinal_kayit=rej,
                             durum=OnayDurumu.REDDEDILDI))
        await db.commit()
        job_id = job.id

    r = await client.get(f"/api/v1/muhasebe/{job_id}/uzlastirma", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["pnl"]["gelir_kurus"] == 140_000
    assert d["yevmiye_onayli"]["gelir_kurus"] == 100_000
    assert d["yevmiye_onaysiz"]["gelir_kurus"] == 40_000
    assert d["tutuyor"] is True
    assert datetime.now(UTC)  # (keeps the import honest)
