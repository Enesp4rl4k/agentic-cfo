"""
GİB (Gelir İdaresi Başkanlığı) e-Fatura / e-Arşiv UBL-TR 2.1 XML Parser.
Parses official Turkish Electronic Invoices (UBL-TR standard), extracts tax breakdowns (KDV, Tevkifat, Stopaj),
parties (VKN/TCKN), monetary totals, and suggests Turkish Uniform Chart of Accounts (TDHP) journal entries.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
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
    tax_category_code: str = "0015"  # KDV
    tax_category_name: str = "KDV"


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
    issue_date: date
    currency_code: str = "TRY"
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
    # What the direction keyed on, so a reviewer can judge it rather than trust it.
    direction_basis: str = ""

    @property
    def needs_review(self) -> bool:
        """An invoice whose side we cannot establish must not post itself."""
        return self.direction == "unknown"


class UBLTRInvoiceParser:
    """Production parser for Turkish Revenue Administration (GİB) UBL-TR XML Invoices."""

    NAMESPACES = {
        "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    }

    @classmethod
    def _party_identifier(cls, party_node: ET.Element) -> str:
        """The party's VKN/TCKN, chosen by schemeID rather than by position.

        `cac:PartyIdentification` is a repeating element and its order is not
        fixed. GİB's own HKS samples list MERSISNO before VKN, so taking the
        first one read a MERSİS number as the tax number. The same slot also
        carries PLAKA, SAYACNO, TESISATNO and SEVKIYATNO — a licence plate is
        not something to decide the direction of a ledger with.
        """
        fallback = ""
        for node in party_node.findall(
            "cac:PartyIdentification/cbc:ID", cls.NAMESPACES
        ):
            value = (node.text or "").strip()
            if not value:
                continue
            scheme = (node.get("schemeID") or "").upper()
            if scheme in ("VKN", "TCKN"):
                return value
            if not scheme and not fallback:
                # An unlabelled identifier is all a foreign customer has.
                fallback = value
        return fallback

    @staticmethod
    def normalize_vkn(raw: str | None) -> str:
        """VKN (10 hane) / TCKN (11 hane), noktalama ve boşluklardan arındırılmış.

        Anything of another length is not an identifier and must not be compared:
        a truncated or padded number that happened to match would decide which
        side of the ledger an invoice posts to.
        """
        digits = re.sub(r"\D", "", raw or "")
        return digits if len(digits) in (10, 11) else ""

    @classmethod
    def parse_xml(
        cls, xml_content: str | bytes, *, own_vkn: str = ""
    ) -> ParsedUBLInvoice:
        """Parse a UBL-TR invoice.

        `own_vkn` is the VKN of the organisation whose books these are. Without
        it the invoice can still be read, but its direction stays "unknown" and
        no journal entry is generated — posting to a guessed side is worse than
        posting nothing, and the confidence gate is there to hold it.

        Raises `NotAnInvoiceError` for well-formed UBL that is not an Invoice.
        """
        if isinstance(xml_content, str):
            xml_bytes = xml_content.encode("utf-8")
        else:
            xml_bytes = xml_content

        root = ET.fromstring(xml_bytes)
        if root.tag != INVOICE_ROOT:
            raise NotAnInvoiceError(root.tag)

        # Helper to find text safely
        def _find_text(element, xpath: str, default: str = "") -> str:
            node = element.find(xpath, cls.NAMESPACES)
            return node.text.strip() if node is not None and node.text else default

        def _to_decimal(val_str: str) -> Decimal:
            try:
                clean = re.sub(r"[^\d.-]", "", val_str.replace(",", "."))
                return Decimal(clean) if clean else Decimal("0.0")
            except Exception:
                return Decimal("0.0")

        # 1. Header Information
        uuid_str = _find_text(root, "cbc:UUID", "N/A")
        inv_no = _find_text(root, "cbc:ID", "N/A")
        inv_type = _find_text(root, "cbc:InvoiceTypeCode", "SATIS").upper()
        profile_id = _find_text(root, "cbc:ProfileID", "TICARIFATURA")
        date_str = _find_text(root, "cbc:IssueDate", "2024-01-01")
        currency = _find_text(root, "cbc:DocumentCurrencyCode", "TRY")

        try:
            issue_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            issue_date = date.today()

        # 2. Supplier (Satıcı)
        supplier_node = root.find("cac:AccountingSupplierParty/cac:Party", cls.NAMESPACES)
        supplier = InvoiceParty()
        if supplier_node is not None:
            vkn = cls._party_identifier(supplier_node)
            title = _find_text(supplier_node, "cac:PartyName/cbc:Name") or _find_text(
                supplier_node, "cac:PartyLegalEntity/cbc:RegistrationName"
            )
            tax_office = _find_text(supplier_node, "cac:PartyTaxScheme/cac:TaxScheme/cbc:Name")
            supplier = InvoiceParty(vkn_tckn=vkn, title=title, tax_office=tax_office)

        # 3. Customer (Alıcı)
        customer_node = root.find("cac:AccountingCustomerParty/cac:Party", cls.NAMESPACES)
        customer = InvoiceParty()
        if customer_node is not None:
            vkn = cls._party_identifier(customer_node)
            title = _find_text(customer_node, "cac:PartyName/cbc:Name") or _find_text(
                customer_node, "cac:PartyLegalEntity/cbc:RegistrationName"
            )
            tax_office = _find_text(customer_node, "cac:PartyTaxScheme/cac:TaxScheme/cbc:Name")
            customer = InvoiceParty(vkn_tckn=vkn, title=title, tax_office=tax_office)

        # 4. Monetary Totals
        monetary_node = root.find("cac:LegalMonetaryTotal", cls.NAMESPACES)
        line_ext_total = Decimal("0.0")
        tax_excl_total = Decimal("0.0")
        tax_incl_total = Decimal("0.0")
        payable_amount = Decimal("0.0")

        if monetary_node is not None:
            line_ext_total = _to_decimal(_find_text(monetary_node, "cbc:LineExtensionAmount"))
            tax_excl_total = _to_decimal(_find_text(monetary_node, "cbc:TaxExclusiveAmount"))
            tax_incl_total = _to_decimal(_find_text(monetary_node, "cbc:TaxInclusiveAmount"))
            payable_amount = _to_decimal(_find_text(monetary_node, "cbc:PayableAmount"))

        # 5. Tax Subtotals (KDV & Tevkifat)
        tax_subtotals = []
        withholding_tax = Decimal("0.0")
        for t_sub in root.findall("cac:TaxTotal/cac:TaxSubtotal", cls.NAMESPACES):
            taxable = _to_decimal(_find_text(t_sub, "cbc:TaxableAmount"))
            tax_amt = _to_decimal(_find_text(t_sub, "cbc:TaxAmount"))
            pct = _to_decimal(_find_text(t_sub, "cbc:Percent"))
            cat_name = _find_text(t_sub, "cac:TaxCategory/cac:TaxScheme/cbc:Name", "KDV")
            tax_subtotals.append(
                InvoiceTaxSubtotal(
                    taxable_amount=taxable,
                    tax_amount=tax_amt,
                    percent=pct,
                    tax_category_name=cat_name,
                )
            )

        # Total KDV amount
        total_kdv = sum(
            (t.tax_amount for t in tax_subtotals if "KDV" in t.tax_category_name.upper()),
            Decimal("0"),
        )

        # 6. Invoice Lines
        lines = []
        for l_node in root.findall("cac:InvoiceLine", cls.NAMESPACES):
            line_id = _find_text(l_node, "cbc:ID")
            item_name = _find_text(l_node, "cac:Item/cbc:Name", "Hizmet/Ürün")
            qty = _to_decimal(_find_text(l_node, "cbc:InvoicedQuantity", "1"))
            price = _to_decimal(_find_text(l_node, "cac:Price/cbc:PriceAmount"))
            line_ext = _to_decimal(_find_text(l_node, "cbc:LineExtensionAmount"))
            lines.append(
                InvoiceLineItem(
                    line_id=line_id,
                    item_name=item_name,
                    quantity=qty,
                    unit_price=price,
                    line_extension_amount=line_ext,
                )
            )

        # 7. Which side are we on?
        direction, basis = cls._resolve_direction(own_vkn, supplier, customer)

        # 8. Generate Turkish Uniform Chart of Accounts (TDHP) Journal Entries
        journal_entries = cls._generate_tdhp_entries(
            direction=direction,
            supplier=supplier,
            customer=customer,
            subtotal=tax_excl_total or line_ext_total,
            total_kdv=total_kdv,
            payable=payable_amount or tax_incl_total,
            inv_no=inv_no,
        )

        return ParsedUBLInvoice(
            invoice_uuid=uuid_str,
            invoice_number=inv_no,
            invoice_type=inv_type,
            profile_id=profile_id,
            issue_date=issue_date,
            currency_code=currency,
            supplier=supplier,
            customer=customer,
            line_items=lines,
            tax_subtotals=tax_subtotals,
            line_extension_total=line_ext_total,
            tax_exclusive_total=tax_excl_total,
            tax_inclusive_total=tax_incl_total,
            payable_amount=payable_amount,
            withholding_tax_amount=withholding_tax,
            suggested_tdhp_entries=journal_entries,
            direction=direction,
            direction_basis=basis,
        )

    @classmethod
    def _resolve_direction(
        cls, own_vkn: str, supplier: InvoiceParty, customer: InvoiceParty
    ) -> tuple[InvoiceDirection, str]:
        """Sale or purchase, decided by whose VKN issued the invoice.

        This used to be read off `InvoiceTypeCode`, with everything outside
        {SATIS, IHRACAT} treated as a purchase. Of the fourteen codes GİB
        actually emits, that made one an income and thirteen an expense —
        YTBSATIS, a sale by name, was booked as a cost. Two of the three codes
        in the income list (IHRACAT, KOMISYON) are not codes GİB issues at all;
        exports carry ISTISNA and the broker case is KOMISYONCU.
        """
        mine = cls.normalize_vkn(own_vkn)
        if not mine:
            return "unknown", "kendi VKN'miz yapılandırılmamış (GIB_VKN)"

        sup = cls.normalize_vkn(supplier.vkn_tckn)
        cus = cls.normalize_vkn(customer.vkn_tckn)
        if sup and sup == cus:
            # Both sides carry the same VKN, so neither side is ours in
            # particular. Branch transfers look like this, and so do malformed
            # invoices; either way the direction is not knowable from the VKN.
            return "unknown", f"satıcı ve alıcı aynı VKN'yi taşıyor ({sup})"
        if mine == sup:
            return "sale", f"satıcı VKN {sup} bizim VKN'mizle eşleşti"
        if mine == cus:
            return "purchase", f"alıcı VKN {cus} bizim VKN'mizle eşleşti"
        return "unknown", (
            f"VKN {mine} ne satıcıyla ({sup or 'yok'}) ne alıcıyla ({cus or 'yok'}) eşleşti"
        )

    @classmethod
    def _generate_tdhp_entries(
        cls,
        direction: InvoiceDirection,
        supplier: InvoiceParty,
        customer: InvoiceParty,
        subtotal: Decimal,
        total_kdv: Decimal,
        payable: Decimal,
        inv_no: str,
    ) -> list[TDHPJournalEntry]:
        """Auto-generates TDHP (Tek Düzen Hesap Planı) double-entry bookkeeping records.

        Returns nothing when the direction is unknown. A journal line posted to
        the wrong side is not a smaller error than a missing one — it is the
        same money booked backwards, and it reconciles perfectly while doing so.
        """
        if direction == "unknown":
            return []

        entries = []
        desc = f"Fatura No: {inv_no} - {supplier.title or customer.title}"

        if direction == "sale":
            # Sales Invoice (Satış Faturası)
            # Borç: 120 Alıcılar
            entries.append(
                TDHPJournalEntry(
                    account_code="120.01",
                    account_name=f"Alıcılar - {customer.title or 'Müşteri'}",
                    debit_amount=payable,
                    credit_amount=Decimal("0.0"),
                    description=desc,
                )
            )
            # Alacak: 600 Yurtiçi Satışlar
            entries.append(
                TDHPJournalEntry(
                    account_code="600.01",
                    account_name="Yurtiçi Satışlar Geliri",
                    debit_amount=Decimal("0.0"),
                    credit_amount=subtotal,
                    description=desc,
                )
            )
            # Alacak: 391 Hesaplanan KDV
            if total_kdv > 0:
                entries.append(
                    TDHPJournalEntry(
                        account_code="391.01",
                        account_name="Hesaplanan KDV",
                        debit_amount=Decimal("0.0"),
                        credit_amount=total_kdv,
                        description=desc,
                    )
                )
        else:
            # Purchase / Expense Invoice (Alış / Gider Faturası)
            # Borç: 770 Genel Yönetim Giderleri (veya 153 Ticari Mallar)
            entries.append(
                TDHPJournalEntry(
                    account_code="770.01",
                    account_name="Genel Yönetim Giderleri (Alış/Hizmet)",
                    debit_amount=subtotal,
                    credit_amount=Decimal("0.0"),
                    description=desc,
                )
            )
            # Borç: 191 İndirilecek KDV
            if total_kdv > 0:
                entries.append(
                    TDHPJournalEntry(
                        account_code="191.01",
                        account_name="İndirilecek KDV",
                        debit_amount=total_kdv,
                        credit_amount=Decimal("0.0"),
                        description=desc,
                    )
                )
            # Alacak: 320 Satıcılar
            entries.append(
                TDHPJournalEntry(
                    account_code="320.01",
                    account_name=f"Satıcılar - {supplier.title or 'Tedarikçi'}",
                    debit_amount=Decimal("0.0"),
                    credit_amount=payable,
                    description=desc,
                )
            )

        return entries
