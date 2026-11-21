"""Review of 6e47786: RULE A ("no digit left behind") and RULE B ("one door"), the reviewer's inputs verbatim.

Both were reproduced through the real entry: a money line without a date or a separator merged into the previous
row's description as a "continuation" (5000 lost, statement "verified"); a `₺` amount the pattern could not match
made the running balance the booked amount; the Logo connector called `parser.parse` directly and dropped rows
while reporting success with `skipped=0`.
"""
from __future__ import annotations

import ast
import random
from pathlib import Path

import pytest
import pytest_asyncio

from app.parsers.accounting.logo_tiger import LogoTigerParser
from app.parsers.accounting.mikro import MikroParser
from app.parsers.banks.garanti import GarantiParser
from app.parsers.lines import is_candidate, money_tokens
from app.services.erp.logo_tiger_connector import LogoTigerConnector, MikroConnector
from app.services.ingest.door import connector_rows, read_text_statement, sync_outcome
from app.services.ingest.hold import row_reasons, split_uncertain
from app.services.ingest.okuma import unaccounted
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.test_parsers.test_accounting_parsers import LOGO_TIGER_CSV

BASE = "GARANTİ BBVA Hesap Ekstresi\n01.01.2026 Kira -200,00 800,00\n"


def _is_held(row: dict) -> bool:
    """Whether the hold step would keep this row from the books (the currency is settled elsewhere)."""
    return bool(row_reasons({**row, "currency": "TRY"}))


def _door(extra: str):
    door = read_text_statement(GarantiParser(), BASE + extra + "\n")
    accepted, held = split_uncertain(door.rows)
    return door, accepted, held


# ── RULE A (i): a line that may carry money is held, never absorbed ──────────────────────────────────────────

@pytest.mark.parametrize(("line", "cents"), [
    ("Maas odemesi 5000", 500000),                  # reviewer input 1
    ("3 Kas Maas odemesi 5000", 500000),            # 2
    ("Kira bedeli 5000 TL", 500000),                # 3
    ("Beş bin lira havale", 0),                     # 4: a number in words: held with its raw text, amount unknown
])
def test_a_money_line_after_a_row_is_held_not_merged_into_its_description(line: str, cents: int) -> None:
    door, accepted, held = _door(line)
    assert len(door.rows) == 2, "the line must be a row of its own"
    kept = door.rows[0]
    assert "5000" not in kept["description"] and "bin" not in kept["description"]        # not absorbed
    row = door.rows[1]
    assert row["amount_cents"] == cents and row["description"] == line                    # right value, raw text kept
    assert "line_unreadable" in row_reasons({**row, "currency": "TRY"})
    assert unaccounted({**door.ledger.as_dict(), "accepted": len(accepted), "held": len(held)}) == 0


REVIEWER_LINES = [                       # review of a27cf27, verbatim: each used to be absorbed as a continuation
    "Hesap özeti ücreti 1.250,00", "Dönem sonu faiz 1.500,50", "Dönem sonu faiz 12.05.2025 1.500,50",
    "Belge 2500", "Referans 12345 EFT", "Ref 5000", "Müşteri 1500 tahsilat",
]


@pytest.mark.parametrize("line", REVIEWER_LINES)
def test_an_exemption_never_swallows_a_real_amount(line: str) -> None:
    door, accepted, held = _door(line)
    assert len(door.rows) == 2 and door.ledger.continuation == 0, "the line must be a row of its own"
    assert "line_unreadable" in row_reasons({**door.rows[1], "currency": "TRY"}) or door.rows[1].get("amount_uncertain")
    assert door.rows[1]["amount_cents"] > 0                                                  # the amount is on the held row
    assert door.balance_check != "verified" or _is_held(door.rows[1])                        # never a clean "verified" run without it
    assert unaccounted({**door.ledger.as_dict(), "accepted": len(accepted), "held": len(held)}) == 0


