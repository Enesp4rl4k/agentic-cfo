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


# ── round 4: the table reader no longer decides what a transaction is ────────────────────────────────────────

def _sheet(tmp_path, name: str, *rows):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(list(r))
    path = tmp_path / name
    wb.save(path)
    return str(path)


def test_a_toplam_payment_with_a_date_and_an_amount_survives_the_xlsx_reader(tmp_path):
    from datetime import datetime

    from app.services.ingest.okuma import ReadLedger
    from app.services.ingest.rows import _tablo_ekstresi

    ledger = ReadLedger()
    rows = _tablo_ekstresi(_sheet(
        tmp_path, "e.xlsx",
        ["Tarih", "Açıklama", "Tutar"],
        [datetime(2026, 1, 5), "Toplam fatura ödemesi", -1500.0],
        [datetime(2026, 1, 6), "Satış", 4000.0],
        [datetime(2026, 1, 7), "Kira", -700.0],
    ), ledger=ledger) or []
    assert [r["description"] for r in rows] == ["Toplam fatura ödemesi", "Satış", "Kira"]
    assert ledger.read == 3 and ledger.summary_skipped == 0 and ledger.emitted == 3


def test_the_same_row_survives_the_csv_reader_and_the_description_first_layout(tmp_path):
    from app.services.ingest.okuma import ReadLedger
    from app.services.ingest.rows import _tablo_ekstresi

    path = tmp_path / "e.csv"
    path.write_text("Açıklama;Tarih;Tutar\nToplam fatura ödemesi;05.01.2026;-1.500,00\nSatış;06.01.2026;4.000,00\n", encoding="utf-8")
    ledger = ReadLedger()
    rows = _tablo_ekstresi(str(path), ledger=ledger) or []
    assert [r["description"] for r in rows] == ["Toplam fatura ödemesi", "Satış"] and ledger.summary_skipped == 0


def test_exact_summary_rows_and_a_totals_line_are_skipped_counted_and_listed(tmp_path):
    from app.services.ingest.okuma import ReadLedger
    from app.services.ingest.rows import _tablo_ekstresi

    ledger = ReadLedger()
    rows = _tablo_ekstresi(_sheet(
        tmp_path, "e.xlsx",
        ["Tarih", "Açıklama", "Borç", "Alacak", "Bakiye"],
        [None, "Devreden Bakiye", None, None, 1000.0],
        ["05.01.2026", "Kira", 100.0, None, 900.0],
        ["06.01.2026", "Satış", None, 400.0, 1300.0],
        [None, "Toplam", 100.0, 400.0, None],
        ["TOPLAM", None, 100.0, 400.0, None],
    ), ledger=ledger) or []
    assert len(rows) == 2 and ledger.summary_skipped == 3 and ledger.read == 5
    assert [x["description"] for x in ledger.summary_lines] == ["Devreden Bakiye", "Toplam", "TOPLAM"]


def test_a_file_of_only_summary_lines_says_so_instead_of_falling_through(tmp_path):
    from app.services.ingest.okuma import ReadLedger
    from app.services.ingest.rows import _tablo_ekstresi

    ledger = ReadLedger()
    rows = _tablo_ekstresi(_sheet(
        tmp_path, "e.xlsx", ["Tarih", "Açıklama", "Tutar", "Bakiye"],
        [None, "Devreden Bakiye", None, 1000.0], [None, "Genel Toplam", None, 1000.0],
    ), ledger=ledger)
    assert rows == [] and ledger.summary_skipped == 2           # not None: nothing else may re-read it as something else


def test_a_zero_amount_row_is_held_not_booked_at_zero():
    from app.services.ingest.hold import row_reasons
    from app.services.ingest.rows import _try_parse_csv

    rows = _try_parse_csv("Tarih;Açıklama;Tutar\n01.03.2026;Kira;-400,00\n02.03.2026;Sıfır;0,00\n03.03.2026;Satış;900,00\n04.03.2026;Gaz;-50,00\n") or []
    zero = next(r for r in rows if r["description"] == "Sıfır")
    assert zero["zero_amount"] is True and "amount_zero" in row_reasons({**zero, "currency": "TRY"})


def test_a_reader_that_crashes_is_logged_and_reported_not_swallowed(monkeypatch, caplog):
    import logging

    from app.services.ingest import rows as rows_mod
    from app.services.ingest.okuma import ReadLedger
    from app.services.ingest.summary import ingest_summary

    def boom(*_a, **_k):
        raise RuntimeError("secret cell contents 12345")

    monkeypatch.setattr(rows_mod, "resolve_file", boom)
    ledger = ReadLedger()
    with caplog.at_level(logging.ERROR):
        assert rows_mod._try_parse_csv("Tarih;Açıklama;Tutar\n01.03.2026;Kira;-400,00\n", ledger=ledger) is None
    assert ledger.reader_failed
    assert any("statement reader failed" in r.message and "RuntimeError" in r.message for r in caplog.records)
    assert not any("secret" in r.getMessage() for r in caplog.records)         # the layout signature, never cell contents
    assert "alternatif okuyucu kullanıldı" in ingest_summary([], {}, ledger.as_dict())["summary"]


def test_the_summary_says_where_every_row_went():
    from app.services.ingest.summary import ingest_summary

    out = ingest_summary([{}] * 3, {"new": 1}, {"read": 8, "summary_skipped": 2, "account_skipped": 1, "unaccounted": 1,
                                                 "summary_lines": [{"description": "Toplam", "date": ""}]})
    assert "8 satır okundu: 3 kaydedildi, 1 kararınızı bekliyor, 2 özet satırı atlandı, 1 geçiş/kapanış kaydı atlandı" in out["summary"]
    assert "1 satır hesaba katılamadı" in out["summary"] and out["skipped_lines"][0]["description"] == "Toplam"
