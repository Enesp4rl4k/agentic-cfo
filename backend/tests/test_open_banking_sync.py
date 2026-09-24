"""An open-banking sync becomes an analysis, and the bank token stays out of URLs.

The fetched rows were written to a Redis key nothing ever read (`ob_transactions:*`),
on a job with no file: the analysis failed with "file not found" while the
endpoint answered "queued". And the bank's access token was a query parameter,
written into every access and proxy log on the way.
"""
from __future__ import annotations

from typing import Any

import pytest_asyncio
from sqlalchemy import select

from tests.api_helpers import bellek_istemcisi, kullanici

URL = "/api/v1/open-banking/connections/c1/sync"


class _SahteBanka:
    def __init__(self, satirlar: list[dict[str, Any]]):
        self.satirlar = satirlar
        self.gelen_token: str | None = None

    async def get_transactions(self, access_token: str, account_id: str,
                               start_date: str, end_date: str) -> list[dict[str, Any]]:
        self.gelen_token = access_token
        return self.satirlar


@pytest_asyncio.fixture
async def client(monkeypatch, tmp_path):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path), raising=False)
    monkeypatch.setattr("app.api.open_banking._get_bank_settings", lambda bank_id: ("id", "secret", True))

    async def kuyruk(job_id, budget_input=None):
        return "queued"

    monkeypatch.setattr("app.worker.enqueue_analysis", kuyruk)
    async with bellek_istemcisi() as c:
        yield c


def _banka(monkeypatch, satirlar):
    banka = _SahteBanka(satirlar)
    monkeypatch.setattr("app.services.open_banking.get_bank_client", lambda *a, **k: banka)
    return banka


_SATIRLAR = [
    {"amount_cents": 1_250_000, "type": "income", "date": "2026-08-03", "description": "Tahsilat A"},
    {"amount_cents": -450_000, "type": "expense", "date": "2026-08-05", "description": "Kira"},
]


async def test_the_fetched_rows_become_an_analysis_with_a_file(client, monkeypatch):
    from app.models.analysis_job import AnalysisJob

    banka = _banka(monkeypatch, _SATIRLAR)
    headers, _, _ = await kullanici(client, "banka@example.com")
    r = await client.post(URL, headers=headers, json={
        "bank_id": "akbank", "account_id": "TR01", "access_token": "gizli-token",
    })
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["transaction_count"] == 2 and d["status"] == "queued" and d["job_id"]
    assert banka.gelen_token == "gizli-token"

    async with client._maker() as db:
        job = (await db.execute(select(AnalysisJob).where(AnalysisJob.id == d["job_id"]))).scalar_one()
    assert job.file_path, "iş bir dosyaya bağlı olmalı; eskiden boştu"
    assert job.filename.startswith("akbank_open_banking")


async def test_the_token_is_not_accepted_in_the_url(client, monkeypatch):
    _banka(monkeypatch, _SATIRLAR)
    headers, _, _ = await kullanici(client, "url@example.com")
    r = await client.post(f"{URL}?bank_id=akbank&account_id=TR01&access_token=gizli", headers=headers)
    assert r.status_code == 422


async def test_an_empty_pull_says_so_without_a_job(client, monkeypatch):
    _banka(monkeypatch, [])
    headers, _, _ = await kullanici(client, "bos@example.com")
    r = await client.post(URL, headers=headers, json={
        "bank_id": "akbank", "account_id": "TR01", "access_token": "t",
    })
    assert r.status_code == 200
    assert r.json()["data"] == {**r.json()["data"], "job_id": None, "status": "veri_yok"}
