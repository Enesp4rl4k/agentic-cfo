"""The period a file states in its header is proof of the days it covers; nothing else is read as one."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("USE_SQLITE", "true")

from app.agents.orchestrator import run_cfo_pipeline
from app.agents.state import AgentRunConfig
from app.services.stated_period import stated_period

CORPUS = Path(__file__).resolve().parent / "fixtures" / "tr_corpus"
CFG = AgentRunConfig(require_review=True, auto_proceed_min_confidence=0.80)
Q1 = {"start": "2026-01-01", "end": "2026-03-31"}


class TestReadingTheHeader:
    @pytest.mark.parametrize("header", [
        "Dönem: 01.01.2026 - 31.03.2026",
        "DÖNEM : 01/01/2026 – 31/03/2026",
        "Tarih Aralığı;01.01.2026;31.03.2026",
        "Tarih Aralığı: 2026-01-01 - 2026-03-31",
        "Hesap özeti 01.01.2026 ile 31.03.2026",
    ][:4])
    def test_labelled_periods(self, header: str) -> None:
        assert stated_period(f"Örnek Bank\n{header}\nTarih;Tutar\n") == Q1

    def test_a_bare_line_of_two_dates(self) -> None:
        assert stated_period("Örnek Bank\n01.01.2026 - 31.03.2026\n\nTarih;Tutar\n") == Q1

    def test_start_and_end_date_fields(self) -> None:
        text = "Başlangıç Tarihi;01.01.2026\nBitiş Tarihi;31.03.2026\nTarih;Tutar\n"
        assert stated_period(text) == Q1

    def test_the_logo_export_header(self) -> None:
        demo = Path(__file__).resolve().parents[2] / "demo" / "data" / "logo_tiger_2024.csv"
        assert stated_period(demo.read_text(encoding="utf-8")) == {"start": "2024-01-01", "end": "2024-12-31"}

    def test_nothing_stated_is_none(self) -> None:
        assert stated_period("Tarih;Açıklama;Tutar\n02.01.2026;Kira;-100\n") is None

    def test_a_transaction_row_is_never_a_period(self) -> None:
        body = "x" * 5000 + chr(10) + "Dönem: 01.01.2026 - 31.03.2026"  # past the header region
        assert stated_period(body) is None

    def test_two_different_periods_prove_neither(self) -> None:
        assert stated_period("Dönem: 01.01.2026 - 31.03.2026\nTarih Aralığı: 01.04.2026 - 30.06.2026\n") is None

    def test_a_backwards_or_enormous_period_is_ignored(self) -> None:
        assert stated_period("Dönem: 31.03.2026 - 01.01.2026\n") is None
        assert stated_period("Dönem: 01.01.2000 - 31.03.2026\n") is None

    def test_a_transaction_outside_the_period_means_the_header_is_about_something_else(self) -> None:
        assert stated_period("Dönem: 01.01.2026 - 31.03.2026\n", ["2026-02-01", "2026-04-02"]) is None
        assert stated_period("Dönem: 01.01.2026 - 31.03.2026\n", ["2026-01-02", "2026-03-30"]) == Q1


class TestThroughThePipeline:
    async def test_a_three_month_statement_without_a_header_has_a_runway_on_the_stated_assumption(self) -> None:
        result = await run_cfo_pipeline(
            job_id="sample-plain", file_path=str(CORPUS / "banka_ekstresi_ocak_mart_2026.csv"),
            file_type="csv", run_config=CFG,
        )
        runway = result["forecast"]["runway"]
        assert result["awaiting_review"] is False and result.get("statement_period") is None
        assert runway["status"] == "computed" and runway["basis"] == "assumed"
        assert runway["opening_cash_cents"] == 9_000_000 and runway["level"] == "critical"
        assert "ay tam sayıldı (varsayım)" in runway["message"]
        critical = [a for a in result["forecast"]["alerts"] if a["level"] == "critical"]
        assert len(critical) == 1 and "varsayım" in critical[0]["message"] and "₺90.000,00" in critical[0]["message"]

    async def test_the_same_statement_with_its_period_stated_has_no_assumption(self) -> None:
        result = await run_cfo_pipeline(
            job_id="sample-stated", file_path=str(CORPUS / "banka_ekstresi_donemli_2026.csv"),
            file_type="csv", run_config=CFG,
        )
        runway = result["forecast"]["runway"]
        assert result["statement_period"] == Q1 and result["awaiting_review"] is False
        assert runway["status"] == "computed" and runway["basis"] == "known" and "varsayım" not in runway["message"]
        assert runway["months_used"] == 3
