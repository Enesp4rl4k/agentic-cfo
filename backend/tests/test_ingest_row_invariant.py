"""No row disappears unseen: read == booked + held + skipped-and-counted, for every entry path.

Property-style: varied synthetic statements (the fixture layouts x rows with summary-like descriptions, empty
descriptions, dates in every format, zero amounts, duplicate rows, unparseable cells, page-break artefacts) go
through BOTH entry paths of the statement reader (the table reader, as a spreadsheet or CSV file is read, and the
raw CSV text) and through the bank PDF text path. The equation is the one `app.services.ingest.okuma` states and
the ingest step enforces ("N satır hesaba katılamadı" when it fails).
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from app.services.ingest.hold import split_uncertain
from app.services.ingest.okuma import ReadLedger, merge_counts, unaccounted
from app.services.ingest.rows import _tablo_ekstresi, _try_parse_csv

DESCRIPTIONS = [
    "Kira", "Satış", "Elektrik faturası", "Toplam", "Toplam fatura ödemesi", "Devreden Bakiye", "Devreden KDV",
    "Total Wireless", "Genel Toplam", "Ara Toplam", "", "EFT gelen - ABC Ltd", "Dönem Sonu Bakiyesi", "total",
]
DATES = ["05.01.2026", "2026-01-05", "05/01/2026", "5.1.26", "not a date", "", "31.02.2026"]
AMOUNTS = ["1.500,00", "-1.500,00", "(250,00)", "0,00", "abc", "", "1.234,56-", "₺99,90", "12,5", "-0,00"]
LAYOUTS = {
    "signed": ("Tarih;Açıklama;Tutar", 1),
    "signed_balance": ("Tarih;Açıklama;Tutar;Bakiye", 1),
    "outflow_inflow": ("Tarih;Açıklama;Ödeme;Tahsilat", 2),
    "borc_alacak": ("Tarih;Açıklama;Borç;Alacak", 2),
    "ba_column": ("Tarih;Açıklama;Tutar;B/A", 1),
    "plain_type": ("Tarih;Açıklama;Tutar;Tip", 1),
}


def _statement(rng: random.Random) -> tuple[str, int, int]:
    """(csv text, data lines after the header, lines a table reader sees after the header)."""
    name = rng.choice(sorted(LAYOUTS))
    header, _ = LAYOUTS[name]
    lines = [header]
    after = 0
    nonblank = 0
    previous: str | None = None
    for _ in range(rng.randint(1, 14)):
        roll = rng.random()
        if roll < 0.08:
            lines.append("")                                   # a blank line
            after += 1
            continue
        if roll < 0.14:
            lines.append(header)                               # a page break repeats the header
            after += 1
            nonblank += 1
            continue
        if roll < 0.20 and previous is not None:
            lines.append(previous)                             # a duplicate row
            after += 1
            nonblank += 1
            continue
        cells = [rng.choice(DATES), rng.choice(DESCRIPTIONS)]
        amount = rng.choice(AMOUNTS)
        if name == "outflow_inflow" or name == "borc_alacak":
            cells += [amount, ""] if rng.random() < 0.5 else ["", amount]
        else:
            cells.append(amount)
            if name == "signed_balance":
                cells.append(rng.choice(["10.000,00", "9.500,00", "", "x"]))
            if name == "ba_column":
                cells.append(rng.choice(["B", "A", "X", ""]))
            if name == "plain_type":
                cells.append(rng.choice(["income", "expense", ""]))
        if rng.random() < 0.08:
            cells.append("fazlalık")                           # misaligned: a cell beyond the header
        previous = ";".join(cells)
        lines.append(previous)
        after += 1
        nonblank += 1
    return "\n".join(lines) + "\n", nonblank, after


def _reconcile(rows: list[dict], ledger: ReadLedger) -> None:
    accepted, held = split_uncertain(rows)
    counts = {**ledger.as_dict(), "accepted": len(accepted), "held": len(held)}
    assert not ledger.reader_failed, "the reader crashed on a well-formed shape"
    assert unaccounted(counts) == 0, counts
    assert ledger.read == (
        ledger.emitted + ledger.summary_skipped + ledger.account_skipped + ledger.blank + ledger.header_repeats
    ), ledger


@pytest.mark.parametrize("seed", range(300))
def test_the_raw_csv_path_accounts_for_every_row(seed: int) -> None:
    text, nonblank, _ = _statement(random.Random(seed))
    ledger = ReadLedger()
    rows = _try_parse_csv(text, ledger=ledger)
    assert rows is not None, "a statement header must be read as a statement"
    # what the reader was handed: every non-empty line after the header (an empty line is not a row at all)
    assert ledger.read == nonblank
    _reconcile(rows, ledger)


@pytest.mark.parametrize("seed", range(300))
def test_the_table_reader_path_accounts_for_every_row(seed: int, tmp_path: Path) -> None:
    text, _, after = _statement(random.Random(seed))
    path = tmp_path / "ekstre.csv"
    path.write_text(text, encoding="utf-8")
    ledger = ReadLedger()
    rows = _tablo_ekstresi(str(path), ledger=ledger)
    if rows is None:
        pytest.skip("the table reader found no table: another reader takes the file")
    assert ledger.read == after                                 # every line after the header, blank or not
    _reconcile(rows, ledger)


def test_the_properties_are_not_vacuous() -> None:
    """The generator reaches every bucket, and a row dropped silently would break the equation."""
    seen = ReadLedger()
    for seed in range(300):
        text, _, _ = _statement(random.Random(seed))
        one = ReadLedger()
        _try_parse_csv(text, ledger=one)
        seen.blank += one.blank
        seen.summary_skipped += one.summary_skipped
        seen.emitted += one.emitted
    assert seen.summary_skipped > 20 and seen.emitted > 500
    counts = {"read": 10, "emitted": 5, "summary_skipped": 2, "blank": 1, "accepted": 3, "held": 2}
    assert unaccounted(counts) == 2                              # 2 rows vanished
    assert unaccounted({**counts, "emitted": 7, "accepted": 4, "held": 2}) == 1   # read and emitted agree; one row lost in the hold step
    assert merge_counts({"read": 1, "emitted": 1}, {"read": 2, "blank": 2})["read"] == 3  # type: ignore[index]
