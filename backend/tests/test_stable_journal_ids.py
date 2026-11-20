"""An accountant's decision survives a re-run of the same file.

The journal entry id (`kayit_id`) was a fresh uuid4 on every run. A re-run (a
resume, a second `tr-vertical`, a retry) therefore produced entries the earlier
decisions no longer matched: the approvals sat orphaned in the table, applied to
nothing, and the accountant was asked to decide the same entries again.

The id is now derived from the transaction behind the entry, so the same file
gives the same ids, a changed row gives a new one, and a decided row is neither
re-queued nor orphaned. (Audit 2026-11-20, first item; my own `enqueue_review`
said "decided rows stay as history", which was true and useless: they matched
nothing.)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agents.accounting.orchestrator import get_muhasebe_agent
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.services.accounting.approved_journal import uygula
from app.services.accounting.journal_store import enqueue_review
from tests.api_helpers import kullanici


def _tx(desc, amount=50_000, date="2026-01-05T00:00:00+00:00", **extra):
    return {"amount_kurus": amount, "type": "expense", "description": desc,
            "transaction_date": date, **extra}


async def _run(job_id, txs):
    agent = get_muhasebe_agent(use_llm_fallback=False, regional_packs=["tr"])
    r = await agent.run(job_id, txs)
    return [e["kayit_id"] for e in r.yevmiye_kayitlari], r


# ── the id ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_same_file_gives_the_same_ids():
    txs = [_tx("Kira ödemesi"), _tx("Maaş ödemesi", 300_000)]
    a, _ = await _run("job-1", txs)
    b, _ = await _run("job-1", [dict(t) for t in txs])
    assert a == b and len(set(a)) == 2


@pytest.mark.asyncio
async def test_a_changed_row_changes_only_its_own_id():
    a, _ = await _run("job-1", [_tx("Kira ödemesi"), _tx("Maaş ödemesi", 300_000)])
    b, _ = await _run("job-1", [_tx("Kira ödemesi"), _tx("Maaş ödemesi", 310_000)])
    assert a[0] == b[0] and a[1] != b[1]


@pytest.mark.asyncio
async def test_identical_rows_still_get_distinct_ids_and_keep_them_in_order():
    twin = [_tx("Kargo gideri"), _tx("Kargo gideri")]
    a, _ = await _run("job-1", twin)
    b, _ = await _run("job-1", [dict(t) for t in twin])
    assert a[0] != a[1] and a == b


@pytest.mark.asyncio
async def test_two_jobs_never_share_an_id():
    a, _ = await _run("job-1", [_tx("Kira ödemesi")])
    b, _ = await _run("job-2", [_tx("Kira ödemesi")])
    assert a != b


@pytest.mark.asyncio
async def test_the_review_queue_carries_the_same_ids_as_the_journal():
    ids, r = await _run("job-1", [_tx("Kira ödemesi")])
    assert {i["kayit_id"] for i in r.onay_kuyrugu} <= set(ids)


# ── a re-run keeps what was decided ──────────────────────────────────────────

async def _job(client, email):
    _h, org, uid = await kullanici(client, email, role="owner")
    async with client._maker() as db:
        job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv",
                          org_id=org, user_id=uid, status=JobStatus.COMPLETED)
        db.add(job)
        await db.commit()
        return job.id, org, uid


def _item(kayit_id):
    return {"kayit_id": kayit_id, "thp_hesap_kodu": "770", "confidence": 0.5, "onay_neden": "test"}


async def _rows(db, job_id):
    return {
        r.kayit_id: r
        for r in (await db.execute(select(SMMMOnayKaydi).where(SMMMOnayKaydi.job_id == job_id))).scalars()
    }


@pytest.mark.asyncio
async def test_a_decided_row_is_neither_requeued_nor_orphaned_by_a_rerun(client):
    job_id, org, uid = await _job(client, "k1@x.com")
    async with client._maker() as db:
        await enqueue_review(db, job_id=job_id, org_id=org, user_id=uid,
                             items=[_item("a"), _item("b")], packs=["tr"])
        await db.commit()
        rows = await _rows(db, job_id)
        rows["a"].durum = OnayDurumu.ONAYLANDI  # the accountant decides "a"
        await db.commit()

    # The same file, run again: the same two ids.
    async with client._maker() as db:
        await enqueue_review(db, job_id=job_id, org_id=org, user_id=uid,
                             items=[_item("a"), _item("b")], packs=["tr"])
        await db.commit()
        rows = await _rows(db, job_id)
    assert set(rows) == {"a", "b"}
    assert rows["a"].durum == OnayDurumu.ONAYLANDI  # kept, not duplicated, not reset
    assert rows["b"].durum == OnayDurumu.BEKLIYOR


@pytest.mark.asyncio
async def test_a_pending_row_that_no_longer_exists_goes_and_a_new_entry_is_queued(client):
    job_id, org, uid = await _job(client, "k2@x.com")
    async with client._maker() as db:
        await enqueue_review(db, job_id=job_id, org_id=org, user_id=uid,
                             items=[_item("a"), _item("b")], packs=["tr"])
        await db.commit()
        keep = (await _rows(db, job_id))["a"].id
    async with client._maker() as db:
        await enqueue_review(db, job_id=job_id, org_id=org, user_id=uid,
                             items=[_item("a"), _item("c")], packs=["tr"])
        await db.commit()
        rows = await _rows(db, job_id)
    assert set(rows) == {"a", "c"}
    assert rows["a"].id == keep  # the surviving pending row is the same row, not recreated


def test_a_decision_applies_to_the_rerun_journal():
    # The point of it all: yesterday's approval is today's approval.
    entries = [{"kayit_id": "stable", "onay_gerekli": True, "thp_hesap_kodu": "770",
                "satirlar": [{"hesap_kodu": "770", "borc": 100, "alacak": 0},
                             {"hesap_kodu": "102", "borc": 0, "alacak": 100}]}]
    onay = [SimpleNamespace(kayit_id="stable", durum=OnayDurumu.ONAYLANDI.value)]
    assert [e["kayit_id"] for e in uygula(entries, onay).entries] == ["stable"]


# ── one decision per entry ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_entry_cannot_have_two_review_rows(client):
    job_id, org, _uid = await _job(client, "k3@x.com")
    async with client._maker() as db:
        for _ in range(2):
            db.add(SMMMOnayKaydi(job_id=job_id, org_id=org, kayit_id="dup", orijinal_kayit={},
                                 durum=OnayDurumu.BEKLIYOR))
        with pytest.raises(IntegrityError):
            await db.commit()
