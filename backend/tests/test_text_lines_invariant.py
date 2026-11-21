"""A line that looks like money is never dropped because a row pattern rejected it.

The invariant used to be a tautology on the text path: `read` was the number of lines the row regex matched, so a
payment the regex did not recognise (no running balance, a negative running balance, a currency suffix, an extra
column, a wrapped line) was never read at all and 0 rows were "unaccounted". `app.parsers.lines` now takes `read`
from the physical lines of the text, before any row pattern is asked, and every candidate line the parser did not
take is HELD with its raw text. These tests inject K such lines into each bank's text fixture and each ERP export
and assert that exactly K more rows exist, and that no amount disappears.
"""
from __future__ import annotations

import inspect
import random

import pytest

from app.parsers import lines as lines_module
from app.parsers.accounting.logo_tiger import LogoTigerParser
from app.parsers.accounting.mikro import MikroParser
from app.parsers.accounting.netsis import NetsisParser
from app.parsers.accounting.parasut import ParasutParser
from app.parsers.banks.akbank import AkbankParser
from app.parsers.banks.garanti import GarantiParser
from app.parsers.banks.isbank import IsBankParser
from app.parsers.banks.yapkredi import YapiKrediParser
from app.parsers.banks.ziraat import ZiraatParser
from app.parsers.lines import account_for_lines, read_lines
from app.services.ingest.hold import row_reasons, split_uncertain
from app.services.ingest.okuma import ReadLedger, unaccounted
from app.services.ingest.rows import _statement_to_transactions
from tests.test_parsers.test_accounting_parsers import LOGO_TIGER_CSV, PARASUT_TRANSACTION_CSV
from tests.test_parsers.test_bank_parsers import AKBANK_TEXT, GARANTI_TEXT, ISBANK_TEXT, ZIRAAT_TEXT

YAPIKREDI_TEXT = "YAPI KREDİ BANKASI\nHesap No: 1234567\n01.03.2026  Kira  -1.000,00  9.000,00\n02.03.2026  Satış  500,00  9.500,00\n"
MIKRO_CSV = "MİKRO YAZILIM\nTarih;Açıklama;Giriş;Çıkış\n05.01.2024;Satış;1.000,00;\n06.01.2024;Kira;;500,00\n07.01.2024;Satış 2;300,00;\n"
NETSIS_CSV = "NETSİS\nTarih;Evrak No;Açıklama;Borç;Alacak\n05.01.2024;E1;Kira;500,00;\n06.01.2024;E2;Satış;;900,00\n07.01.2024;E3;Gaz;120,00;\n"

BANKS = {
    "garanti": (GarantiParser, GARANTI_TEXT), "akbank": (AkbankParser, AKBANK_TEXT), "isbank": (IsBankParser, ISBANK_TEXT),
    "ziraat": (ZiraatParser, ZIRAAT_TEXT), "yapikredi": (YapiKrediParser, YAPIKREDI_TEXT),
}
ERPS = {
    "logo": (LogoTigerParser, LOGO_TIGER_CSV), "parasut": (ParasutParser, PARASUT_TRANSACTION_CSV),
    "mikro": (MikroParser, MIKRO_CSV), "netsis": (NetsisParser, NETSIS_CSV),
}

# Shapes a row pattern does not match: (lines, the amounts they carry in kuruş, how many physical lines)
TEXT_SHAPES = [
    (["04.01.2026 Havale ₺1.250,00"], [125000]),                                      # currency prefix
    (["04.01.2026 Maaş 5.000,00 TL -3.700,00 TL ABC123 fazlalık"], [500000]),         # extra column
    (["04.01.2026 Havale EFT", "-1.000,00"], [100000]),                              # split across two lines
    (["4/1/26 Kira -2.500,00 9.900,00"], [250000]),                                   # a different date format
    (["2026-01-04 Maaş -700,00 9.000,00"], [70000]),                                  # ISO date
    (["04.01.2026 Havale 2 500,00"], [250000]),                                       # a space as thousands separator
    (["04.01.2026   -   Virman   333,33"], [33333]),                                  # dash column
]
ERP_SHAPES = [
    (["31.02.2024;Bozuk tarihli;;250,00;"], [25000]),                                 # a date that cannot be read
    (["05.01.2024;Tutarsız;;;"], [0]),                                                # no amount at all
    (["05.01.2024;Sıfır;0,00;;"], [0]),                                               # zero amount
    (["9/9/24 serbest metin 1.111,11"], [111111]),                                    # not even the export's layout
    (["07.01.2024 Kısa satır"], [0]),                                                 # a short row
]


