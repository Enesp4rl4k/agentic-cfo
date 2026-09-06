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
    # Empty when the invoice was posted. Otherwise it says, in the reviewer's
    # language, why no entry was generated.
    posting_note: str = ""

    @property
    def needs_review(self) -> bool:
        """No entry means a human has to decide.

        Either we could not establish which side of the invoice we are on, or
        the components we read do not add up to a balanced journal — in both
        cases the parse is incomplete and posting it would be a guess.
        """
        return not self.suggested_tdhp_entries


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

        allowance_total = Decimal("0.0")
        if monetary_node is not None:
            line_ext_total = _to_decimal(_find_text(monetary_node, "cbc:LineExtensionAmount"))
            tax_excl_total = _to_decimal(_find_text(monetary_node, "cbc:TaxExclusiveAmount"))
            tax_incl_total = _to_decimal(_find_text(monetary_node, "cbc:TaxInclusiveAmount"))
            payable_amount = _to_decimal(_find_text(monetary_node, "cbc:PayableAmount"))
            # İskonto. Declared on the model since the beginning and never read,
            # so it was always 0,00 whatever the invoice said.
            allowance_total = _to_decimal(
                _find_text(monetary_node, "cbc:AllowanceTotalAmount")
            )

        # 5. Tax Subtotals — identified by TaxTypeCode, not by display name.
        #
        # GİB writes the same tax under four different names in its own package:
        # "KDV", "Katma Değer Vergisi", "GERÇEK USULDE KATMA DEĞER VERGİSİ", and
        # once with no name at all. Matching on `"KDV" in name` caught 21 of the
        # 26 KDV subtotals and silently dropped five, which is why several of
        # GİB's own invoices produced a journal short by exactly the VAT.
        # 0015 is KDV; 0071 is ÖTV; the rest are other taxes we must not merge.
        tax_subtotals = []
        for t_sub in root.findall("cac:TaxTotal/cac:TaxSubtotal", cls.NAMESPACES):
            tax_subtotals.append(
                InvoiceTaxSubtotal(
                    taxable_amount=_to_decimal(_find_text(t_sub, "cbc:TaxableAmount")),
                    tax_amount=_to_decimal(_find_text(t_sub, "cbc:TaxAmount")),
                    percent=_to_decimal(_find_text(t_sub, "cbc:Percent")),
                    tax_category_code=_find_text(
                        t_sub, "cac:TaxCategory/cac:TaxScheme/cbc:TaxTypeCode"
                    ),
                    tax_category_name=_find_text(
                        t_sub, "cac:TaxCategory/cac:TaxScheme/cbc:Name"
                    ),
                )
            )

        total_kdv = sum(
            (t.tax_amount for t in tax_subtotals if t.tax_category_code == KDV_TAX_CODE),
            Decimal("0"),
        )
        # Every other declared tax — ÖTV and friends. On a sale we owe it; on a
        # purchase it is part of what the goods cost us. Either way it is not
        # deductible VAT and must never be added to 191.
        other_taxes = sum(
            (
                t.tax_amount
                for t in tax_subtotals
                if t.tax_category_code and t.tax_category_code != KDV_TAX_CODE
            ),
            Decimal("0"),
        )
        # A subtotal with no code at all is a tax we cannot classify. Counting it
        # as KDV was the old default and would put someone else's tax into the
        # deductible account.
        unclassified_tax = sum(
            (t.tax_amount for t in tax_subtotals if not t.tax_category_code),
            Decimal("0"),
        )

        # Tevkifat lives in its own element, not in TaxTotal. The field existed
        # on the model from the start and was assigned a hardcoded 0.0, so every
        # withheld invoice reported no withholding and its journal came out
        # short by exactly the amount withheld.
        withholding_tax = sum(
            (
                _to_decimal(_find_text(w, "cbc:TaxAmount"))
                for w in root.findall("cac:WithholdingTaxTotal", cls.NAMESPACES)
            ),
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
        journal_entries, posting_note = cls._generate_tdhp_entries(
            direction=direction,
            supplier=supplier,
            customer=customer,
            tax_exclusive=tax_excl_total or line_ext_total,
            tax_inclusive=tax_incl_total,
            total_kdv=total_kdv,
            other_taxes=other_taxes,
            unclassified_tax=unclassified_tax,
            withheld=withholding_tax,
            payable=payable_amount or tax_incl_total,
            currency=currency,
            profile_id=profile_id,
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
            allowance_total=allowance_total,
            suggested_tdhp_entries=journal_entries,
            direction=direction,
            direction_basis=basis,
            posting_note=posting_note,
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
        *,
        direction: InvoiceDirection,
        supplier: InvoiceParty,
        customer: InvoiceParty,
        tax_exclusive: Decimal,
        tax_inclusive: Decimal,
        total_kdv: Decimal,
        other_taxes: Decimal,
        unclassified_tax: Decimal,
        withheld: Decimal,
        payable: Decimal,
        currency: str,
        profile_id: str,
        inv_no: str,
    ) -> tuple[list[TDHPJournalEntry], str]:
        """TDHP (Tek Düzen Hesap Planı) double-entry records, or a reason there are none.

        Returns `(entries, note)`. An empty list is never a silent outcome: the
        note says what stopped us, and the caller holds the invoice for a human.

        The one rule this function will not bend is that the entry must balance
        against the invoice's own figures. It would be easy to derive revenue as
        whatever makes the two sides equal — and that would turn every tax we
        failed to read into revenue, reconciled perfectly and wrong. So each
        component is read from the document, the entry is built from them, and
        the balance is then checked rather than assumed.
        """
        if direction == "unknown":
            return [], "fatura yönü belirlenemedi — kayıt üretilmedi"
        if payable <= 0:
            return [], "ödenecek tutar yok — kayıt üretilmedi"
        if unclassified_tax > 0:
            # A subtotal with no TaxTypeCode is a tax we cannot name. It used to
            # default to KDV, which puts somebody else's tax into 191.
            return [], (
                f"sınıflandırılamayan vergi ({unclassified_tax}) — "
                "TaxTypeCode yok, kayıt üretilmedi"
            )
        if currency and currency.upper() != "TRY":
            # UBL carries the rate in cac:PricingExchangeRate when there is one;
            # GİB's own foreign-currency samples omit it. Booking the foreign
            # figure into a TRY ledger is the exact error the integer-kuruş rule
            # exists to prevent, and it is invisible afterwards.
            return [], (
                f"fatura {currency} cinsinden ve kur bilgisi yok — "
                "TRY deftere kursuz işlenemez"
            )

        # Özel matrah and the like: KDV is declared but already inside the price,
        # so the inclusive and exclusive totals are equal. Adding it on top
        # double-counted it and broke the balance by exactly the VAT.
        kdv_inside_price = total_kdv > 0 and tax_inclusive == tax_exclusive
        net = tax_exclusive - total_kdv if kdv_inside_price else tax_exclusive

        entries: list[TDHPJournalEntry] = []
        desc = f"Fatura No: {inv_no} - {supplier.title or customer.title}"

        def add(code: str, name: str, *, debit: Decimal = Decimal("0.0"),
                credit: Decimal = Decimal("0.0")) -> None:
            if debit == 0 and credit == 0:
                return
            entries.append(
                TDHPJournalEntry(
                    account_code=code,
                    account_name=name,
                    debit_amount=debit,
                    credit_amount=credit,
                    description=desc,
                )
            )

        if direction == "sale":
            add("120.01", f"Alıcılar - {customer.title or 'Müşteri'}", debit=payable)
            # An export is 601, not 600. GİB marks it on the profile, so this is
            # read rather than inferred from the currency or the customer.
            if profile_id.upper() == "IHRACAT":
                add("601.01", "Yurtdışı Satışlar", credit=net)
            else:
                add("600.01", "Yurtiçi Satışlar Geliri", credit=net)
            # Tevkifatta KDV'nin tevkif edilen kısmını alıcı doğrudan beyan eder;
            # satıcı yalnızca kalanı hesaplanan KDV olarak taşır.
            add("391.01", "Hesaplanan KDV", credit=total_kdv - withheld)
            add("360.01", "Ödenecek Vergi ve Fonlar (ÖTV vb.)", credit=other_taxes)
        else:
            # Other taxes are part of what the goods cost us — never deductible.
            add(
                "770.01",
                "Genel Yönetim Giderleri (Alış/Hizmet)",
                debit=net + other_taxes,
            )
            add("191.01", "İndirilecek KDV", debit=total_kdv)
            add("320.01", f"Satıcılar - {supplier.title or 'Tedarikçi'}", credit=payable)
            # Tevkif edilen KDV, 2 no'lu beyanname ile sorumlu sıfatıyla ödenir.
            add("360.02", "Ödenecek Vergi ve Fonlar (Tevkifat)", credit=withheld)

        debit_total = sum((e.debit_amount for e in entries), Decimal("0"))
        credit_total = sum((e.credit_amount for e in entries), Decimal("0"))
        gap = abs(debit_total - credit_total)
        if gap > BALANCE_TOLERANCE:
            return [], (
                f"yevmiye dengelenmedi (borç {debit_total} / alacak {credit_total}, "
                f"fark {gap}) — faturanın bileşenleri kendi toplamıyla tutmuyor"
            )

        return entries, ""
