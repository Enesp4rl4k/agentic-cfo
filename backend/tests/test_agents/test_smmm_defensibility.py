"""SMMM Defensibility Packet (differentiator #4) — assembly, hash, finalize."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main  # noqa: F401 — full model registration
from app.database import Base
from app.models.agent_run import AgentRun
from app.models.report import Report, ReportFormat
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.services.smmm_defensibility import (
    DefensibilityError,
    build_packet,
    content_hash,
    finalize_packet,
)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


def _entry(kayit_id: str, code: str, amount: int, *, needs_review: bool, conf: float):
    return {
        "kayit_id": kayit_id,
        "tarih": "2024-01-15T00:00:00+00:00",
        "aciklama": f"işlem {kayit_id}",
        "toplam_borc": amount,
        "toplam_alacak": amount,
        "dengeli": True,
        "confidence": conf,
        "onay_gerekli": needs_review,
        "onay_neden": "Yüksek tutar" if needs_review else "",
        "thp_hesap_kodu": code,
        "kaynak_islem_id": f"tx-{kayit_id}",
        "satirlar": [],
    }


async def _seed_journal(db, job_id="job-1", entries=None):
    db.add(Report(
        job_id=job_id, report_type="tr_muhasebe_journal", report_format=ReportFormat.JSON,
        data={
            "yevmiye_kayitlari": entries or [],
            "dengeli": True, "denge_hatalari": [],
            "ortalama_confidence": 0.87, "thp_dagilim": {"770": 2, "153": 1},
        },
    ))
    await db.commit()


async def _seed_onay(db, job_id, kayit_id, durum, *, org_id="org-1", corrected=None):
    db.add(SMMMOnayKaydi(
        job_id=job_id, org_id=org_id, kayit_id=kayit_id, durum=durum,
        otomatik_hesap_kodu="770",
        duzeltilmis_hesap_kodu=corrected,
        onaylayan_user_id="smmm-1" if durum != OnayDurumu.BEKLIYOR else None,
        onay_zamani=datetime.now(UTC) if durum != OnayDurumu.BEKLIYOR else None,
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_decision_source_classification(db):
    entries = [
        _entry("k1", "770", 10_000, needs_review=False, conf=0.95),  # ai_auto
        _entry("k2", "770", 500_000, needs_review=True, conf=0.55),  # -> approved
        _entry("k3", "153", 800_000, needs_review=True, conf=0.5),   # -> corrected
        _entry("k4", "770", 900_000, needs_review=True, conf=0.4),   # -> rejected
    ]
    await _seed_journal(db, entries=entries)
    await _seed_onay(db, "job-1", "k2", OnayDurumu.ONAYLANDI)
    await _seed_onay(db, "job-1", "k3", OnayDurumu.DUZELTILDI, corrected="255")
    await _seed_onay(db, "job-1", "k4", OnayDurumu.REDDEDILDI)

    packet = await build_packet(db=db, job_id="job-1", org_id="org-1", period="2024-01")
    src = {i["kayit_id"]: i["decision_source"] for i in packet.payload["entries"]}
    assert src == {
        "k1": "ai_auto_posted",
        "k2": "human_approved",
        "k3": "human_corrected",
        "k4": "rejected",
    }
    s = packet.summary
    assert s["entry_count"] == 4
    assert s["ai_auto_posted"] == 1
    assert s["human_reviewed"] == 2
    assert s["rejected"] == 1
    assert s["pending_review"] == 0
    # corrected entry keeps the before/after
    k3 = next(i for i in packet.payload["entries"] if i["kayit_id"] == "k3")
    assert k3["review"]["original_account"] == "770"
    assert k3["review"]["corrected_account"] == "255"


@pytest.mark.asyncio
async def test_pending_review_blocks_defensible_flag(db):
    entries = [_entry("k1", "770", 500_000, needs_review=True, conf=0.5)]
    await _seed_journal(db, entries=entries)  # no onay row → pending
    packet = await build_packet(db=db, job_id="job-1", org_id="org-1", period="2024-01")
    assert packet.summary["pending_review"] == 1
    assert packet.summary["defensible"] is False


@pytest.mark.asyncio
async def test_hash_is_stable_and_content_sensitive():
    p1 = {"summary": {"a": 1}, "entries": [{"x": 1}]}
    p2 = {"entries": [{"x": 1}], "summary": {"a": 1}}   # key order differs
    p3 = {"summary": {"a": 2}, "entries": [{"x": 1}]}
    assert content_hash(p1) == content_hash(p2)
    assert content_hash(p1) != content_hash(p3)


@pytest.mark.asyncio
async def test_build_pulls_run_metadata(db):
    await _seed_journal(db, entries=[_entry("k1", "770", 1000, needs_review=False, conf=0.9)])
    db.add(AgentRun(
        org_id="org-1", pipeline="tr_vertical", job_id="job-1", status="completed",
        latency_ms=1234.5, cost_usd=0.02,
        result_ref={"reconciliation": {"action": "proceed"},
                    "confidence_breakdown": {"aggregate": 0.9}},
    ))
    await db.commit()
    packet = await build_packet(db=db, job_id="job-1", org_id="org-1", period="2024-01")
    assert packet.summary["run"]["latency_ms"] == 1234.5
    assert packet.summary["reconciliation"] == {"action": "proceed"}
    assert packet.summary["confidence_breakdown"] == {"aggregate": 0.9}


@pytest.mark.asyncio
async def test_finalize_lifecycle(db):
    await _seed_journal(db, entries=[_entry("k1", "770", 1000, needs_review=False, conf=0.9)])
    packet = await build_packet(db=db, job_id="job-1", org_id="org-1", period="2024-01")
    draft_hash = packet.content_hash

    with pytest.raises(DefensibilityError, match="beyan"):
        await finalize_packet(db=db, packet_id=packet.id, user_id="smmm-1", statement="  ")

    final = await finalize_packet(
        db=db, packet_id=packet.id, user_id="smmm-1",
        statement="2024/01 dönemi kayıtlarını inceledim ve uygun buldum. SM. Ali Veli",
    )
    assert final.status == "finalized"
    assert final.finalized_by_user_id == "smmm-1"
    assert final.content_hash != draft_hash  # seal now covers the statement

    with pytest.raises(DefensibilityError, match="zaten"):
        await finalize_packet(db=db, packet_id=packet.id, user_id="smmm-1", statement="tekrar")

    # a finalized packet cannot be regenerated
    with pytest.raises(DefensibilityError, match="kesinleştir"):
        await build_packet(db=db, job_id="job-1", org_id="org-1", period="2024-01")


@pytest.mark.asyncio
async def test_finalize_blocked_by_pending(db):
    await _seed_journal(db, entries=[_entry("k1", "770", 500_000, needs_review=True, conf=0.5)])
    packet = await build_packet(db=db, job_id="job-1", org_id="org-1", period="2024-01")
    with pytest.raises(DefensibilityError, match="onay bekliyor"):
        await finalize_packet(db=db, packet_id=packet.id, user_id="smmm-1", statement="beyan metni")


@pytest.mark.asyncio
async def test_build_without_journal_errors(db):
    with pytest.raises(DefensibilityError, match="yevmiye"):
        await build_packet(db=db, job_id="missing", org_id="org-1", period="2024-01")
