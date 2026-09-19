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
from decimal import Decimal
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
    # Knowing the direction is not the same as being able to post: a foreign
    # currency with no rate, or components that do not reach the invoice's own
    # total, still stop the entry. Those hold for a reason, and say so.
    if inv.needs_review:
        assert inv.posting_note and "yönü belirlenemedi" not in inv.posting_note


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


# ── Tax components, and the balance that proves we read them all ─────────────

def _as_supplier(path: Path):
    """Parse as if we issued it, so a journal is actually generated."""
    vkn = UBLTRInvoiceParser.normalize_vkn(_party_vkn(path, "AccountingSupplierParty"))
    return UBLTRInvoiceParser.parse_xml(path.read_bytes(), own_vkn=vkn or "1234567890")


@pytest.mark.parametrize("path", _invoices(), ids=_ids(_invoices()))
def test_a_generated_journal_always_balances(path: Path) -> None:
    """The one invariant of double-entry bookkeeping.

    Eleven of GİB's 43 documents used to produce an unbalanced journal. It
    would be easy to make this pass by deriving revenue as whatever squares the
    two sides — and that would silently turn every tax we failed to read into
    revenue. So the entry is built from components read off the document and
    the balance is checked afterwards; an invoice that will not balance is not
    posted at all, with a note saying why.
    """
    inv = _as_supplier(path)
    if not inv.suggested_tdhp_entries:
        assert inv.posting_note, "kayıt üretilmediyse gerekçesi yazılmalı"
        return
    debit = sum(e.debit_amount for e in inv.suggested_tdhp_entries)
    credit = sum(e.credit_amount for e in inv.suggested_tdhp_entries)
    assert debit == credit, f"{path.name}: borç {debit} != alacak {credit}"


def test_no_invoice_is_ever_silently_dropped() -> None:
    """Posted or held — never neither, never without a reason."""
    for path in _invoices():
        inv = _as_supplier(path)
        assert bool(inv.suggested_tdhp_entries) != bool(inv.posting_note), (
            f"{path.name}: kayıt da yok gerekçe de yok (ya da ikisi birden var)"
        )


def _find(name: str) -> Path:
    for p in _invoices():
        if p.name == name:
            return p
    pytest.skip(f"{name} korpusta yok")
    raise AssertionError  # pragma: no cover


def test_tevkifat_is_read_and_splits_the_vat_correctly() -> None:
    """`withholding_tax_amount` was a hardcoded 0.0 on a model that advertised it.

    Tevkifat lives in cac:WithholdingTaxTotal, not in TaxTotal, so it was never
    read and every withheld invoice came out short by exactly the amount
    withheld. On GİB's sample: matrah 20000, KDV 3600, tevkifat 3240 (%90),
    ödenecek 20360.
    """
    inv = _as_supplier(_find("TEVKIFAT.xml"))
    assert inv.withholding_tax_amount == Decimal("3240")
    assert inv.payable_amount == Decimal("20360")

    by_code = {e.account_code: e for e in inv.suggested_tdhp_entries}
    assert by_code["120.01"].debit_amount == Decimal("20360")
    assert by_code["600.01"].credit_amount == Decimal("20000")
    # The buyer declares the withheld part itself; the seller carries the rest.
    assert by_code["391.01"].credit_amount == Decimal("360")


def test_tevkifat_from_the_buyers_side_owes_the_withheld_vat() -> None:
    """2 no'lu KDV beyannamesi: the buyer is liable for the withheld portion."""
    path = _find("TEVKIFAT.xml")
    vkn = UBLTRInvoiceParser.normalize_vkn(_party_vkn(path, "AccountingCustomerParty"))
    if not vkn:
        pytest.skip("alıcı VKN yok")
    inv = UBLTRInvoiceParser.parse_xml(path.read_bytes(), own_vkn=vkn)

    by_code = {e.account_code: e for e in inv.suggested_tdhp_entries}
    assert by_code["191.01"].debit_amount == Decimal("3600")   # full VAT deductible
    assert by_code["320.01"].credit_amount == Decimal("20360")  # what we actually pay
    assert by_code["360.02"].credit_amount == Decimal("3240")   # what we owe the state


