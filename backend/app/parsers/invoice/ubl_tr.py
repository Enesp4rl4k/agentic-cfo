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

from pydantic import BaseModel, Field


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
    invoice_type: str = "SATIS"  # SATIS, IADE, TEVKIFAT, IHRACAT
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


class UBLTRInvoiceParser:
    """Production parser for Turkish Revenue Administration (GİB) UBL-TR XML Invoices."""

    NAMESPACES = {
        "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    }

    @classmethod
    def parse_xml(cls, xml_content: str | bytes) -> ParsedUBLInvoice:
        """Parses UBL-TR XML string or bytes and returns validated structured model."""
        if isinstance(xml_content, str):
            xml_bytes = xml_content.encode("utf-8")
        else:
            xml_bytes = xml_content

        root = ET.fromstring(xml_bytes)

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
            vkn = _find_text(supplier_node, "cac:PartyIdentification/cbc:ID")
            title = _find_text(supplier_node, "cac:PartyName/cbc:Name") or _find_text(
                supplier_node, "cac:PartyLegalEntity/cbc:RegistrationName"
            )
            tax_office = _find_text(supplier_node, "cac:PartyTaxScheme/cac:TaxScheme/cbc:Name")
            supplier = InvoiceParty(vkn_tckn=vkn, title=title, tax_office=tax_office)

        # 3. Customer (Alıcı)
        customer_node = root.find("cac:AccountingCustomerParty/cac:Party", cls.NAMESPACES)
        customer = InvoiceParty()
        if customer_node is not None:
            vkn = _find_text(customer_node, "cac:PartyIdentification/cbc:ID")
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

        # 7. Generate Turkish Uniform Chart of Accounts (TDHP) Journal Entries
        journal_entries = cls._generate_tdhp_entries(
            inv_type=inv_type,
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
        )

    @classmethod
    def _generate_tdhp_entries(
        cls,
        inv_type: str,
        supplier: InvoiceParty,
        customer: InvoiceParty,
        subtotal: Decimal,
        total_kdv: Decimal,
        payable: Decimal,
        inv_no: str,
    ) -> list[TDHPJournalEntry]:
        """Auto-generates TDHP (Tek Düzen Hesap Planı) double-entry bookkeeping records."""
        entries = []
        desc = f"Fatura No: {inv_no} - {supplier.title or customer.title}"

        if "SATIS" in inv_type or "IHRACAT" in inv_type:
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
