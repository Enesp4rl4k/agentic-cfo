"""Plan M0: a re-driven run leaves the same things behind as the first run.

`POST /runs/{id}/resume` re-ran the TR pipeline and saved neither the journal
(so the e-Defter and the defensibility packet had nothing to read) nor the
review rows (so /smmm-onay stayed empty). Both now go through
`persist_tr_vertical_result`, which is what is tested here.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.organization import Organization
from app.models.report import Report
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.services.accounting.journal_store import (
    MUHASEBE_JOURNAL_REPORT,
    persist_tr_vertical_result,
)


def _result(kayit_ids):
    return SimpleNamespace(
        accounting={
            "dengeli": True,
            "onay_kuyrugu": [
                {"kayit_id": k, "thp_hesap_kodu": "770", "confidence": 0.5, "onay_neden": "test"}
                for k in kayit_ids
            ],
        },
        accounting_journal=[{"kayit_id": k, "onay_gerekli": True, "satirlar": []} for k in kayit_ids],
    )


@pytest.mark.asyncio
async def test_resume_saves_journal_and_review_rows_and_replaces_stale_pending(client):
    async with client._maker() as db:
        org = Organization(name="Org", slug="org-resume", regional_packs=["tr"])
        db.add(org)
        await db.flush()
        job = AnalysisJob(
            filename="a.csv", file_path="/a.csv", file_type="csv",
            org_id=org.id, status=JobStatus.COMPLETED,
        )
        db.add(job)
        await db.flush()
        # A decided row from the first run is history and must survive.
        db.add(
            SMMMOnayKaydi(
                job_id=job.id, org_id=org.id, kayit_id="old-decided",
                orijinal_kayit={}, durum=OnayDurumu.ONAYLANDI,
            )
        )
        db.add(
            SMMMOnayKaydi(
                job_id=job.id, org_id=org.id, kayit_id="old-pending",
                orijinal_kayit={}, durum=OnayDurumu.BEKLIYOR,
            )
        )
        await db.commit()

        n = await persist_tr_vertical_result(
            db, job_id=job.id, org_id=org.id, user_id="u1", result=_result(["n1", "n2"])
        )
        assert n == 2

        journal = (
            await db.execute(
                select(Report).where(
                    Report.job_id == job.id, Report.report_type == MUHASEBE_JOURNAL_REPORT
                )
            )
        ).scalar_one()
        assert [e["kayit_id"] for e in journal.data["yevmiye_kayitlari"]] == ["n1", "n2"]

        rows = (
            await db.execute(select(SMMMOnayKaydi.kayit_id, SMMMOnayKaydi.durum).where(
                SMMMOnayKaydi.job_id == job.id))
        ).all()
        by_id = {k: str(d) for k, d in rows}
        assert by_id == {
            "old-decided": OnayDurumu.ONAYLANDI.value,
            "n1": OnayDurumu.BEKLIYOR.value,
            "n2": OnayDurumu.BEKLIYOR.value,
        }


@pytest.mark.asyncio
async def test_no_accounting_result_saves_nothing(client):
    async with client._maker() as db:
        n = await persist_tr_vertical_result(
            db, job_id="j", org_id=None, user_id="u",
            result=SimpleNamespace(accounting=None, accounting_journal=None),
        )
        assert n == 0
