"""#116 review follow-ups on the text-statement line accounting.

(a) a bare keyword reference with 8+ digits and no date ("Ref 12500000") is no longer absorbed as a continuation:
    a word alone does not explain a round-looking number. An amount glued to an IBAN with no space is held.
(b) a statement with a held row is never said to be "verified against the balance chain" as a whole.
(c) noise: lines that are positively not money (a labelled reference, a zero-padded branch code, a trade-registry
    number beside a copyright year, an issue-date label) are counted as non-rows, by strict token rules.
"""
from __future__ import annotations

import pytest

from app.parsers.banks.garanti import GarantiParser
from app.parsers.lines import is_candidate, money_tokens
from tests.realistic_garanti import two_page_statement
from tests.test_text_lines_invariant import _pipeline

BASE = (
    "GARANTİ BBVA Hesap Ekstresi\n"
    "Tarih Valör Açıklama Tutar Bakiye\n"
    "01.01.2026 01.01.2026 Maaş +2.000,00 12.000,00\n"
    "02.01.2026 02.01.2026 Kira -1.000,00 11.000,00\n"
)


def _held(text: str) -> list[dict]:
    rows, _ = _pipeline(GarantiParser, text)
    return [r for r in rows if r.get("line_unreadable") or r.get("amount_uncertain")]


# ── (a) ──────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("word", ["Ref", "Referans", "Belge", "Dekont", "ref", "REF"])
@pytest.mark.parametrize("digits", ["12500000", "123456789", "99999999", "10000000"])
def test_a_bare_keyword_and_a_long_number_with_no_date_is_held_with_its_value(word, digits) -> None:
    held = _held(BASE + f"{word} {digits}\n")
    assert len(held) == 1 and digits in held[0]["description"]
    assert held[0]["amount_cents"] == int(digits) * 100          # a bare integer is whole lira: shown beside the raw line


@pytest.mark.parametrize("line", [
    "Ref: 12500000", "Referans No 12345678", "Fatura no 12345678", "Ref AB12345678", "Dekont: 123456789",
    "FTR 2025000123", "FTR2025000123", "Fiş No: 12345678", "Fis No 12345678", "Dekont No 12345678", "Belge No 12345678",
    "İrsaliye No 12345678", "FTR 2025000124 Ref: 98765432 nolu fatura",
])
def test_a_labelled_reference_is_still_explained(line) -> None:
    assert money_tokens(line) == [] and not is_candidate(line)
    assert _held(BASE + line + "\n") == []


def test_a_keyword_that_is_not_a_reference_label_explains_nothing() -> None:
    for line in ("Hesap özeti ücreti 1.250,00", "Belge 2500", "Ref 5000", "Müşteri 1500 tahsilat", "Sube 5000", "Referans 12500000 EFT"):
        assert len(_held(BASE + line + "\n")) == 1, line


@pytest.mark.parametrize("glued", [
    "TR3300061005197864578413261.250,00", "TR330006100519786457841326 1.250,00", "tr330006100519786457841326250,00",
])
def test_an_amount_glued_to_an_iban_holds_the_line(glued) -> None:
    held = _held(BASE + f"{glued}\n")
    assert len(held) == 1 and held[0]["description"].startswith(glued[:10])


def test_an_amount_glued_to_an_iban_in_a_dated_row_with_a_balance_is_held_not_booked_as_the_balance() -> None:
    rows, _ = _pipeline(GarantiParser, BASE + "05.01.2026 Havale TR3300061005197864578413261.250,00 9.000,00\n")
    last = rows[-1]
    assert last.get("amount_uncertain") is True        # it is booked nowhere: the hold step waits for a person


def test_a_valid_iban_beside_a_real_amount_is_still_a_normal_row() -> None:
    rows, _ = _pipeline(GarantiParser, BASE + "05.01.2026 Havale TR33 0006 1005 1978 6457 8413 26 -500,00 10.500,00\n")
    assert not rows[-1].get("amount_uncertain") and not rows[-1].get("line_unreadable") and rows[-1]["amount_cents"] == 50000


# ── (b) ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_statement_with_a_held_row_is_not_said_to_be_verified_as_a_whole() -> None:
    from app.services.ingest.summary import ingest_summary

    counts = {"read": 6, "balance_check": "verified"}
    accepted = [{}] * 5
    clean = ingest_summary(accepted, {"new": 0}, counts)
    assert clean["balance_check"] == "verified" and "bakiye zinciriyle doğrulandı" in clean["summary"]

    held = ingest_summary(accepted, {"new": 1}, counts)
    assert held["balance_check"] == "verified_partial"
    assert "bakiye zinciriyle doğrulanan 5 satır; 1 satır kararınızı bekliyor" in held["summary"]
    assert "bakiye zinciriyle doğrulandı" not in held["summary"]
    waiting = ingest_summary(accepted, {"new": 0, "already_waiting": 2}, counts)
    assert waiting["balance_check"] == "verified_partial"
    unverified = ingest_summary(accepted, {"new": 1}, {"read": 6, "balance_check": "unverified"})
    assert unverified["balance_check"] == "unverified" and "bakiye ile doğrulanamadı" in unverified["summary"]


