"""Bir üreticinin yazdığı kategori sözlükte yoksa, kimse onu tanımaz.

`_CATEGORY_MAP` is the vocabulary: revenue, other_income, cogs, salary, tax,
loan, rent, utilities, marketing, technology, other_expense. `_guess_category`
can only ever return one of those, so every producer that goes through it is
safe by construction.

The producers that hardcode a category are not. The UBL-TR path wrote "sales",
which is a keyword *inside* the revenue rule and not a category at all —
nothing downstream that groups on category could see those rows. It sat there
because the P&L computes revenue from `type == "income"` rather than from the
category, so the number that would have exposed it stayed right.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.agents.data_ingestion import _CATEGORY_MAP, _guess_category

APP = Path(__file__).resolve().parents[1] / "app"

VOCABULARY = {cat for cat, _kw, _pri in _CATEGORY_MAP} | {"other_expense"}


def test_the_vocabulary_is_what_we_think_it_is() -> None:
    """A guard on the guard: if the categories change, the tests below stop
    meaning what they claim."""
    assert "revenue" in VOCABULARY
    assert "sales" not in VOCABULARY, (
        '"sales" is a keyword inside the revenue rule, not a category'
    )
    assert "cogs" in VOCABULARY and "other_expense" in VOCABULARY


@pytest.mark.parametrize(
    "description",
    ["", "  ", "bilinmeyen bir açıklama", "Ocak ayı ofis kirası", "AWS invoice"],
)
def test_guess_category_can_only_return_a_known_category(description: str) -> None:
    assert _guess_category(description) in VOCABULARY


def _dict_keys(node: ast.Dict) -> set[str]:
    return {
        k.value for k in node.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }


def _hardcoded_categories() -> dict[str, str]:
    """Literal categories written into *transaction* dicts, mapped to where.

    Scoped by shape, not by the key name alone: "category" is also the key for
    risk categories, compliance categories and CSV column aliases, which are
    different vocabularies that happen to share a word. A transaction is the
    dict that also carries an amount.
    """
    found: dict[str, str] = {}
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(APP.parent)).replace("\\", "/")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = _dict_keys(node)
            if "category" not in keys or not keys & {"amount_cents", "amount", "tutar"}:
                continue
            for key, value in zip(node.keys, node.values):
                if not (isinstance(key, ast.Constant) and key.value == "category"):
                    continue
                # Only a literal, or a conditional between literals. Walking the
                # whole value wanders into the comparison of
                # `"cogs" if direction == "inbound" else "revenue"` and reports
                # "inbound" as a category.
                candidates: list[ast.expr] = [value]
                if isinstance(value, ast.IfExp):
                    candidates = [value.body, value.orelse]
                for cand in candidates:
                    if not (isinstance(cand, ast.Constant) and isinstance(cand.value, str)):
                        continue
                    # A category is one token. Anything with a space is prose —
                    # a field label, a help string — sharing the key name.
                    if " " in cand.value:
                        continue
                    found.setdefault(cand.value, f"{rel}:{cand.lineno}")
    return found


def test_no_producer_invents_a_category() -> None:
    unknown = [
        f"{cat!r}  ({where})"
        for cat, where in sorted(_hardcoded_categories().items())
        if cat not in VOCABULARY
    ]
    assert not unknown, (
        "sözlükte olmayan kategori yazılıyor — _CATEGORY_RULES içindeki "
        "adlardan birini kullanın, yoksa kategoriye göre gruplayan hiçbir yer "
        "bu satırları görmez:\n  " + "\n  ".join(unknown)
    )


def test_the_efatura_client_emits_known_categories() -> None:
    """The GİB client builds its rows by hand, in both directions."""
    from app.services.gib_efatura import EFaturaClient

    client = EFaturaClient.__new__(EFaturaClient)
    item = {"issueDate": "2024-03-15", "payableAmount": 1000.0, "uuid": "x"}
    for direction in ("inbound", "outbound"):
        rows = client._parse_invoice_list([dict(item)], direction)
        assert rows, direction
        assert rows[0]["category"] in VOCABULARY, rows[0]["category"]


def test_efatura_amounts_do_not_lose_a_kurus_to_truncation() -> None:
    """`int(19.99 * 100)` is 1998: binary floating point lands just under, and
    int() truncates rather than rounds. Always downward, on a large share of
    ordinary amounts."""
    from app.services.gib_efatura import EFaturaClient

    client = EFaturaClient.__new__(EFaturaClient)
    rows = client._parse_invoice_list(
        [
            {"issueDate": "2024-03-15", "payableAmount": 19.99, "uuid": "a"},
            {"issueDate": "2024-03-16", "payableAmount": 1234567.89, "uuid": "b"},
        ],
        "inbound",
    )
    assert [r["amount_cents"] for r in rows] == [1999, 123456789]


def test_an_unrecognised_response_produces_no_phantom_rows() -> None:
    """Every field is read by guessing among three key spellings, because this
    client was written against a response nobody had seen. When the guesses all
    miss, the old code emitted a transaction with no date and no amount."""
    from app.services.gib_efatura import EFaturaClient

    client = EFaturaClient.__new__(EFaturaClient)
    rows = client._parse_invoice_list(
        [{"someOtherShape": 1}, {"alsoUnknown": "x"}], "inbound"
    )
    assert rows == []


def test_an_uploaded_category_column_is_checked_against_the_vocabulary() -> None:
    """A category column is the uploader's word, not ours.

    It used to pass straight through: "Gıda", "payroll", "sales" — all
    reasonable things to write in a spreadsheet, none of them something this
    pipeline groups by. An unrecognised category is worse than a guessed one,
    because it vanishes from every report without a word.
    """
    from app.agents.data_ingestion import _try_parse_csv

    csv_text = (
        "date,description,amount,category\n"
        "2024-01-15,Ocak ofis kirası,-28500.00,Gıda\n"
        "2024-01-16,Yazılım lisans geliri,285000.00,revenue\n"
    )
    rows = _try_parse_csv(csv_text)
    assert rows and len(rows) == 2
    for row in rows:
        assert row["category"] in VOCABULARY, row["category"]
    # "Gıda" is not a category, so the description decides instead.
    assert rows[0]["category"] == "rent"
    # A category we do know is kept as written.
    assert rows[1]["category"] == "revenue"
