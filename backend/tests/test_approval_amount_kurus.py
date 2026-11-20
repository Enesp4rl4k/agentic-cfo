"""The accountant's review queue carries amounts in kuruş.

`tx_amount_try` was lira as NUMERIC(15,2), filled as `int / 100`, served as a
float, and `if k.tx_amount_try else None` turned a zero into null. It was the
one money field outside the kuruş rule. Now the queue stores and serves
`tx_amount_kurus`.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy import select

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.organization import Organization
from app.models.smmm_onay import SMMMOnayKaydi
from app.services.accounting.journal_store import persist_tr_vertical_result
from tests.api_helpers import bellek_istemcisi, kullanici


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _result(items: list[dict]) -> SimpleNamespace:
    queue = [{"kayit_id": f"k{i}", "thp_hesap_kodu": "770", "confidence": 0.5, **it}
             for i, it in enumerate(items)]
    journal = [{"kayit_id": q["kayit_id"], "onay_gerekli": True, "thp_hesap_kodu": "770", "satirlar": []}
               for q in queue]
    return SimpleNamespace(accounting={"dengeli": True, "onay_kuyrugu": queue}, accounting_journal=journal)


async def _job(client, org_id: str) -> str:
    async with client._maker() as db:
        org = await db.get(Organization, org_id)
        org.regional_packs = ["tr"]
        job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv",
                          org_id=org_id, status=JobStatus.COMPLETED)
        db.add(job)
        await db.commit()
        return job.id


async def test_the_queue_stores_and_serves_kurus_and_a_zero_stays_zero(client):
    headers, org_id, user_id = await kullanici(client, "kurus@example.com")
    job_id = await _job(client, org_id)
    async with client._maker() as db:
        await persist_tr_vertical_result(
            db, job_id=job_id, org_id=org_id, user_id=user_id,
            result=_result([{"tx_amount_kurus": 0}, {"tx_amount_kurus": 2_147_483_648_00}]),
        )

    res = await client.get(f"/api/v1/smmm/onay/queue/{job_id}", headers=headers)
    assert res.status_code == 200, res.text
    amounts = [k["tx_amount_kurus"] for k in res.json()["data"]["kayitlar"]]
    # Largest first; above the old 32-bit limit; zero is zero, not null.
    assert amounts == [2_147_483_648_00, 0]
    assert all("tx_amount_try" not in k for k in res.json()["data"]["kayitlar"])


async def test_a_queue_item_from_before_the_change_is_read_as_lira(client):
    _, org_id, user_id = await kullanici(client, "eski@example.com")
    job_id = await _job(client, org_id)
    async with client._maker() as db:
        await persist_tr_vertical_result(
            db, job_id=job_id, org_id=org_id, user_id=user_id,
            result=_result([{"tx_amount_try": 12.34}]),
        )
        row = (await db.execute(select(SMMMOnayKaydi).where(SMMMOnayKaydi.job_id == job_id))).scalar_one()
    assert row.tx_amount_kurus == 1_234