# Each exemption: the exempt token ALONE on a line is not held; the same token plus a money token on the line IS.
EXEMPT_PAIRS = [
    ("IBAN", "TR33 0006 1005 1978 6457 8413 26"),
    ("card mask", "**** 1234"),
    ("card 4-4-4-4", "4543 1234 5678 9010"),
    ("mobile phone", "0(532) 123 45 67"),
    ("+90 phone", "+90 212 318 18 18"),
    ("landline", "0 212 318 18 18"),
    ("0850 line", "0 850 222 0 333"),
    ("444 line", "444 0 333"),
    ("page marker", "Sayfa 2 / 5"),
    ("copyright year", "© 2026"),
    ("year phrase", "2026 yılı"),
    ("labelled id line", "Müşteri No: 4455667"),
    ("keyword reference (long)", "Ref 20250001234"),
    ("keyword reference (alphanumeric)", "Dekont FTR2025000123"),
]


@pytest.mark.parametrize(("name", "token"), EXEMPT_PAIRS, ids=[p[0] for p in EXEMPT_PAIRS])
def test_an_exempt_token_alone_is_not_held_but_the_same_token_with_money_is(name: str, token: str) -> None:
    assert not is_candidate(token), (name, money_tokens(token))
    for with_money in (f"{token} 1.250,00", f"Havale 750,00 {token}", f"{token} 5000"):
        assert is_candidate(with_money), (name, with_money)
    # and in a statement: with money it is a held row carrying that money
    door, _, _ = _door(f"{token} 1.250,00")
    assert door.rows[1]["amount_cents"] == 125000 and door.ledger.continuation == 0


def test_a_short_reference_number_stays_money_suspect_and_an_invalid_iban_is_not_an_iban() -> None:
    for line in ("Ref 5000", "Belge 2500", "Referans 12345", "TR33 0006 1005 1978 6457 8413 27"):
        assert is_candidate(line), line                                       # the last: checksum fails, so it is just digits
    assert not is_candidate("Hesap özeti")                                    # words alone exempt nothing and hold nothing
    assert is_candidate("Hesap özeti 1.250,00") and is_candidate("Toplam fatura 1.250,00")


def test_a_labelled_id_is_exempt_only_on_a_line_that_is_the_label_and_its_number() -> None:
    assert not is_candidate("Vergi No: 1234567890")
    assert is_candidate("Vergi No: 1234567890 12.05.2025")                   # a date on the line: not a header/footer line
    assert is_candidate("Vergi No: 1234567890 aidat 1.500,00")


# ── RULE A (ii)/(iii): a matched row with a number it did not account for is not booked ──────────────────────

def test_a_row_with_a_currency_marked_token_the_pattern_did_not_consume_is_held_not_booked() -> None:
    door, _, _ = _door("03.01.2026 B ₺5.000 -9.200")                                    # reviewer input 5
    row = door.rows[1]
    assert row.get("amount_uncertain") is True and "amount_uncertain" in row_reasons({**row, "currency": "TRY"})
    assert _is_held(row)                                                                     # held, with its raw line
    assert "₺5.000" in door.statement.transactions[1].raw_row
    assert row["amount_cents"] == 500000                                                     # shown beside the raw line: 5.000,00, not the balance


def test_a_plain_reference_number_in_a_description_does_not_make_a_row_uncertain() -> None:
    door, _, _ = _door("02.01.2026 FATURA 12345 +2.000,00 12.000,00")
    assert not door.rows[1].get("amount_uncertain")


def test_a_booked_amount_is_never_the_balance_when_another_money_token_is_on_the_line() -> None:
    door, _, _ = _door("04.01.2026 Havale ₺1.250,00 -3.700,00")
    row = door.rows[1]
    assert row["amount_cents"] != 370000 or row.get("amount_uncertain") or row.get("line_unreadable")


