"""Plan v7 §P0 / W3 — a missing external service is a reasoned 503, not a 500.

Live audit 2026-10-24: `/chat/job/{id}` with no LLM key and
`/reports/{id}/executive-pdf` with no Pango/GObject both returned an unhandled
500 ("İç sunucu hatası"). The numbers were fine; only the service was missing.
"""
from __future__ import annotations

import builtins

import pytest

from tests.api_helpers import bellek_istemcisi, kullanici, ornek_rapor


async def _job_with_dashboard(client, org_id: str) -> str:
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.report import Report, ReportFormat, ReportType

    async with client._maker() as db:
        job = AnalysisJob(filename="x.csv", file_path="/x.csv", file_type="csv",
                          org_id=org_id, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        db.add(Report(job_id=job.id, report_type=ReportType.FULL,
                      report_format=ReportFormat.JSON, data=ornek_rapor()))
        await db.commit()
        return job.id


async def test_chat_without_an_llm_is_503_llm_unavailable(monkeypatch):
    from app.platform import model_gateway

    async def no_model(*a, **k):
        raise model_gateway.LLMUnavailable("openai_api_key is a placeholder")

    monkeypatch.setattr(model_gateway, "complete_text", no_model)
    monkeypatch.setattr(model_gateway, "ainvoke", no_model, raising=False)
    async with bellek_istemcisi() as client:
        headers, org_id, _ = await kullanici(client, "sohbet@example.com")
        job_id = await _job_with_dashboard(client, org_id)
        res = await client.post(f"/api/v1/chat/job/{job_id}", headers=headers,
                                json={"question": "Nakit pistim kaç ay?"})
    assert res.status_code == 503, res.text
    body = res.json()
    assert body["error_code"] == "llm_unavailable"
    assert "placeholder" not in body["error"]  # no internals in the message


async def test_executive_pdf_without_an_engine_is_503_pdf_engine_unavailable(monkeypatch):
    real_import = builtins.__import__

    def no_pango(name, *args, **kwargs):
        if name == "weasyprint":
            raise OSError("cannot load library 'libgobject-2.0-0': error 0x7e")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pango)
    async with bellek_istemcisi() as client:
        headers, org_id, _ = await kullanici(client, "pdf@example.com")
        job_id = await _job_with_dashboard(client, org_id)
        res = await client.get(f"/api/v1/reports/{job_id}/executive-pdf", headers=headers)
    assert res.status_code == 503, res.text
    body = res.json()
    assert body["error_code"] == "pdf_engine_unavailable"
    assert "libgobject" not in body["error"]


@pytest.mark.parametrize("exc_name", ["LLMUnavailable"])
def test_the_handler_is_registered(exc_name):
    from app.main import app
    from app.platform import model_gateway

    assert getattr(model_gateway, exc_name) in app.exception_handlers
