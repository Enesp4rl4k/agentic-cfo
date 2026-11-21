"""G23 — an invoice number in a bank description is a whole token, and a shared number needs a name.

`_number_in` used to test `number in description`, so "12" matched "A1234" and settled the
wrong invoice. These are the cases a person would call different numbers.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.services.reconciliation import BY_NAME, BY_NUMBER, CONFIRMED, PROPOSED, _decide, _number_in


def _item(number: str, *, counterparty: str = "Alfa Ltd", cents: int = 100_000, id_: str = "i1",
          direction: str = "payable"):
    return SimpleNamespace(
        id=id_, description=f"e-Fatura {number}: {counterparty}", counterparty=counterparty,
        amount_cents=cents, paid_cents=0, currency="TRY", direction=direction,
        issue_date=date(2024, 1, 1), due_date=date(2024, 2, 1),
    )


@pytest.mark.parametrize(
    "number, description, found",
    [
        ("12", "A1234 ODEME", False),             # inside a longer alphanumeric run
        ("12", "ODEME 1234", False),
        ("12", "ODEME 12", True),
        ("12", "FATURA NO 12 TESEKKURLER", True),
        ("12", "FATURA 12.", True),               # a sentence's full stop is not part of a number
        ("12", "FATURA NO:12", True),
        ("12", "INV-12 ODEME", False),            # "INV-12" is another number than "12"
        ("12", "2024-12 ODEME", False),
        ("12", "12/2024 ODEME", False),
        ("2024/15", "FATURA 2024/15 BEDELI", True),
        ("2024/15", "FATURA 2024-15 BEDELI", False),    # another separator is not guessed
        ("2024/15", "FATURA 12024/15", False),
        ("2024/15", "FATURA 2024/155", False),
        ("2024/15", "FATURA 2024/15/1", False),
        ("15", "FATURA 2024/15 BEDELI", False),
        ("A-001", "A-001 NOLU FATURA", True),
        ("A-001", "A-0012 NOLU FATURA", False),
        ("A-001", "XA-001", False),
        ("A-001", "A-1", False),                  # leading zeros are significant
        ("001", "ODEME 1", False),
        ("1", "ODEME 001", False),
        ("001", "ODEME 001", True),
        ("GIB2024000000050", "GIB2024000000050 FATURASI", True),
        ("GIB2024000000050", "GIB20240000000501", False),
        ("a-1", "ODEME A-1", True),               # case and Turkish letters fold
        ("İ-5", "ODEME i-5", True),
    ],
)
def test_the_number_is_a_whole_token(number, description, found):
    assert _number_in(_item(number), description) is found


def test_an_item_with_no_number_in_its_description_is_never_number_matched():
    item = SimpleNamespace(description="Satış faturası", counterparty="x")
    assert _number_in(item, "Satış faturası 12") is False


def _row(description: str, cents: int = 100_000):
    return SimpleNamespace(
        id="r1", description=description, amount_cents=cents, currency="TRY", direction="expense",
        transaction_date=datetime(2024, 1, 20, tzinfo=UTC),
    )


def test_a_short_number_does_not_settle_an_invoice_whose_number_merely_contains_it():
    short, long_ = _item("12", id_="short", counterparty="Beta Ltd"), _item("A1234", id_="long")
    match = _decide(_row("ODEME A1234"), [short, long_], set())
    assert match is not None and match.item.id == "long" and match.method == BY_NUMBER


def test_two_suppliers_with_one_number_are_told_apart_by_the_name_in_the_description():
    alfa = _item("A-1", counterparty="Alfa Gıda A.Ş.", id_="alfa", cents=100_000)
    beta = _item("A-1", counterparty="Beta Tekstil Ltd.", id_="beta", cents=100_000)
    match = _decide(_row("A-1 NOLU FATURA BETA TEKSTIL"), [alfa, beta], set())
    assert match is not None
    assert (match.item.id, match.method, match.status) == ("beta", BY_NUMBER, CONFIRMED)


def test_a_shared_number_with_no_name_is_never_settled_automatically():
    alfa = _item("A-1", counterparty="Alfa Gıda A.Ş.", id_="alfa", cents=100_000)
    beta = _item("A-1", counterparty="Beta Tekstil Ltd.", id_="beta", cents=100_000)
    match = _decide(_row("A-1 NOLU FATURA"), [alfa, beta], set())
    assert match is not None
    assert match.status == PROPOSED          # a person chooses; the number alone never confirms
    assert match.method != BY_NUMBER


def test_a_shared_number_with_the_wrong_amount_for_the_named_supplier_is_not_matched_to_the_other():
    alfa = _item("A-1", counterparty="Alfa Gıda A.Ş.", id_="alfa", cents=100_000)
    beta = _item("A-1", counterparty="Beta Tekstil Ltd.", id_="beta", cents=250_000)
    match = _decide(_row("A-1 BETA TEKSTIL", cents=100_000), [alfa, beta], set())
    # Beta is named but its amount differs: it may be a part payment (a proposal), never Alfa's invoice.
    assert match is not None and match.item.id == "beta" and match.status == PROPOSED


def test_the_name_alone_with_the_exact_amount_still_confirms():
    alfa = _item("A-1", counterparty="Alfa Gıda A.Ş.", id_="alfa", cents=100_000)
    match = _decide(_row("ALFA GIDA HAVALE"), [alfa], set())
    assert match is not None and (match.method, match.status) == (BY_NAME, CONFIRMED)
