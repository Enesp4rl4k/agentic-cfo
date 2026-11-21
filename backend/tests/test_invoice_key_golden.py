"""Golden keys for plan v10 G23: the literal strings migration 065 wrote, and the lengths that bound them.

Migration 065 imports `document_key`, so what a fresh upgrade writes is whatever this function does
today. These literals are what it did when the migration shipped: if one fails, the normaliser or the
key format changed, and every stored `inv:` key (ledger rows, correction rows, overrides, open items)
no longer matches what the application computes for the same document. That change needs its own data
migration (re-key the stored ids), not an edit to these expected values.
"""

from __future__ import annotations

import pytest

from app.core.invoice_identity import document_key, variant_key

ALFA = "Alfa Gıda A.Ş."


@pytest.mark.parametrize(
    "org, number, counterparty, direction, expected",
    [
        ("org-1", "A-1", ALFA, "income", "inv:s:nd92075a582ad:A-1"),
        ("org-1", "a-1", "ALFA GIDA ANONIM SIRKETI", "income", "inv:s:nd92075a582ad:A-1"),
        ("org-1", "A-1", "Alfa Gıda San. ve Tic. A.Ş.", "expense", "inv:p:nbe73586c8f9f:A-1"),
        ("org-1", "2024/15", "Beta Tekstil Ltd. Şti.", "income", "inv:s:n2c76ecabbe4a:2024/15"),
        ("org-1", "A-1", "Alfa 1234567890", "expense", "inv:p:t47102f8d16d5:A-1"),
        ("org-1", "A-1", "Kaya 10000000146", "income", "inv:s:t2c332719681a:A-1"),
        ("org-2", "A-1", ALFA, "income", "inv:s:ne9d1ee87468b:A-1"),   # another organisation: another hash
        ("org-1", "GIB2024000000050", "x", "income", "doc:GIB2024000000050"),
        ("org-1", "A-1", None, "income", "doc:A-1"),
        ("org-1", "A-1", "Alfa", "other", "doc:A-1"),
    ],
)
def test_the_key_is_exactly_what_migration_065_wrote(org, number, counterparty, direction, expected):
    assert document_key(org, number, counterparty, direction) == expected


def test_a_variant_key_is_exactly_this():
    assert variant_key("inv:s:n4a50a86d5f0c:A-1", 100_000, "2024-03-01", "Alfa Ltd.") == (
        "inv:s:n4a50a86d5f0c:A-1~vb8d90e6c"
    )


def test_the_longest_key_fits_every_column_that_holds_it():
    """transactions.document_id is 64 wide; the ledger key is 120 wide with the longest suffixes; the open item 128."""
    number = "X" * 64                                      # the widest document number an upload can carry
    base = document_key("org-1", number, ALFA, "expense")
    variant = variant_key(base, 9_999_999_999_999, "2024-12-31", "A" * 300)
    assert len(base) == len("inv:p:") + 13 + 1 + 64 == 84
    assert len(variant) == 84 + len("~v") + 8
    assert len(variant + "~k999-iptal") <= 120             # canonical_transactions.source_record_id
    assert len(variant) <= 128                             # open_items.document_id (the item key is the ledger key)
    legacy = variant_key(document_key("org-1", number, None, "expense"), 1, "2024-01-01", None)
    assert len(legacy + "~k999-iptal") <= 120 and len(legacy) <= 128


def test_the_database_columns_are_as_wide_as_that_assumes():
    from app.models.canonical_transaction import CanonicalTransaction
    from app.models.open_item import OpenItem
    from app.models.transaction import Transaction

    assert Transaction.__table__.c.document_id.type.length == 64  # type: ignore[attr-defined]
    assert CanonicalTransaction.__table__.c.source_record_id.type.length == 120  # type: ignore[attr-defined]
    assert OpenItem.__table__.c.document_id.type.length == 128  # type: ignore[attr-defined]
