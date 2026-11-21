"""The account a statement is from survives the upload paths, so a remembered answer can be applied (and checked)."""
from __future__ import annotations

import pytest

from tests.test_ingest import XLSX, _login, _xlsx

UNBALANCED = _xlsx(
    ["AKBANK T.A.Ş. HESAP HAREKETLERİ"], ["Hesap No: 1234567"], [],
    ["İşlem Tarihi", "Açıklama", "Borç", "Alacak"],
    ["05.01.2024", "Ofis kirası", "28.500,00", None],
    ["06.01.2024", "EFT gelen - ABC Ltd", None, "10.000,00"],
)
NO_ACCOUNT = _xlsx(
    ["Hesap hareketleri"], [],
    ["İşlem Tarihi", "Açıklama", "Borç", "Alacak"],
    ["05.01.2024", "Ofis kirası", "28.500,00", None],
    ["06.01.2024", "EFT gelen - ABC Ltd", None, "10.000,00"],
)
UNAMBIGUOUS = _xlsx(
    ["İşlem Tarihi", "Açıklama", "Çıkış", "Giriş"],
    ["05.01.2024", "Ofis kirası", "28.500,00", None],
    ["06.01.2024", "EFT gelen - ABC Ltd", None, "10.000,00"],
)


async def _ingested(client, name: str, data: bytes):
    from app.agents.data_ingestion import run_data_ingestion
    from app.agents.state import AgentRunConfig
    from app.models.analysis_job import AnalysisJob

    h = await _login(client)
    r = await client.post("/api/v1/veri/ekle", files=[("files", (name, data, XLSX))], headers=h)
    assert r.status_code == 201, r.text
    async with client._maker() as db:
        job = await db.get(AnalysisJob, r.json()["data"]["job_id"])
        out = await run_data_ingestion({"file_path": job.file_path, "file_type": job.file_type, "job_id": job.id}, AgentRunConfig())
    return [*(out.patch or {}).get("transactions", []), *(out.patch or {}).get("held_transactions", [])]


@pytest.mark.asyncio
async def test_the_upload_page_path_keeps_the_account_so_the_answer_can_be_remembered(client):
    rows = await _ingested(client, "ekstre.xlsx", UNBALANCED)
    assert {r["direction_file"]["reason"] for r in rows} == {"convention_unverified"}
    assert {r["direction_file"]["identity"] for r in rows} == {True}


@pytest.mark.asyncio
async def test_a_file_that_names_no_account_says_so_and_cannot_be_remembered(client):
    rows = await _ingested(client, "ekstre.xlsx", NO_ACCOUNT)
    assert {r["direction_file"]["identity"] for r in rows} == {False}


@pytest.mark.asyncio
async def test_unambiguous_words_book_through_the_upload_page_path(client):
    rows = await _ingested(client, "ekstre.xlsx", UNAMBIGUOUS)
    assert sorted((r["type"], r["amount_cents"]) for r in rows) == [("expense", 2_850_000), ("income", 1_000_000)]