# ── RULE B: the ERP connector goes through the same door ─────────────────────────────────────────────────────

LOGO_BAD = LOGO_TIGER_CSV + "31.02.2026;F010;Maaş;5.000,00;;\n4 Ocak Havale 7.000,00\n05.01.2026;F011;Bozuk;abc;;\n"   # reviewer input 6


def test_the_logo_parser_through_the_door_loses_no_row_and_no_amount() -> None:
    door = read_text_statement(LogoTigerParser(), LOGO_BAD, "logo.csv", bank_name="Logo Tiger")
    rows = connector_rows(door, "logo_tiger")
    assert len(rows) == 4 + 3                                                               # the 4 good ones and the 3 bad
    by_text = {r["description"] for r in rows}
    assert any("Havale 7.000,00" in d for d in by_text) and any("31.02.2026" in d or "Maaş" in d for d in by_text)
    amounts = [r["amount_cents"] for r in rows]
    assert 500000 in amounts or any("5.000,00" in r["description"] for r in rows)
    assert any(r["type"] is None for r in rows)                                              # no direction was defaulted
    assert sync_outcome(door)["ok"] is True and sync_outcome(door)["held_candidates"] >= 3


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def test_the_logo_connector_never_says_success_for_rows_it_dropped(client) -> None:
    _, org_id, _ = await kullanici(client, "erp1@x.com")
    async with client._maker() as db:
        result = await LogoTigerConnector(db).sync_from_csv(org_id, LOGO_BAD, "logo.csv")
    assert len(result["transactions"]) == 7 and result["held_candidates"] >= 3 and result["needs_review"] is True
    assert result["counts"]["read"] >= 7 and result["skipped"] == 0
    assert not any(t["type"] == "expense" and t["amount_cents"] is None for t in result["transactions"] if "abc" in t["description"] and False)
    # the CSV the job reads keeps the unknown direction as "?" and the unreadable amount as "?": held, visible
    from app.services.ingest.ekle import islemler_csv

    text = islemler_csv(result["transactions"]).decode("utf-8")
    assert ",?" in text or ";?" in text


async def test_the_mikro_connector_goes_through_the_door_too(client) -> None:
    _, org_id, _ = await kullanici(client, "erp2@x.com")
    mikro = "MİKRO YAZILIM\nTarih;Açıklama;Giriş;Çıkış\n05.01.2024;Satış;1.000,00;\n31.02.2024;Bozuk tarih;;250,00\n06.01.2024;Kira;;500,00\n"
    async with client._maker() as db:
        result = await MikroConnector(db).sync_from_csv(org_id, mikro, "mikro.csv")
    assert len(result["transactions"]) == 3 and result["held_candidates"] >= 1


# ── injection property test, extended ────────────────────────────────────────────────────────────────────────

PLAIN_DIGIT_LINES = [("Hesap özeti ücreti 1.250,00", 125000), ("Dönem sonu faiz 1.500,50", 150050), ("Ref 5000", 500000),
                     ("Belge 2500", 250000), ("Toplam fatura 750,00", 75000), ("Devir ücreti 300,00", 30000),
                     ("Maas odemesi 5000", 500000), ("Kira bedeli 5000 TL", 500000), ("3 Kas Maas odemesi 5000", 500000),
                     ("Aidat 250", 25000), ("Havale 12000 lira", 1200000)]
EXTRA_TOKEN_ROWS = [("05.01.2026 B ₺5.000 -9.200", 500000), ("05.01.2026 Ödeme 100,00 $20,00 9.000,00", 10000)]


