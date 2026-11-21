"""UBL-TR invoice data: what a parsed GİB e-Fatura / e-Arşiv invoice is.

The parser in `ubl_tr.py` produces these; split out so the data contract and the
XML reading live apart (plan v11 F2). `ubl_tr` re-exports every name here.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

# UBL-TR ships more than invoices. Of the 43 documents GİB publishes in its own
# package, 15 are DespatchAdvice, ApplicationResponse or ReceiptAdvice — an
# e-İrsaliye is not a fatura and carries no monetary total. They parsed happily
# into a 0,00 TL SATIS invoice with a balanced journal behind it, because every
# `find` returned None and every default held.
INVOICE_ROOT = "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice"


class NotAnInvoiceError(ValueError):
    """The document is well-formed UBL, but it is not an Invoice."""

    def __init__(self, root_tag: str) -> None:
        self.root_tag = root_tag
        super().__init__(
            f"UBL kök elemanı 'Invoice' değil: {root_tag!r} — bu belge bir fatura değil."
        )


# Which side of the invoice we are on. `InvoiceTypeCode` cannot answer this: it
# names the *kind* of invoice (SATIS, TEVKIFAT, ISTISNA, OZELMATRAH…), never who
# issued it. Direction is settled by whose VKN sits in AccountingSupplierParty.
InvoiceDirection = Literal["sale", "purchase", "unknown"]

# GİB tax type codes. 0015 is KDV; 0071 is ÖTV. The display name cannot stand in
# for these — GİB writes KDV under four different names in its own samples.
KDV_TAX_CODE = "0015"

# What a journal is allowed to be out by before we stop calling it balanced.
# Wide enough for per-line rounding on a long invoice, far too narrow to absorb
# a missing tax component.
BALANCE_TOLERANCE = Decimal("0.05")


class InvoiceParty(BaseModel):
    vkn_tckn: str = ""
    title: str = ""
    tax_office: str | None = None
    city: str | None = None
    country: str = "Türkiye"


class InvoiceTaxSubtotal(BaseModel):
    taxable_amount: Decimal
    tax_amount: Decimal
    percent: Decimal
    # Empty means the invoice declared no code. Defaulting these to KDV is how
    # an unidentified tax used to end up in the deductible VAT account.
    tax_category_code: str = ""
    tax_category_name: str = ""


class InvoiceLineItem(BaseModel):
    line_id: str
    item_name: str
    quantity: Decimal
    unit_code: str = "C62"  # Adet
    unit_price: Decimal
    line_extension_amount: Decimal
    kdv_percent: Decimal = Decimal("20.0")
    kdv_amount: Decimal = Decimal("0.0")


class TDHPJournalEntry(BaseModel):
    account_code: str
    account_name: str
    debit_amount: Decimal = Decimal("0.0")   # Borç
    credit_amount: Decimal = Decimal("0.0")  # Alacak
    description: str


class ParsedUBLInvoice(BaseModel):
    invoice_uuid: str
    invoice_number: str  # ETTN / Fatura No (e.g. GIB2024000000001)
    # GİB's own package emits fourteen distinct codes: SATIS, IADE, TEVKIFAT,
    # TEVKIFATIADE, ISTISNA, OZELMATRAH, KOMISYONCU, SARJ, SARJANLIK and the
    # YTB* family. The list is open — treat it as a label, never as direction.
    invoice_type: str = "SATIS"
    profile_id: str = "TICARIFATURA"  # TEMELFATURA, TICARIFATURA, EARSIVFATURA
    # None when the document has no readable date: never a stand-in.
    issue_date: date | None
    # cac:PaymentTerms. None when the document gives none, or gives one we cannot
    # believe. The note is the document's own words: "%50 peşin, %50 45 gün
    # sonra" means this date does not cover the whole amount.
    payment_due_date: date | None = None
    payment_note: str = ""
    # "" = the invoice carries no DocumentCurrencyCode: the row is held, not read as lira.
    currency_code: str = ""
    supplier: InvoiceParty
    customer: InvoiceParty
    line_items: list[InvoiceLineItem] = Field(default_factory=list)
    tax_subtotals: list[InvoiceTaxSubtotal] = Field(default_factory=list)
    line_extension_total: Decimal = Decimal("0.0")  # Mal/Hizmet Toplamı (Matrah)
    tax_exclusive_total: Decimal = Decimal("0.0")
    tax_inclusive_total: Decimal = Decimal("0.0")
    allowance_total: Decimal = Decimal("0.0")        # İskonto Toplamı
    payable_amount: Decimal = Decimal("0.0")         # Ödenecek Tutar
    withholding_tax_amount: Decimal = Decimal("0.0") # Tevkifat Tutarı
    suggested_tdhp_entries: list[TDHPJournalEntry] = Field(default_factory=list)

    # Are we the seller or the buyer? Settled by VKN, never by invoice type.
    direction: InvoiceDirection = "unknown"
    # An IADE (return) invoice: issued by the party who returns the goods, so it
    # undoes what it returns instead of being a sale or a purchase of its own.
    # GİB's rule, and the one assumption separating the two readings; see
    # `economic_direction`.
    is_return: bool = False
    # What the direction keyed on, so a reviewer can judge it rather than trust it.
    direction_basis: str = ""
    # Empty when the invoice was posted. Otherwise it says, in the reviewer's
    # language, why no entry was generated.
    posting_note: str = ""

    @property
    def economic_direction(self) -> InvoiceDirection:
        """What the invoice does to *our* books.

        `direction` says which side of the document we are on (issuer = "sale").
        An ordinary invoice does what its side says. A return is issued by the one
        returning the goods, so the issuer undoes a purchase and the receiver undoes
        a sale: the opposite of the document side.
        """
        if not self.is_return or self.direction == "unknown":
            return self.direction
        return "purchase" if self.direction == "sale" else "sale"

    @property
    def needs_review(self) -> bool:
        """No entry means a human has to decide.

        Either we could not establish which side of the invoice we are on, or
        the components we read do not add up to a balanced journal — in both
        cases the parse is incomplete and posting it would be a guess.
        """
        return not self.suggested_tdhp_entries
