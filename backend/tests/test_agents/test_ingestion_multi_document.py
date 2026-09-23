"""Ingestion reads every document of the analysis and puts the rows together.

The node read `state["file_path"]` and nothing else, so extra documents of the
same analysis (three invoices dropped together) could not be part of it. The
transactions are concatenated, the confidence is the lowest of the documents,
and a review needed for one is a review for the run.
"""
from __future__ import annotations

from typing import Any

import app.agents.data_ingestion as di
from app.agents.data_ingestion import run_data_ingestion
from app.agents.state import SkillResult


def _plant(monkeypatch, sonuclar: dict[str, SkillResult]) -> list[str]:
    """Each path answers with the result the test chose; records the order."""
    okunan: list[str] = []

    async def fake(file_path: str, file_type: str, state: Any, config: Any) -> SkillResult:
        okunan.append(file_path)
        return sonuclar[file_path]

    monkeypatch.setattr(di, "_belgeyi_al", fake)
    return okunan


def _ok(n: int, *, conf: float = 0.95, review: bool = False, text: str = "x") -> SkillResult:
    return SkillResult(
        ok=True, confidence=conf, needs_review=review, detail=f"{n} işlem",
        patch={"raw_text": text, "transactions": [{"i": i} for i in range(n)]},
    )


async def test_one_document_behaves_exactly_as_before(monkeypatch):
    _plant(monkeypatch, {"ana.xml": _ok(2)})
    out = await run_data_ingestion({"file_path": "ana.xml", "file_type": "xml"}, None)
    assert out.ok and len(out.patch["transactions"]) == 2
    assert out.detail == "2 işlem"          # untouched, no summary wrapper


async def test_rows_from_every_document_are_kept(monkeypatch):
    okunan = _plant(monkeypatch, {
        "ana.xml": _ok(2, text="bir"),
        "ek1.xml": _ok(3, text="iki"),
        "ek2.xml": _ok(1, text="üç"),
    })
    out = await run_data_ingestion({
        "file_path": "ana.xml", "file_type": "xml",
        "ek_belgeler": [{"path": "ek1.xml", "type": "xml", "ad": "ek1.xml"},
                        {"path": "ek2.xml", "type": "xml", "ad": "ek2.xml"}],
    }, None)
    assert okunan == ["ana.xml", "ek1.xml", "ek2.xml"]
    assert out.ok and len(out.patch["transactions"]) == 6
    assert out.patch["raw_text"] == "bir\n\niki\n\nüç"
    assert "3 belge, 6 işlem" in out.detail


async def test_the_confidence_is_the_lowest_and_a_review_spreads(monkeypatch):
    _plant(monkeypatch, {
        "ana.xml": _ok(1, conf=0.95),
        "ek1.xml": _ok(1, conf=0.60, review=True),
    })
    out = await run_data_ingestion({
        "file_path": "ana.xml", "file_type": "xml",
        "ek_belgeler": [{"path": "ek1.xml", "type": "xml"}],
    }, None)
    assert out.confidence == 0.60 and out.needs_review is True


async def test_an_unreadable_document_does_not_discard_the_others(monkeypatch):
    _plant(monkeypatch, {
        "ana.xml": _ok(2),
        "bozuk.xml": SkillResult(ok=False, detail="File not found: bozuk.xml", halt=True),
    })
    out = await run_data_ingestion({
        "file_path": "ana.xml", "file_type": "xml",
        "ek_belgeler": [{"path": "bozuk.xml", "type": "xml", "ad": "bozuk.xml"}],
    }, None)
    assert out.ok and len(out.patch["transactions"]) == 2
    assert out.needs_review is True, "okunamayan belge insana sorulmalı"
    assert "bozuk.xml" in out.detail


async def test_when_no_document_yields_rows_the_run_stops(monkeypatch):
    _plant(monkeypatch, {
        "ana.xml": SkillResult(ok=False, detail="okunamadı", halt=True),
        "ek1.xml": SkillResult(ok=False, detail="okunamadı", halt=True),
    })
    out = await run_data_ingestion({
        "file_path": "ana.xml", "file_type": "xml",
        "ek_belgeler": [{"path": "ek1.xml", "type": "xml"}],
    }, None)
    assert out.ok is False and out.confidence == 0.0
    assert "hiçbirinden işlem çıkarılamadı" in out.detail
