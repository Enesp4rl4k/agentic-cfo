"""Golden-case eval for THP account classification.

The existing eval corpus checks the CFO pipeline's arithmetic — revenue, EBITDA,
net margin. It says nothing about whether a transaction reaches the *right*
account, which is the one thing an SMMM would be held to. A trial balance can
foot perfectly and still book social-security withholdings as tax.

Marked `eval` so it runs in the same gate as the rest of the corpus.
"""
from __future__ import annotations

import pytest

from app.services.accounting.thp_classifier import THP_HESAPLARI, get_thp_classifier
from tests.fixtures.tr_corpus.thp_cases import COUNTER_ACCOUNTS, THP_GOLDEN_CASES

pytestmark = pytest.mark.eval


@pytest.mark.parametrize(
    ("description", "tx_type", "expected", "why"),
    THP_GOLDEN_CASES,
    ids=[c[0][:28] for c in THP_GOLDEN_CASES],
)
def test_thp_golden_case(description: str, tx_type: str, expected: str, why: str) -> None:
    result = get_thp_classifier().classify(
        description=description,
        vendor=None,
        transaction_type=tx_type,
        amount_kurus=100_000,
    )
    assert result.hesap_kodu == expected, (
        f"{description!r} -> {result.hesap_kodu} "
        f"({THP_HESAPLARI[result.hesap_kodu].adi if result.hesap_kodu in THP_HESAPLARI else '?'}), "
        f"beklenen {expected} ({THP_HESAPLARI[expected].adi}). {why}"
    )
    assert result.yontem == "kural", (
        "golden cases must be answerable by the deterministic rule engine; "
        f"{description!r} fell through to {result.yontem}"
    )


def test_classifier_never_returns_the_cash_counter_account() -> None:
    """`double_entry` supplies 100/102 itself as the other side of every entry.

    A classifier that also answers 102 produces 102/102: balanced, and
    meaningless. Payment-instrument words are the trap — "havale", "eft" and
    "transfer" describe how money moved, not what it should be booked against.
    """
    classifier = get_thp_classifier()
    instrument_phrasings = [
        ("Musteri odemesi havale ile geldi", "income"),
        ("Tedarikciye eft ile odeme", "expense"),
        ("Banka hesabina para transferi", "income"),
        ("Swift ile gelen odeme", "income"),
    ]
    for description, tx_type in instrument_phrasings:
        result = classifier.classify(
            description=description,
            vendor=None,
            transaction_type=tx_type,
            amount_kurus=100_000,
        )
        assert result.hesap_kodu not in COUNTER_ACCOUNTS, (
            f"{description!r} classified as {result.hesap_kodu} — "
            "double_entry already books the cash side"
        )


def test_no_keyword_is_claimed_by_two_accounts() -> None:
    """A keyword on two accounts makes the winner an accident of dict order.

    `sgk` sat on both 360 and 361, so "SGK primi ödemesi" scored a tie and 360
    won purely by being defined first.
    """
    seen: dict[str, str] = {}
    clashes: list[str] = []
    for kod, hesap in THP_HESAPLARI.items():
        for anahtar in hesap.anahtar_kelimeler:
            key = anahtar.strip().lower()
            if key in seen and seen[key] != kod:
                clashes.append(f"{key!r}: {seen[key]} and {kod}")
            else:
                seen.setdefault(key, kod)
    assert not clashes, "keyword claimed by more than one account:\n  " + "\n  ".join(clashes)