# ── (c) noise ────────────────────────────────────────────────────────────────────────────────────────────────

def _reviewers_text() -> str:
    """The two-page text with the lines the review found noisy: a wrapped reference with a branch code, a trade
    registry number beside the copyright year, an issue-date line."""
    out = []
    for line in two_page_statement(20).split("\n"):
        out.append(line)
        if line.startswith(("03.01", "09.01", "15.01")):
            out.append("Ref: 123456789 Sube 0123")
    return "\n".join(out).replace("© 2026 Garanti BBVA", "Ticaret Sicil No: 123456 © 2026 Garanti BBVA")


def test_the_reviewers_realistic_text_holds_no_noise_and_loses_no_row() -> None:
    rows, ledger = _pipeline(GarantiParser, _reviewers_text())
    noise = [r["description"] for r in rows if r.get("line_unreadable")]
    assert len(rows) - len(noise) == 20 and noise == []          # was 6 held lines before this change
    assert ledger.non_row_lines >= 9 and ledger.continuation == 3


def test_the_noise_rules_do_not_hide_a_transaction() -> None:
    text = _reviewers_text().split("\n")
    text[8:8] = ["Hesap özeti ücreti 1.250,00", "Belge 2500", "Sube 5000", "Ref 12500000", "Düzenleme tarihi 01.02.2026 150,00",
                 "Sicil No: 123456 1.000,00"]
    rows, _ = _pipeline(GarantiParser, "\n".join(text))
    held = [r["description"] for r in rows if r.get("line_unreadable")]
    assert len(held) == 6, held


@pytest.mark.parametrize("line", ["Sube 0123", "Şube Kodu: 0456", "Ref: 123456789 Sube 0123", "Düzenleme tarihi 01.02.2026"])
def test_a_positively_identified_non_money_token_is_not_a_candidate(line) -> None:
    assert money_tokens(line) == [] or line.startswith("Düzenleme")
    assert _held(BASE + line + "\n") == []


@pytest.mark.parametrize("line", ["Sube 5000", "Şube 1250,00", "Sube 500 TL", "Düzenleme ücreti 01.02.2026 100,00"])
def test_a_branch_word_with_a_money_shaped_number_is_still_held(line) -> None:
    assert len(_held(BASE + line + "\n")) == 1


# ── noise on the review's invoice-number text (round 2) ──────────────────────────────────────────────────────

def test_the_invoice_number_text_holds_no_noise_and_loses_no_row() -> None:
    """Five `FTR 2025000123 nolu fatura tahsilati` wrapped lines, an `FTR … Ref: …` line, and footers with a year, a
    copyright line and an issue date with a time, on two pages. Held non-transaction lines: 10 before, 0 now (target
    <= 1 per page)."""
    from tests.realistic_garanti_invoices import two_page_with_invoices

    text, expected = two_page_with_invoices()
    rows, ledger = _pipeline(GarantiParser, text)
    noise = [r["description"] for r in rows if r.get("line_unreadable")]
    assert len(rows) - len(noise) == expected and noise == []
    assert ledger.continuation >= 5


def test_the_invoice_number_text_still_holds_every_money_line_injected_into_it() -> None:
    from tests.realistic_garanti_invoices import two_page_with_invoices

    lines = two_page_with_invoices()[0].split("\n")
    lines[10:10] = ["FTR 2025000999 tahsilat 1.250,00", "Hesap özeti ücreti 1.250,00", "Ref 12500000", "FTR 5000",
                    "© 2026 5000", "Düzenleme tarihi: 01.02.2026 14:32 250,00"]
    rows, _ = _pipeline(GarantiParser, "\n".join(lines))
    held = [r["description"] for r in rows if r.get("line_unreadable")]
    assert len(held) == 5, held                               # the sixth (a dated line with an amount) is read as a ROW
    assert len(rows) == 26                                    # 20 real + 6 injected: none lost


@pytest.mark.parametrize("line", ["Düzenleme tarihi: 01.02.2026 14:32", "Basım tarihi 01.02.2026", "Son işlem tarihi: 31.01.2026 23:59:10"])
def test_an_issue_date_label_with_its_date_and_time_is_a_footer(line) -> None:
    assert _held(BASE + line + "\n") == []


