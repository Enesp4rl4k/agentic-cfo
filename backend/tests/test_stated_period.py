"""The period a file states in its header is evidence for the days it covers; nothing else is read as one."""
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
TABLE = "Tarih;Açıklama;Tutar;Bakiye\n02.01.2026;Kira;-100,00;900,00\n"


class TestReadingTheHeader:
    @pytest.mark.parametrize("header", [
        "Dönem: 01.01.2026 - 31.03.2026",
        "DÖNEM : 01/01/2026 – 31/03/2026",
        "Tarih Aralığı;01.01.2026;31.03.2026",
        "Tarih Aralığı: 2026-01-01 - 2026-03-31",
    ])
    def test_labelled_periods(self, header: str) -> None:
        assert stated_period(f"Örnek Bank\n{header}\n\n{TABLE}") == Q1

    def test_start_and_end_date_fields(self) -> None:
        text = f"Başlangıç Tarihi;01.01.2026\nBitiş Tarihi;31.03.2026\n{TABLE}"
        assert stated_period(text) == Q1

    def test_the_logo_export_header(self) -> None:
        demo = Path(__file__).resolve().parents[2] / "demo" / "data" / "logo_tiger_2024.csv"
        assert stated_period(demo.read_text(encoding="utf-8")) == {"start": "2024-01-01", "end": "2024-12-31"}

    def test_a_pdf_style_header_line_with_spaced_columns(self) -> None:
        assert stated_period("Dönem: 01.01.2026 - 31.03.2026\nTarih   Açıklama   Tutar   Bakiye\n") == Q1

    def test_nothing_stated_is_none(self) -> None:
        assert stated_period(TABLE) is None

    def test_a_bare_pair_of_dates_or_a_print_date_is_not_a_period(self) -> None:
        assert stated_period(f"Örnek Bank\n01.01.2026 - 31.03.2026\n\n{TABLE}") is None
        assert stated_period(f"Rapor Tarihi: 31.03.2026\n{TABLE}") is None

    def test_period_looking_text_in_a_row_description_is_ignored(self) -> None:
        # The first lines ARE the table: everything after the column-header line is a row.
        text = "Tarih;Açıklama;Tutar;Bakiye\n02.01.2026;Dönem 01.01.2026 - 31.01.2026 aidat;-100,00;900,00\n"
        assert stated_period(text) is None
        # ... and a row below a real header never adds or changes a period.
        text = f"Dönem: 01.01.2026 - 31.03.2026\n{TABLE}05.01.2026;Dönem 01.04.2026 - 30.04.2026 aidat;-1,00;899,00\n"
        assert stated_period(text) == Q1

    def test_a_file_with_no_table_header_has_no_stated_period(self) -> None:
        assert stated_period("Dönem: 01.01.2026 - 31.03.2026\nbir iki üç\n02.01.2026 Kira -100\n") is None

    def test_two_different_periods_prove_neither(self) -> None:
        text = f"Dönem: 01.01.2026 - 31.03.2026\nTarih Aralığı: 01.04.2026 - 30.06.2026\n{TABLE}"
        assert stated_period(text) is None

    def test_a_backwards_or_enormous_period_is_ignored(self) -> None:
        assert stated_period(f"Dönem: 31.03.2026 - 01.01.2026\n{TABLE}") is None
        assert stated_period(f"Dönem: 01.01.2000 - 31.03.2026\n{TABLE}") is None

    def test_a_transaction_outside_the_period_means_the_header_is_about_something_else(self) -> None:
        text = f"Dönem: 01.01.2026 - 31.03.2026\n{TABLE}"
        assert stated_period(text, ["2026-02-01", "2026-04-02"]) is None
        assert stated_period(text, ["2026-01-02", "2026-03-30"]) == Q1


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

    async def test_the_same_statement_with_its_period_stated_has_no_assumption(self, monkeypatch) -> None:
        # The corpus statement ends in March 2026; the age rule (`aged_basis`) is about the clock, not the period.
        monkeypatch.setattr("app.services.bank_balance.BURN_WINDOW_DAYS", 10_000)
        result = await run_cfo_pipeline(
            job_id="sample-stated", file_path=str(CORPUS / "banka_ekstresi_donemli_2026.csv"),
            file_type="csv", run_config=CFG,
        )
        runway = result["forecast"]["runway"]
        assert result["statement_period"] == Q1 and result["awaiting_review"] is False
        assert runway["status"] == "computed" and runway["basis"] == "known" and "varsayım" not in runway["message"]
        assert runway["months_used"] == 3

    async def test_a_header_the_rows_do_not_reach_is_not_trusted(self, tmp_path: Path) -> None:
        # The header says through 31 March; the rows stop on 10 March (a truncated export).
        text = (CORPUS / "banka_ekstresi_donemli_2026.csv").read_text(encoding="utf-8")
        cut = "".join(line for line in text.splitlines(keepends=True) if not line.startswith(("30.03.2026",)))
        cut += "10.03.2026;Personel maaş ödemesi;" + chr(34) + "-60.000,00" + chr(34) + ";" + chr(34) + "90.000,00" + chr(34) + ";TRY" + chr(10)
        path = tmp_path / "kesik.csv"
        path.write_text(cut, encoding="utf-8")
        result = await run_cfo_pipeline(job_id="truncated", file_path=str(path), file_type="csv", run_config=CFG)
        runway = result["forecast"]["runway"]
        assert result["statement_period"] == Q1
        assert runway["status"] == "insufficient_history"  # Jan and Feb only: March is not whole
        assert "Mart yalnızca 1–10 arası var; hesaba katılmadı" in runway["message"]
        assert "Ekstre başlığındaki bitiş tarihi 31 Mart 2026, satırların son tarihi 10 Mart 2026: başlığa güvenilmedi" in runway["message"]