def test_ozel_matrah_does_not_add_vat_that_is_already_in_the_price() -> None:
    """KDV declared, but inclusive == exclusive: it is inside the price.

    Adding it on top double-counted it and broke the balance by exactly the VAT.
    """
    inv = _as_supplier(_find("OZELMATRAH.xml"))
    assert inv.tax_inclusive_total == inv.tax_exclusive_total == Decimal("24.94")

    by_code = {e.account_code: e for e in inv.suggested_tdhp_entries}
    assert by_code["120.01"].debit_amount == Decimal("24.94")
    assert by_code["391.01"].credit_amount == Decimal("4.01")
    assert by_code["600.01"].credit_amount == Decimal("20.93")


def test_vat_is_recognised_however_gib_spells_it() -> None:
    """GİB writes tax code 0015 under four different names in its own package —
    "KDV", "Katma Değer Vergisi", "GERÇEK USULDE KATMA DEĞER VERGİSİ", and once
    with no name at all. Matching on the name dropped five of 26 subtotals."""
    inv = _as_supplier(_find("HASTANE.xml"))
    names = {t.tax_category_name for t in inv.tax_subtotals}
    assert any("Katma" in n for n in names), "bu örnek KDV'yi açık adıyla yazıyor"

    by_code = {e.account_code: e for e in inv.suggested_tdhp_entries}
    assert by_code["391.01"].credit_amount == Decimal("11.28")
    assert by_code["600.01"].credit_amount == Decimal("141.07")


def test_otv_is_not_merged_into_deductible_vat() -> None:
    """0071 is ÖTV. It is never deductible VAT, and this sample proves the
    codes have to be read: the ÖTV subtotal is larger than the KDV one."""
    inv = _as_supplier(_find("OTV.xml"))
    codes = {t.tax_category_code: t.tax_amount for t in inv.tax_subtotals}
    assert codes["0071"] == Decimal("1842.62")
    assert codes["0015"] == Decimal("1482.17")


def test_gibs_own_otv_sample_does_not_add_up_and_is_held() -> None:
    """Not our arithmetic: 6391.67 + 3324.79 = 9716.46, and the document says
    the payable is 9718.48. An invoice whose components do not reach its own
    total is one we do not understand well enough to post."""
    inv = _as_supplier(_find("OTV.xml"))
    assert inv.suggested_tdhp_entries == []
    assert "dengelenmedi" in inv.posting_note
    assert "2.02" in inv.posting_note


def test_discount_is_read() -> None:
    """`allowance_total` was on the model from the start and never populated."""
    inv = _as_supplier(_find("TicariFaturaOrnegi.xml"))
    assert inv.allowance_total == Decimal("786.90")
    # 26003.40 - 786.90 = 25216.50
    assert inv.tax_exclusive_total == Decimal("25216.50")

    by_code = {e.account_code: e for e in inv.suggested_tdhp_entries}
    assert by_code["600.01"].credit_amount == Decimal("25216.50")
    assert by_code["391.01"].credit_amount == Decimal("4538.97")


def test_foreign_currency_is_not_booked_into_a_lira_ledger() -> None:
    """A USD invoice used to post its USD figure into a TRY journal with no
    rate and no flag — invisible afterwards, and the exact error the
    integer-kuruş rule exists to prevent."""
    inv = _as_supplier(_find("ISTISNA-2.xml"))
    assert inv.currency_code == "USD"
    assert inv.suggested_tdhp_entries == []
    assert "kur" in inv.posting_note


def test_export_invoice_credits_601_not_600() -> None:
    """Yurtdışı satış 601'e yazılır. GİB marks it on the profile."""
    inv = _as_supplier(_find("IHRACAT.xml"))
    if inv.profile_id.upper() != "IHRACAT":
        pytest.skip("bu örnek IHRACAT profili taşımıyor")
    if not inv.suggested_tdhp_entries:
        pytest.skip(f"kayıt üretilmedi: {inv.posting_note}")
    codes = {e.account_code for e in inv.suggested_tdhp_entries}
    assert "601.01" in codes
    assert "600.01" not in codes
