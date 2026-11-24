"""Pages of an uploaded PDF that yielded no text reach the field the upload result screen renders.

From the reading door (a generated PDF through `run_cfo_analysis`: the real child process, the ingestion step, the
worker's job metadata) to `GET /api/v1/analysis/{job}` -> `data.ingest.pages_not_read`, which `IngestCounts.tsx` shows.
"""
from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio

import app.agents.data_ingestion as di
import app.database as database
from tests.api_helpers import arka_plan_bitsin, bellek_istemcisi, kullanici

pymupdf = pytest.importorskip("pymupdf")

ROW = "{d} HAVALE GELEN ODEME ACIKLAMA FATURA NO 2026 {a} {b}"


@pytest_asyncio.fixture
async def ortam(monkeypatch, tmp_path):
    async with bellek_istemcisi() as c:
        monkeypatch.setattr(database, "get_session_factory", lambda eng=None: c._maker)
        monkeypatch.setattr(database, "session_factory", lambda: c._maker)
        monkeypatch.setattr(database, "engine", lambda: None)
        from app.services import review_continuation as rc

        async def devam_yok(job_id: str) -> str:
            return "skipped"

        monkeypatch.setattr(rc, "devami_baslat", devam_yok)
        yield c, tmp_path
        await arka_plan_bitsin()


def statement_with(tmp_path, last_page) -> str:
    doc = pymupdf.open()
    doc.new_page().insert_text((40, 72), "\n".join([ROW.format(d="01.03.2026", a="500,00", b="10.500,00"), ROW.format(d="02.03.2026", a="250,00", b="10.750,00")]), fontsize=8)
    last_page(doc)
    path = str(tmp_path / "ekstre.pdf")
    doc.save(path)
    doc.close()
    return path


def scan(doc) -> None:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40))
    pix.clear_with(200)
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=pix)


async def analysed(client, path: str, org_id, monkeypatch) -> dict[str, Any]:
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.worker import run_cfo_analysis

    async def fake_llm(raw_text: str, settings: Any) -> list[dict[str, Any]]:
        return [{"date": "02.03.2026", "amount": 250, "type": "expense", "description": "A", "confidence": 0.95}]

    monkeypatch.setattr(di, "_extract_transactions_with_llm", fake_llm)
    async with client._maker() as db:
        job = AnalysisJob(filename="ekstre.pdf", file_path=path, file_type="pdf", org_id=org_id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = job.id
    await run_cfo_analysis({}, job_id)
    return job_id


async def test_a_scanned_last_page_is_listed_on_the_analysis_result_with_its_reason_and_the_job_is_held(ortam, monkeypatch):
    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "sayfa@x.com")
    job_id = await analysed(client, statement_with(tmp_path, scan), org_id, monkeypatch)

    data = (await client.get(f"/api/v1/analysis/{job_id}", headers=headers)).json()["data"]
    (entry,) = data["ingest"]["pages_not_read"]
    assert entry["file"] == "ekstre.pdf"
    (page,) = entry["pages"]
    assert page["page"] == 2 and page["state"] == "hold"
    assert "taranmış görünüyor" in page["tr"] and "looks scanned" in page["en"]
    assert data["awaiting_review"] is True


async def test_a_logo_page_is_listed_as_a_note_and_does_not_hold(ortam, monkeypatch):
    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "logo@x.com")

    def logo(doc) -> None:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20))
        pix.clear_with(200)
        doc.new_page().insert_image(pymupdf.Rect(50, 50, 130, 130), pixmap=pix)

    job_id = await analysed(client, statement_with(tmp_path, logo), org_id, monkeypatch)
    data = (await client.get(f"/api/v1/analysis/{job_id}", headers=headers)).json()["data"]
    (page,) = data["ingest"]["pages_not_read"][0]["pages"]
    assert page["state"] == "note" and "görsel/boş sayfa" in page["tr"]