def _pipeline(parser_cls, text: str) -> tuple[list[dict], ReadLedger]:
    parser = parser_cls()
    statement = parser.parse(text, "")
    account = account_for_lines(text, statement.transactions)
    statement.transactions = account.transactions
    ledger = ReadLedger(read=account.read, continuation=account.continuation, non_row_lines=account.non_row)
    for line in account.summary:
        ledger.skip_summary(line)
    rows = _statement_to_transactions(statement)
    ledger.emitted = len(rows)
    return rows, ledger


def _inject(text: str, shapes: list, rng: random.Random) -> tuple[str, int, int]:
    """Insert K shapes between the rows of the body; returns (text, physical lines injected, cents injected)."""
    body = text.splitlines()
    k = rng.randint(1, 4)
    added = cents = 0
    for _ in range(k):
        lines, amounts = rng.choice(shapes)
        # inside the statement body: after its first dated row (a title above the table is not the body)
        first_row = next((i for i, line in enumerate(body) if lines_module.DATE_LIKE.match(line.strip())), 0)
        at = rng.randint(first_row + 1, len(body))
        body[at:at] = lines
        added += len(lines)
        cents += sum(amounts)
    return "\n".join(body) + "\n", added, cents


def _total(rows: list[dict]) -> int:
    return sum(abs(r.get("amount_cents") or 0) for r in rows)


@pytest.mark.parametrize("seed", range(40))
@pytest.mark.parametrize("name", sorted(BANKS))
def test_injected_money_lines_in_bank_text_are_booked_or_held_never_dropped(name: str, seed: int) -> None:
    parser_cls, text = BANKS[name]
    base_rows, _ = _pipeline(parser_cls, text)
    injected, added, cents = _inject(text, TEXT_SHAPES, random.Random(seed))
    rows, ledger = _pipeline(parser_cls, injected)
    accepted, held = split_uncertain(rows)
    base_accepted, base_held = split_uncertain(base_rows)
    assert len(accepted) + len(held) == len(base_accepted) + len(base_held) + added          # exactly K more, none lost
    assert _total(rows) >= _total(base_rows) + cents                                         # no amount disappeared
    counts = {**ledger.as_dict(), "accepted": len(accepted), "held": len(held)}
    assert unaccounted(counts) == 0, counts


@pytest.mark.parametrize("seed", range(30))
@pytest.mark.parametrize("name", sorted(ERPS))
def test_injected_lines_in_erp_exports_are_held_not_dropped(name: str, seed: int) -> None:
    parser_cls, text = ERPS[name]
    base_rows, _ = _pipeline(parser_cls, text)
    assert base_rows, "the fixture must parse"
    injected, added, cents = _inject(text, ERP_SHAPES, random.Random(seed))
    rows, ledger = _pipeline(parser_cls, injected)
    assert len(rows) == len(base_rows) + added
    assert _total(rows) >= _total(base_rows) + cents
    accepted, held = split_uncertain(rows)
    assert len(accepted) + len(held) == len(rows)
    assert unaccounted({**ledger.as_dict(), "accepted": len(accepted), "held": len(held)}) == 0


def test_a_payment_the_regex_rejects_is_held_with_its_raw_text() -> None:
    """The reproduced case: Garanti text, three lines the pattern used to lose (a 5.000,00 salary among them)."""
    text = (
        "GARANTİ BBVA Hesap Ekstresi\n"
        "01.01.2026 Maaş Geliri 9.000,00 14.000,00\n"
        "02.01.2026 Kira -1.000,00 13.000,00\n"
        "03.01.2026 Maas -5.000,00 -3.700,00\n"
        "04.01.2026 Havale -100,00\n"
        "05.01.2026 Satis 700,00 TL 1.200,00 TL\n"
        "06.01.2026 Gaz ₺400,00\n"
    )
    rows, ledger = _pipeline(GarantiParser, text)
    assert ledger.read == 7 and len(rows) == 6                      # every physical line is a unit; the title is not a row
    gaz = next(r for r in rows if "Gaz" in r["description"])
    assert gaz["amount_cents"] == 40000 and "line_unreadable" in gaz and "line_unreadable" in row_reasons({**gaz, "currency": "TRY"})
    assert {r["amount_cents"] for r in rows} >= {500000, 10000, 70000, 40000}
    assert unaccounted({**ledger.as_dict(), "accepted": 0, "held": 6}) == 0 and ledger.non_row_lines == 1


def test_a_wrapped_description_is_attached_to_its_row_and_counted_once() -> None:
    text = (
        "GARANTİ BBVA Hesap Ekstresi\n"
        "01.01.2026 Maaş Geliri 9.000,00 14.000,00\n"
        "ABC Holding Ltd. Şti. ocak ayı\n"
        "Sayfa 1 / 2\n"
        "02.01.2026 Kira -1.000,00 13.000,00\n"
        "devamı ofis kirası\n"
        "yine devamı\n"
    )
    rows, ledger = _pipeline(GarantiParser, text)
    assert len(rows) == 2 and ledger.continuation == 3 and ledger.non_row_lines == 2       # title + page footer
    assert rows[0]["description"].endswith("ABC Holding Ltd. Şti. ocak ayı")
    assert rows[1]["description"].endswith("devamı ofis kirası yine devamı")
    assert not any("line_unreadable" in r for r in rows)                                    # not held a second time
    assert ledger.read == ledger.emitted + ledger.continuation + ledger.non_row_lines + ledger.summary_skipped


