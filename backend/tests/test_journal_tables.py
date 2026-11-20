"""A1.1–A1.2 (plan v11, ADR 0001): the journal is written to tables as well as to JSON.

The accounting journal lived only as one JSON document per job
(`reports.tr_muhasebe_journal`): no constraint that an entry balances, no query
by account code, and no way to prove the trial balance equals the P&L. Now
`persist_journal` also writes `journal_entries` / `journal_lines`. The JSON stays
the source every output reads until the shadow comparison below has held long
enough to move the readers (A1.3).

What the tables hold is what the agent *proposed*. The accountant's decisions
stay in `SMMMOnayKaydi` and are applied the same way to either source
(`approved_journal.uygula`), so the comparison is like for like.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.agents.accounting.double_entry import DoubleEntryEngine
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.journal import JournalEntry, JournalLine
from app.models.organization import Organization
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.services.accounting.approved_journal import mizan, uygula
from app.services.accounting.journal_store import persist_journal
from app.services.accounting.journal_tables import yevmiye_tablodan
from app.services.accounting.thp_classifier import THPSonucu
from tests.api_helpers import bellek_istemcisi


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _thp(kod: str, adi: str, confidence: float) -> THPSonucu:
    return THPSonucu(
        hesap_kodu=kod, hesap_adi=adi, ana_grup=kod[0], normal_bakiye="borç",
        tip="gider", confidence=confidence, yontem="kural", aciklama="test",
    )


def _journal() -> list[dict]:
    """Real entries from the engine: auto-posted, held, and two equal payments."""
    txs = [
        {"id": "t1", "transaction_date": "2026-10-01", "amount_kurus": 1_500_000,
         "type": "expense", "description": "Kira Ekim"},
        {"id": "t2", "transaction_date": "2026-10-03", "amount_kurus": 9_900,
         "type": "expense", "description": "Kargo"},
        {"id": "t3", "transaction_date": "2026-10-03", "amount_kurus": 9_900,
         "type": "expense", "description": "Kargo"},
        {"id": "t4", "transaction_date": "2026-10-05", "amount_kurus": 420_000,
         "type": "expense", "description": "Danışmanlık"},
    ]
    thps = [
        _thp("770", "Genel Yönetim Giderleri", 0.99),
        _thp("760", "Pazarlama Satış Dağıtım Giderleri", 0.40),
        _thp("760", "Pazarlama Satış Dağıtım Giderleri", 0.40),
        _thp("770", "Genel Yönetim Giderleri", 0.40),
    ]
    entries = [e.to_dict() for e in DoubleEntryEngine().create_entries_batch(txs, thps)]
    # With no accuracy history every entry is held; the rent entry stands for one
    # the policy let through, so both kinds are compared.
    entries[0]["onay_gerekli"] = False
    assert any(e["onay_gerekli"] for e in entries) and any(not e["onay_gerekli"] for e in entries)
    return entries


async def _job(db, slug: str) -> tuple[str, str]:
    org = Organization(name="Org", slug=slug, regional_packs=["tr"])
    db.add(org)
    await db.flush()
    job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv",
                      org_id=org.id, status=JobStatus.COMPLETED)
    db.add(job)
    await db.commit()
    return job.id, org.id


async def _count(db, model, job_id: str) -> int:
    if model is JournalEntry:
        q = select(func.count()).select_from(JournalEntry).where(JournalEntry.job_id == job_id)
    else:
        q = (select(func.count()).select_from(JournalLine)
             .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
             .where(JournalEntry.job_id == job_id))
    return int((await db.execute(q)).scalar_one())


@pytest.mark.asyncio
async def test_persisting_the_journal_writes_every_entry_and_line(client) -> None:
    async with client._maker() as db:
        job_id, org_id = await _job(db, "jt-write")
        entries = _journal()
        await persist_journal(db, job_id, {"yevmiye_kayitlari": entries})
        await db.commit()

        assert await _count(db, JournalEntry, job_id) == len(entries)
        assert await _count(db, JournalLine, job_id) == sum(len(e["satirlar"]) for e in entries)
        row = (await db.execute(select(JournalEntry).where(JournalEntry.job_id == job_id))).scalars().first()
        assert row is not None and row.org_id == org_id


@pytest.mark.asyncio
async def test_running_again_replaces_the_rows_instead_of_adding_to_them(client) -> None:
    async with client._maker() as db:
        job_id, _ = await _job(db, "jt-rerun")
        entries = _journal()
        for _ in range(2):
            await persist_journal(db, job_id, {"yevmiye_kayitlari": entries})
            await db.commit()
        assert await _count(db, JournalEntry, job_id) == len(entries)


@pytest.mark.asyncio
async def test_the_tables_give_back_the_entries_the_json_holds(client) -> None:
    async with client._maker() as db:
        job_id, _ = await _job(db, "jt-roundtrip")
        entries = _journal()
        await persist_journal(db, job_id, {"yevmiye_kayitlari": entries})
        await db.commit()

        back = await yevmiye_tablodan(db, job_id)
        keys = ("kayit_id", "onay_gerekli", "thp_hesap_kodu", "toplam_borc", "toplam_alacak")
        assert [{k: e[k] for k in keys} for e in back] == [{k: e[k] for k in keys} for e in entries]
        assert [e["satirlar"] for e in back] == [
            [{k: s[k] for k in ("hesap_kodu", "hesap_adi", "borc", "alacak", "aciklama")}
             for s in e["satirlar"]]
            for e in entries
        ]


@pytest.mark.asyncio
async def test_shadow_comparison_trial_balance_is_the_same_from_json_and_from_tables(client) -> None:
    """F7's first half: with the accountant's decisions applied, both sources give
    the same trial balance to the kuruş. This is the check that must hold before
    any reader moves to the tables (A1.3)."""
    async with client._maker() as db:
        job_id, org_id = await _job(db, "jt-shadow")
        entries = _journal()
        await persist_journal(db, job_id, {"yevmiye_kayitlari": entries})
        held = [e for e in entries if e["onay_gerekli"]]
        now = datetime.now(UTC)
        decisions = [
            (held[0], OnayDurumu.ONAYLANDI, None),
            (held[1], OnayDurumu.DUZELTILDI, "740"),
            (held[2], OnayDurumu.REDDEDILDI, None),
        ]
        for entry, durum, yeni in decisions:
            db.add(SMMMOnayKaydi(
                job_id=job_id, org_id=org_id, created_by_user_id="u", kayit_id=entry["kayit_id"],
                orijinal_kayit=entry, durum=durum, otomatik_hesap_kodu=entry["thp_hesap_kodu"],
                duzeltilmis_hesap_kodu=yeni, onay_zamani=now,
            ))
        await db.commit()
        onaylar = (await db.execute(
            select(SMMMOnayKaydi).where(SMMMOnayKaydi.job_id == job_id))).scalars().all()

        from_json = uygula(entries, onaylar)
        from_tables = uygula(await yevmiye_tablodan(db, job_id), onaylar)

        assert mizan(from_tables.entries) == mizan(from_json.entries)
        assert from_tables.excluded == from_json.excluded
        assert "740" in mizan(from_tables.entries)


@pytest.mark.asyncio
async def test_an_unbalanced_entry_is_not_written_and_is_reported(client, caplog) -> None:
    async with client._maker() as db:
        job_id, _ = await _job(db, "jt-unbalanced")
        entries = _journal()
        bad = {**entries[0], "kayit_id": "bozuk", "satirlar": [
            {"hesap_kodu": "770", "hesap_adi": "x", "borc": 100, "alacak": 0, "aciklama": ""},
            {"hesap_kodu": "102", "hesap_adi": "y", "borc": 0, "alacak": 90, "aciklama": ""},
        ]}
        with caplog.at_level(logging.ERROR, logger="app.services.accounting.journal_tables"):
            await persist_journal(db, job_id, {"yevmiye_kayitlari": [*entries, bad]})
            await db.commit()
        assert await _count(db, JournalEntry, job_id) == len(entries)
        assert any("bozuk" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_the_database_refuses_an_unbalanced_entry_or_a_two_sided_line(client) -> None:
    async with client._maker() as db:
        job_id, org_id = await _job(db, "jt-checks")
        db.add(JournalEntry(job_id=job_id, org_id=org_id, kayit_id="x", tarih=datetime.now(UTC),
                            toplam_borc_kurus=100, toplam_alacak_kurus=90))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

        entry = JournalEntry(job_id=job_id, org_id=org_id, kayit_id="y", tarih=datetime.now(UTC),
                             toplam_borc_kurus=100, toplam_alacak_kurus=100)
        db.add(entry)
        await db.flush()
        db.add(JournalLine(entry_id=entry.id, sira=0, hesap_kodu="770", hesap_adi="x",
                           borc_kurus=100, alacak_kurus=100))
        with pytest.raises(IntegrityError):
            await db.commit()
