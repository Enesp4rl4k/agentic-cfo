"""The accountant's decisions survive a re-run of the accounting pipeline.

Each journal entry got a fresh `uuid4` per run, and `SMMMOnayKaydi.kayit_id`
points at it. Re-running the pipeline on the same job (or re-analysing the
file, which re-inserts its transactions with new ids) gave every entry a new
id: an approved entry no longer matched its approval, so it fell out of the
e-Defter and the mizan as "pending" and went back into the accountant's queue.

Now the id comes from the source transaction's content, and a decision carries
over as long as it is about the same proposal (same proposed account).
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents.accounting.double_entry import DoubleEntryEngine, kararli_kayit_id
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.organization import Organization
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.services.accounting.approved_journal import uygula
from app.services.accounting.journal_store import persist_tr_vertical_result
from app.services.accounting.thp_classifier import THPSonucu


def _thp(kod: str = "770") -> THPSonucu:
    return THPSonucu(
        hesap_kodu=kod, hesap_adi="Genel Yönetim Giderleri", ana_grup="7",
        normal_bakiye="borç", tip="gider", confidence=0.5, yontem="kural", aciklama="test",
    )


def _txs(prefix: str) -> list[dict]:
    return [
        {"id": f"{prefix}-1", "transaction_date": "2026-09-01", "amount_kurus": 150_000,
         "type": "expense", "description": "Kira Eylül"},
        # Two equal payments on one day: two entries, two ids.
        {"id": f"{prefix}-2", "transaction_date": "2026-09-02", "amount_kurus": 9_900,
         "type": "expense", "description": "Kargo"},
        {"id": f"{prefix}-3", "transaction_date": "2026-09-02", "amount_kurus": 9_900,
         "type": "expense", "description": "Kargo"},
    ]


def test_the_same_transactions_get_the_same_entry_ids_on_every_run() -> None:
    engine = DoubleEntryEngine()
    first = engine.create_entries_batch(_txs("run1"), [_thp()] * 3)
    # Re-analysis re-inserts transactions with new ids; the content is the same.
    second = engine.create_entries_batch(_txs("run2"), [_thp()] * 3)
    assert [e.kayit_id for e in first] == [e.kayit_id for e in second]
    assert len({e.kayit_id for e in first}) == 3


def test_a_date_read_back_from_the_database_gives_the_same_id() -> None:
    as_text = {"transaction_date": "2026-09-01", "amount_kurus": 150_000,
               "type": "expense", "description": "Kira Eylül"}
    as_datetime = {**as_text, "transaction_date": datetime(2026, 9, 1, tzinfo=UTC)}
    assert kararli_kayit_id(as_text) == kararli_kayit_id(as_datetime)


def test_a_different_transaction_gets_a_different_id() -> None:
    base = {"transaction_date": "2026-09-01", "amount_kurus": 150_000,
            "type": "expense", "description": "Kira Eylül"}
    assert kararli_kayit_id(base) != kararli_kayit_id({**base, "amount_kurus": 150_001})


def _run(entries: list[tuple[str, str]]) -> SimpleNamespace:
    """A TR result whose entries (kayit_id, proposed account) are all held for review."""
    journal = [
        {"kayit_id": k, "onay_gerekli": True, "thp_hesap_kodu": kod,
         "satirlar": [
             {"hesap_kodu": kod, "hesap_adi": "x", "borc": 100, "alacak": 0},
             {"hesap_kodu": "102", "hesap_adi": "Bankalar", "borc": 0, "alacak": 100},
         ]}
        for k, kod in entries
    ]
    queue = [{"kayit_id": k, "thp_hesap_kodu": kod, "confidence": 0.5} for k, kod in entries]
    return SimpleNamespace(
        accounting={"dengeli": True, "onay_kuyrugu": queue},
        accounting_journal=journal,
    )


async def _job(db) -> tuple[str, str]:
    org = Organization(name="Org", slug="org-stable-ids", regional_packs=["tr"])
    db.add(org)
    await db.flush()
    job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv",
                      org_id=org.id, status=JobStatus.COMPLETED)
    db.add(job)
    await db.commit()
    return job.id, org.id


async def _approve(db, job_id: str, kayit_id: str) -> None:
    row = (await db.execute(select(SMMMOnayKaydi).where(
        SMMMOnayKaydi.job_id == job_id, SMMMOnayKaydi.kayit_id == kayit_id,
        SMMMOnayKaydi.durum == OnayDurumu.BEKLIYOR,
    ))).scalar_one()
    row.durum = OnayDurumu.ONAYLANDI
    row.onay_zamani = datetime.now(UTC)
    await db.commit()


async def _rows(db, job_id: str) -> list[SMMMOnayKaydi]:
    return list((await db.execute(
        select(SMMMOnayKaydi).where(SMMMOnayKaydi.job_id == job_id)
    )).scalars().all())


@pytest.mark.asyncio
async def test_an_approval_still_counts_after_the_pipeline_runs_again(client) -> None:
    async with client._maker() as db:
        job_id, org_id = await _job(db)
        result = _run([("a", "770"), ("b", "770")])

        assert await persist_tr_vertical_result(
            db, job_id=job_id, org_id=org_id, user_id="u", result=result) == 2
        await _approve(db, job_id, "a")

        # The same journal again: "a" is decided, only "b" waits.
        assert await persist_tr_vertical_result(
            db, job_id=job_id, org_id=org_id, user_id="u", result=_run([("a", "770"), ("b", "770")])
        ) == 1

        rows = await _rows(db, job_id)
        filed = uygula(result.accounting_journal, rows)
        assert [e["kayit_id"] for e in filed.entries] == ["a"]
        assert filed.excluded == {"b": OnayDurumu.BEKLIYOR.value}
        assert sum(1 for r in rows if r.kayit_id == "a") == 1


@pytest.mark.asyncio
async def test_a_changed_proposal_goes_back_to_the_accountant(client) -> None:
    async with client._maker() as db:
        job_id, org_id = await _job(db)
        await persist_tr_vertical_result(
            db, job_id=job_id, org_id=org_id, user_id="u", result=_run([("a", "770")]))
        await _approve(db, job_id, "a")

        # The agent now proposes 760 for the same entry. The approval was of 770.
        rerun = _run([("a", "760")])
        assert await persist_tr_vertical_result(
            db, job_id=job_id, org_id=org_id, user_id="u", result=rerun) == 1

        rows = await _rows(db, job_id)
        filed = uygula(rerun.accounting_journal, rows)
        assert filed.entries == []
        assert filed.excluded == {"a": OnayDurumu.BEKLIYOR.value}
        # The old decision is history, not overwritten.
        assert {str(r.durum) for r in rows} == {
            OnayDurumu.ONAYLANDI.value, OnayDurumu.BEKLIYOR.value,
        }