def test_a_footer_year_is_exempt_only_beside_a_page_marker_or_a_rights_line() -> None:
    assert _held(BASE + "Sayfa 1 / 2\n2026\n") == []
    assert _held(BASE + "2026 Garanti BBVA. Tüm hakları saklıdır\n") == []
    assert len(_held(BASE + "2026\n")) == 1                    # a lone year with nothing around it may be an amount
    assert len(_held(BASE + "Kira 2026\n")) == 1


# ── round 3: every exemption acts on its own TOKEN; any money token left on the line holds the line ───────────

def _rows_for(line: str):
    rows, ledger = _pipeline(GarantiParser, BASE + line + "\n")
    return rows, ledger


def _unread(line: str) -> int:
    """Lines no row pattern took that the line accounting HELD (no parser rows: nothing can explain the line away)."""
    from app.parsers.lines import account_for_lines

    return account_for_lines(BASE + line + "\n", []).unread - account_for_lines(BASE, []).unread


PAIRED = [
    # (exempt token alone, the same line + a money token, cents of that money)
    ("Düzenleme tarihi 01.02.2026 14:30", "Düzenleme tarihi 01.02.2026 14:30 komisyon 1.250,00", 125000),
    ("Düzenleme tarihi: 01.02.2026 14:32", "Bu belge 01.02.2026 14:30 tarihinde düzenlenmiştir 1.250,00 TL", 125000),
    ("Basım tarihi 01.02.2026", "Basım tarihi 01.02.2026 komisyon 1.250,00", 125000),
    ("FTR 2025000123", "FTR 2025000123 1.250,00", 125000),
    ("FTR 2025000123 nolu fatura tahsilati", "FTR 2025000123 nolu fatura tahsilati 5000", 500000),
    ("Fatura No 2025000123", "Fatura No 2025000123 komisyon 250,50", 25050),
    ("Fiş No: 12345678", "Fiş No: 12345678 masraf 1.250,00", 125000),
    ("İrsaliye No 12345678", "İrsaliye No 12345678 1.250,00 TL", 125000),
    ("Dekont No 12345678", "Dekont No 12345678 ücret 99,90", 9990),
    ("Belge No 12345678", "Belge No 12345678 5000", 500000),
    ("© 2026 Garanti BBVA", "© 2026 komisyon 1.250,00", 125000),
    ("2026 Garanti BBVA. Tüm hakları saklıdır", "2026 Garanti BBVA. Tüm hakları saklıdır 1.250,00", 125000),
    ("Sube 0123", "Sube 0123 1.250,00", 125000),
    ("Ticaret Sicil No: 123456 © 2026 Garanti BBVA", "Ticaret Sicil No: 123456 1.250,00", 125000),
]


@pytest.mark.parametrize(("alone", "with_money", "cents"), PAIRED)
def test_an_exempt_token_alone_is_not_held_and_the_same_line_with_money_is_never_lost(alone, with_money, cents) -> None:
    assert _held(BASE + alone + "\n") == [] and _unread(alone) == 0
    rows, _ = _rows_for(with_money)
    kept = [r for r in rows if r["amount_cents"] == cents]
    # the amount is either a row of its own (booked, or held at the hold step) or a held unread line: never a non-row
    assert kept, (with_money, [(r["description"][:30], r["amount_cents"]) for r in rows])
    assert _unread(with_money) == 1                       # with no parser row to explain it, the accounting holds the line


def test_the_footer_year_beside_a_page_marker_is_a_token_exemption_too() -> None:
    assert _held(BASE + "Sayfa 1 / 2\n2026\n") == []
    for money in ("Sayfa 1 / 2\n2026 komisyon 1.250,00\n", "Sayfa 1 / 2\n2026 1.250,00\n"):
        rows, _ = _pipeline(GarantiParser, BASE + money)
        assert any(r["amount_cents"] == 125000 for r in rows), money


@pytest.mark.parametrize("line", [
    "Düzenleme tarihi 01.02.2026 14:30 komisyon 1.250,00",
    "Bu belge 01.02.2026 14:30 tarihinde düzenlenmiştir 1.250,00 TL",
])
def test_the_reviewers_issue_date_lines_with_an_amount_are_never_counted_as_non_rows(line) -> None:
    from tests.realistic_garanti_invoices import two_page_with_invoices

    base_text = two_page_with_invoices()[0]
    _, base_ledger = _pipeline(GarantiParser, base_text)
    for text in (base_text + line + "\n", base_text.replace("Sayfa 2 / 2", line + "\nSayfa 2 / 2")):
        rows, ledger = _pipeline(GarantiParser, text)
        assert any(r["amount_cents"] == 125000 for r in rows)
        assert ledger.non_row_lines == base_ledger.non_row_lines          # not one more line was written off
