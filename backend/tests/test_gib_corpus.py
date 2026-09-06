"""The parser, run against the documents GİB itself publishes.

Every other fixture in this suite was written by hand, and each was written to
match the code it exercises — the bank statement fixtures are shaped around the
regexes, so they can only ever confirm what the regex already believed. This
module uses the Revenue Administration's own package instead: 43 documents
covering all fourteen invoice type codes it issues, plus the XBRL GL schemas a
ledger is validated against before it can be filed.

Fetch it with `python scripts/fetch_gib_corpus.py`. It is not vendored — a copy
in the tree would drift from the standard, and drift is what this catches.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.parsers.invoice.ubl_tr import NotAnInvoiceError, UBLTRInvoiceParser

CORPUS = Path(__file__).resolve().parent / "fixtures" / "gib_corpus"
UBL_XML = CORPUS / "ubl_tr" / "UBLTR_1.2.1_Paketi" / "xml"

pytestmark = pytest.mark.skipif(
    not UBL_XML.is_dir(),
    reason="GİB korpusu yok — python scripts/fetch_gib_corpus.py",
)

INVOICE_ROOT = "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice"


def _all_documents() -> list[Path]:
    return sorted(UBL_XML.glob("*.xml")) if UBL_XML.is_dir() else []


def _invoices() -> list[Path]:
    out = []
    for p in _all_documents():
        try:
            if ET.parse(p).getroot().tag == INVOICE_ROOT:
                out.append(p)
        except ET.ParseError:  # pragma: no cover - GİB ships well-formed XML
            continue
    return out


def _ids(paths: list[Path]) -> list[str]:
    return [p.name for p in paths]


# ── The corpus is what we think it is ─────────────────────────────────────────

def test_corpus_covers_the_document_types_gib_actually_issues() -> None:
    """A guard on the input, not the code: if GİB reshapes the package, the
    tests below stop meaning what they claim and should say so loudly."""
    docs = _all_documents()
    assert len(docs) >= 40, f"beklenenden az belge: {len(docs)}"
    assert len(_invoices()) >= 25, "fatura sayısı beklenenden az"


# ── Non-invoices must be refused, not silently accepted ───────────────────────

def test_every_document_is_either_parsed_or_refused_by_name() -> None:
    """No document may parse into an invoice it is not.

    DespatchAdvice (e-İrsaliye), ApplicationResponse and ReceiptAdvice are
    valid UBL with no monetary total. They used to parse into a perfectly
    balanced 0,00 TL SATIS invoice, because every `find` returned None and
    every default held. Uploading an e-İrsaliye folder produced phantom sales.
    """
    invoices = {p.name for p in _invoices()}
    refused: list[str] = []
    for path in _all_documents():
        try:
            UBLTRInvoiceParser.parse_xml(path.read_bytes(), own_vkn="1234567890")
        except NotAnInvoiceError:
            refused.append(path.name)
            continue

    non_invoices = {p.name for p in _all_documents()} - invoices
    assert set(refused) == non_invoices, (
        "fatura olmayan her belge reddedilmeli.\n"
        f"  reddedilmesi gereken ama geçen: {sorted(non_invoices - set(refused))}\n"
        f"  yanlışlıkla reddedilen       : {sorted(set(refused) - non_invoices)}"
    )
    assert refused, "korpusta fatura olmayan belge yok — korpus değişmiş olmalı"


@pytest.mark.parametrize("path", _invoices(), ids=_ids(_invoices()))
def test_every_real_invoice_parses(path: Path) -> None:
    inv = UBLTRInvoiceParser.parse_xml(path.read_bytes(), own_vkn="1234567890")
    assert inv.invoice_number
    assert inv.issue_date is not None


# ── Direction comes from the VKN, never from the type code ────────────────────

NS = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}


def _party_vkn(path: Path, side: str) -> str:
    """Read one side's VKN the way the parser is required to: by schemeID.

    GİB's HKS samples list MERSISNO before VKN, and the same element carries
    PLAKA, SAYACNO and TESISATNO elsewhere in the corpus.
    """
    party = ET.parse(path).getroot().find(f"cac:{side}/cac:Party", NS)
    if party is None:
        return ""
    for node in party.findall("cac:PartyIdentification/cbc:ID", NS):
        if (node.get("schemeID") or "").upper() in ("VKN", "TCKN"):
            return (node.text or "").strip()
    return ""


def _both_sides_share_a_vkn(path: Path) -> bool:
    """GİB reuses one placeholder VKN on both parties in part of the corpus."""
    sup = UBLTRInvoiceParser.normalize_vkn(_party_vkn(path, "AccountingSupplierParty"))
    cus = UBLTRInvoiceParser.normalize_vkn(_party_vkn(path, "AccountingCustomerParty"))
    return bool(sup) and sup == cus


def test_identifier_is_chosen_by_scheme_not_by_position() -> None:
    """Two of GİB's own samples put MERSISNO first.

    Taking the first `PartyIdentification` read a MERSİS number as the tax
    number, and the same slot carries licence plates and meter numbers
    elsewhere in the package.
    """
    hks = [p for p in _invoices() if p.name.startswith("HKS-")]
    if not hks:
        pytest.skip("HKS örnekleri korpusta yok")
    for path in hks:
        inv = UBLTRInvoiceParser.parse_xml(path.read_bytes(), own_vkn="1234567890")
        expected = _party_vkn(path, "AccountingSupplierParty")
        assert inv.supplier.vkn_tckn == expected, (
            f"{path.name}: VKN yerine başka bir kimlik okundu "
            f"({inv.supplier.vkn_tckn!r} != {expected!r})"
        )


@pytest.mark.parametrize("path", _invoices(), ids=_ids(_invoices()))
def test_invoice_we_issued_is_income_whatever_its_type_code(path: Path) -> None:
    """The regression this module exists for.

    Direction used to be `invoice_type in ("SATIS", "IHRACAT", "KOMISYON")`.
    Against GİB's fourteen real codes that made exactly one an income and
    thirteen an expense — YTBSATIS, a sale by name, was booked as a cost, and
    every tevkifatlı invoice (construction, cleaning, security, staffing: the
    target segment) had its revenue recorded as spend. Two of the three codes
    in that list are not codes GİB issues at all.
    """
    if _both_sides_share_a_vkn(path):
        pytest.skip("GİB örneği iki tarafta da aynı yer tutucu VKN'yi taşıyor")
    vkn = UBLTRInvoiceParser.normalize_vkn(_party_vkn(path, "AccountingSupplierParty"))
    if not vkn:
        pytest.skip("bu örnekte satıcı VKN yok")

    inv = UBLTRInvoiceParser.parse_xml(path.read_bytes(), own_vkn=vkn)
    assert inv.direction == "sale", (
        f"{path.name} ({inv.invoice_type}): satıcı biziz ama yön {inv.direction!r} — "
        f"{inv.direction_basis}"
    )
    assert not inv.needs_review


@pytest.mark.parametrize("path", _invoices(), ids=_ids(_invoices()))
def test_same_invoice_flips_to_purchase_when_we_are_the_customer(path: Path) -> None:
    """Direction is a property of who we are, not of the document."""
    if _both_sides_share_a_vkn(path):
        pytest.skip("GİB örneği iki tarafta da aynı yer tutucu VKN'yi taşıyor")
    vkn = UBLTRInvoiceParser.normalize_vkn(_party_vkn(path, "AccountingCustomerParty"))
    if not vkn:
        pytest.skip("bu örnekte alıcı VKN yok")

    inv = UBLTRInvoiceParser.parse_xml(path.read_bytes(), own_vkn=vkn)
    assert inv.direction == "purchase", f"{path.name}: {inv.direction_basis}"


@pytest.mark.parametrize("path", _invoices(), ids=_ids(_invoices()))
def test_shared_vkn_on_both_sides_is_not_a_direction(path: Path) -> None:
    """Same VKN on both parties means neither side is ours in particular.

    Branch transfers look like this and so do malformed invoices; picking a
    side would be a guess dressed as a fact.
    """
    if not _both_sides_share_a_vkn(path):
        pytest.skip("bu örnekte taraflar farklı VKN taşıyor")
    vkn = UBLTRInvoiceParser.normalize_vkn(_party_vkn(path, "AccountingSupplierParty"))
    inv = UBLTRInvoiceParser.parse_xml(path.read_bytes(), own_vkn=vkn)
    assert inv.direction == "unknown"
    assert inv.suggested_tdhp_entries == []


@pytest.mark.parametrize("path", _invoices()[:6], ids=_ids(_invoices()[:6]))
def test_unknown_direction_posts_nothing_and_holds_for_review(path: Path) -> None:
    """A stranger's VKN settles neither side, so nothing may be posted.

    A journal line on the wrong side is not a smaller error than a missing one:
    it is the same money booked backwards, and it reconciles perfectly while
    doing so.
    """
    inv = UBLTRInvoiceParser.parse_xml(path.read_bytes(), own_vkn="9999999999")
    assert inv.direction == "unknown"
    assert inv.needs_review
    assert inv.suggested_tdhp_entries == []


def test_missing_own_vkn_is_unknown_not_a_guess() -> None:
    path = _invoices()[0]
    inv = UBLTRInvoiceParser.parse_xml(path.read_bytes(), own_vkn="")
    assert inv.direction == "unknown"
    assert "GIB_VKN" in inv.direction_basis


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234567890", "1234567890"),      # VKN
        ("12345678901", "12345678901"),    # TCKN
        ("123 456 78 90", "1234567890"),
        ("123456789", ""),                 # too short — not an identifier
        ("123456789012", ""),              # too long
        ("", ""),
        (None, ""),
    ],
)
def test_only_vkn_and_tckn_lengths_can_decide_direction(raw, expected) -> None:
    """A truncated or padded number that happened to match would pick the side
    of the ledger an invoice posts to."""
    assert UBLTRInvoiceParser.normalize_vkn(raw) == expected
