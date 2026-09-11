"""e-Arşiv faturası, GİB'in kendi örnekleriyle.

e-Arşiv is not a separate format: it is a UBL-TR Invoice with ProfileID
EARSIVFATURA, and GİB's UBL-TR package ships six of them. None had a test.

Read as they are, all six produce no journal entry — and that is right. GİB's
samples put the same VKN (3333333888) on both sides, and an invoice whose
seller and buyer are the same taxpayer does not say which side of it we are
on. So the first test pins that refusal, and the second puts our own VKN on
one side to show the same documents post, balanced, once the side is known.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.parsers.invoice.ubl_tr import UBLTRInvoiceParser

XML = Path(__file__).resolve().parent / "fixtures" / "gib_corpus" / "ubl_tr" / "UBLTR_1.2.1_Paketi" / "xml"
OURS = "1234567808"
GIB = "3333333888"


def _samples() -> list[Path]:
    if not XML.is_dir():
        return []
    return sorted(f for f in XML.glob("*.xml") if b"<cbc:ProfileID>EARSIVFATURA" in f.read_bytes())


SAMPLES = _samples()
pytestmark = pytest.mark.skipif(
    not SAMPLES, reason="GİB UBL-TR paketi yok — python scripts/fetch_gib_corpus.py"
)


def _with_vkn(raw: bytes, party: str, vkn: str) -> bytes:
    """Replace the VKN inside one party block, and only there."""
    tag = f"cac:{party}".encode()
    start = raw.index(b"<" + tag + b">")
    end = raw.index(b"</" + tag + b">") + len(tag) + 3
    block = re.sub(
        rb'(<cbc:ID schemeID="VKN">)\d+(</cbc:ID>)', rb"\g<1>" + vkn.encode() + rb"\g<2>", raw[start:end]
    )
    return raw[:start] + block + raw[end:]


def test_the_package_has_the_six_earsiv_samples() -> None:
    assert len(SAMPLES) == 6


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.name)
def test_same_vkn_on_both_sides_posts_nothing(path: Path) -> None:
    inv = UBLTRInvoiceParser.parse_xml(path.read_bytes(), own_vkn=GIB)
    assert inv.profile_id == "EARSIVFATURA"
    assert inv.direction == "unknown"
    assert "aynı VKN" in inv.direction_basis
    assert inv.needs_review and not inv.suggested_tdhp_entries


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.name)
@pytest.mark.parametrize(("party", "direction"), [
    ("AccountingSupplierParty", "sale"),
    ("AccountingCustomerParty", "purchase"),
])
def test_once_the_side_is_known_the_invoice_posts_balanced(
    path: Path, party: str, direction: str
) -> None:
    raw = _with_vkn(path.read_bytes(), party, OURS)
    inv = UBLTRInvoiceParser.parse_xml(raw, own_vkn=OURS)
    assert inv.direction == direction
    entries = inv.suggested_tdhp_entries
    assert entries, inv.posting_note
    debit = sum((e.debit_amount for e in entries), Decimal(0))
    credit = sum((e.credit_amount for e in entries), Decimal(0))
    assert debit == credit


def test_a_sales_earsiv_books_its_kdv_to_391() -> None:
    path = next(p for p in SAMPLES if "Satıs" in p.name or "Satış" in p.name)
    inv = UBLTRInvoiceParser.parse_xml(_with_vkn(path.read_bytes(), "AccountingSupplierParty", OURS), own_vkn=OURS)
    kdv = {e.account_code: e.credit_amount for e in inv.suggested_tdhp_entries if e.account_code.startswith("391")}
    assert kdv and sum(kdv.values()) == Decimal("300.00")