def test_summary_lines_of_a_text_statement_are_counted_and_listed_but_a_payment_named_toplam_is_not() -> None:
    text = (
        "GARANTİ BBVA\n"
        "Devreden Bakiye 10.000,00\n"
        "01.01.2026 Kira -1.000,00 9.000,00\n"
        "02.01.2026 Toplam fatura ödemesi -500,00 8.500,00\n"
        "03.01.2026 Toplam -999,00\n"
        "Toplam\n"
    )
    rows, ledger = _pipeline(GarantiParser, text)
    assert ledger.summary_skipped == 2 and ledger.summary_lines[0]["description"] == "Devreden Bakiye 10.000,00"
    assert [r["description"] for r in rows][:2] == ["Kira", "Toplam fatura ödemesi"]


# ── `read` is independent of every row pattern ───────────────────────────────────────────────────────────────

def test_read_does_not_depend_on_the_row_patterns(monkeypatch) -> None:
    text = "GARANTİ BBVA\n01.01.2026 Kira -1.000,00 9.000,00\n02.01.2026 Gaz ₺400,00\n"
    real = len(read_lines(text))
    for cls in (GarantiParser, AkbankParser, IsBankParser, ZiraatParser, YapiKrediParser):
        monkeypatch.setattr(cls, "_parse_table", lambda self, t: [], raising=False)    # a pattern that matches nothing
        parser = cls()
        account = account_for_lines(text, parser.parse(text, "").transactions)
        assert account.read == real == 3                                              # unchanged
        assert account.unread == 2 and len(account.transactions) == 2                 # both money lines held, none lost


def test_the_unit_count_is_computed_in_its_own_function_from_the_text_alone() -> None:
    assert "re.compile" not in inspect.getsource(read_lines) and "parse" not in inspect.getsource(read_lines).replace("splitlines", "")
    source = inspect.getsource(lines_module)
    assert "app.parsers.banks" not in source and "app.parsers.accounting" not in source     # no row pattern is imported


# ── blocker 2: a text statement says whether its balance was checked ─────────────────────────────────────────

def test_a_text_statement_with_a_balance_chain_is_reported_verified() -> None:
    from app.services.ingest.rows import _pdf_yonu
    from app.services.ingest.summary import ingest_summary

    text = (
        "GARANTİ BBVA Hesap Ekstresi\n"
        "01.01.2026 Maaş +2.000,00 12.000,00\n"
        "02.01.2026 Kira -1.000,00 11.000,00\n"
        "03.01.2026 Satış +500,00 11.500,00\n"
        "04.01.2026 Gaz -100,00 11.400,00\n"
    )
    rows, ledger = _pipeline(GarantiParser, text)
    assert _pdf_yonu(rows, "Garanti", text) == "verified"
    ledger.balance_check = "verified"
    assert "bakiye zinciriyle doğrulandı" in ingest_summary([], {}, ledger.as_dict())["summary"]


def test_a_text_statement_that_cannot_be_chained_says_so_and_proves_no_opening_balance() -> None:
    from app.services.bank_balance import closing_balance
    from app.services.ingest.rows import _pdf_yonu
    from app.services.ingest.summary import ingest_summary

    text = (
        "GARANTİ BBVA Hesap Ekstresi\n"
        "01.01.2026 Maaş +2.000,00 12.000,00\n"
        "02.01.2026 Kira -1.000,00 11.000,00\n"
        "03.01.2026 Gaz ₺400,00\n"                      # a line the pattern cannot read: the chain has a hole
        "04.01.2026 Satış +500,00 11.500,00\n"
    )
    rows, ledger = _pipeline(GarantiParser, text)
    status = _pdf_yonu(rows, "Garanti", text)
    assert status == "unverified"
    ledger.balance_check = status
    said = ingest_summary([], {}, ledger.as_dict())["summary"]
    assert "bakiye ile doğrulanamadı" in said and "bakiye zinciriyle doğrulandı" not in said
    # the radar's opening balance only ever comes from a proven chain: here there is none, so it is unknown
    assert closing_balance(rows) is None


def test_a_statement_that_is_not_text_reports_no_balance_claim() -> None:
    from app.services.ingest.summary import ingest_summary

    said = ingest_summary([{}], {}, {"read": 3, "balance_check": None})["summary"]
    assert "bakiye" not in said
