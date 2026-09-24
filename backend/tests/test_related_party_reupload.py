"""Re-uploading the same statement does not double a counterparty.

`GET /related-parties/suggestions` reads every analysis of the organisation,
and the same statement or overlapping months are routinely uploaded more than
once. Counted per analysis row, each re-upload doubled a counterparty's
frequency and total — the numbers the list ranks by.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest_asyncio

from tests.api_helpers import bellek_istemcisi, kullanici

KIRA = 45_000_00  # kuruş


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _analiz(client, org_id: str, aylar: list[int], *, satici: str = "Öztürk Gayrimenkul") -> None:
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.transaction import Transaction

    async with client._maker() as db:
        job = AnalysisJob(filename="ekstre.csv", file_path="/e.csv", file_type="csv",
                          org_id=org_id, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        for ay in aylar:
            db.add(Transaction(job_id=job.id, amount_kurus=KIRA, currency="TRY", type="expense",
                               category="rent", vendor=satici, description=f"Kira {ay}. ay",
                               transaction_date=datetime(2026, ay, 5, tzinfo=UTC)))
        await db.commit()


async def _oneriler(client, headers) -> dict[str, dict]:
    r = await client.get("/api/v1/related-parties/suggestions", headers=headers)
    assert r.status_code == 200, r.text
    return {s["normalized_name"]: s for s in r.json()["data"]["suggestions"]}


async def test_the_same_months_uploaded_twice_count_once(client):
    headers, org_id, _ = await kullanici(client, "kira@example.com")
    await _analiz(client, org_id, [1, 2, 3])
    await _analiz(client, org_id, [1, 2, 3])          # the same statement again

    (oneri,) = (await _oneriler(client, headers)).values()
    assert oneri["transaction_count"] == 3
    assert oneri["total_kurus"] == 3 * KIRA


async def test_overlapping_months_count_each_payment_once(client):
    headers, org_id, _ = await kullanici(client, "ortusen@example.com")
    await _analiz(client, org_id, [1, 2, 3])
    await _analiz(client, org_id, [2, 3, 4])          # Feb–Mar overlap

    (oneri,) = (await _oneriler(client, headers)).values()
    assert oneri["transaction_count"] == 4
    assert oneri["total_kurus"] == 4 * KIRA


async def test_another_organisations_payments_are_not_counted(client):
    _, org_a, _ = await kullanici(client, "a@example.com")
    headers_b, org_b, _ = await kullanici(client, "b@example.com")
    await _analiz(client, org_a, [1, 2, 3])
    await _analiz(client, org_b, [1, 2])

    (oneri,) = (await _oneriler(client, headers_b)).values()
    assert oneri["transaction_count"] == 2