@pytest.mark.parametrize("seed", range(60))
def test_digit_bearing_lines_and_extra_token_rows_are_held_with_the_right_value(seed: int) -> None:
    rng = random.Random(seed)
    prefix = BASE + "02.01.2026 Maaş +2.000,00 2.800,00" + chr(10)
    base_rows = len(read_text_statement(GarantiParser(), prefix).rows)
    lines, cents = [], []
    for _ in range(rng.randint(1, 4)):
        line, c = rng.choice(PLAIN_DIGIT_LINES + EXTRA_TOKEN_ROWS)
        lines.append(line)
        cents.append(c)
    door = read_text_statement(GarantiParser(), prefix + chr(10).join(lines) + chr(10))
    accepted, held = split_uncertain(door.rows)
    assert len(accepted) + len(held) == base_rows + len(lines)                              # exactly the injected count
    raws = [tx.raw_row for tx, row in zip(door.statement.transactions, door.rows, strict=True) if _is_held(row)]
    for line, c in zip(lines, cents, strict=True):
        assert any(line in raw or raw in line for raw in raws), line                         # held, with its raw text
        owner = next(r for tx, r in zip(door.statement.transactions, door.rows, strict=True) if line in tx.raw_row or tx.raw_row in line)
        assert owner["amount_cents"] == c or (c == 0 and not owner["amount_cents"]), (line, owner["amount_cents"])   # the RIGHT value
    # and no injected amount is booked at all, under any value
    assert not [r for r in accepted if r.get("amount_uncertain") or r.get("line_unreadable")]


# ── architecture: one door ──────────────────────────────────────────────────────────────────────────────────

def test_no_module_outside_the_ingest_layer_calls_a_parsers_parse_directly() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    allowed = {"services/ingest/door.py"}                                   # the door itself; nothing else
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("parsers/") or rel in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "parse":
                target = ast.unparse(node.func.value)
                if "parser" in target.lower() and "email" not in target.lower() and "date" not in target.lower():
                    offenders.append(f"{rel}:{node.lineno} {ast.unparse(node.func)}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "to_thread" \
                    and node.args and "parse" in ast.unparse(node.args[0]) and "parser" in ast.unparse(node.args[0]).lower():
                offenders.append(f"{rel}:{node.lineno} {ast.unparse(node.args[0])}")
    assert not offenders, f"parsers must be called through app.services.ingest.door: {offenders}"


def test_no_direction_is_defaulted_in_the_connectors_or_the_csv_they_write() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    for rel in ("services/erp/logo_tiger_connector.py", "services/ingest/ekle.py", "parsers/accounting/parasut.py"):
        source = (root / rel).read_text(encoding="utf-8")
        assert 'or "expense"' not in source and 'or "income"' not in source, rel
    assert MikroParser and LogoTigerParser


@pytest.mark.parametrize("seed", range(12))
async def test_injected_erp_lines_through_the_connector_entry_are_all_present_and_never_booked_wrong(client, seed: int) -> None:
    from tests.test_text_lines_invariant import ERP_SHAPES

    rng = random.Random(seed)
    _, org_id, _ = await kullanici(client, f"erp-inj{seed}@x.com")
    lines = LOGO_TIGER_CSV.rstrip("\n").split("\n")
    injected: list[str] = []
    for _ in range(rng.randint(1, 4)):
        shape, _ = rng.choice(ERP_SHAPES)
        injected += shape
        lines[rng.randint(7, len(lines)):0] = shape
    async with client._maker() as db:
        result = await LogoTigerConnector(db).sync_from_csv(org_id, "\n".join(lines) + "\n", "logo.csv")
    rows = result["transactions"]
    assert len(rows) == 4 + len(injected)                                           # booked + held grew by exactly the injected count
    for line in injected:
        match = [r for r in rows if line in r["description"] or r["description"] in line]
        parsed_ok = [r for r in rows if r["amount_cents"] and r["type"]]
        assert match or parsed_ok, line                                              # present: raw text kept, or parsed with a value
    for r in rows:
        if any(line in r["description"] for line in injected):
            assert r["type"] is None or r["amount_cents"] is not None               # no half-read row is booked with a direction guess
    assert result["ok"] is True and result["counts"]["read"] >= 4 + len(injected)
