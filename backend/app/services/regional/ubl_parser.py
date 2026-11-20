"""GİB UBL-TR 1.2 / 2.1 e-Fatura & e-Arşiv Deep Regional Parser and Batch Ingestion Engine.

Provides:
1. Deep single & batch extraction from XML, Zip archives, and multi-document payloads.
2. Complete tax breakdowns: KDV, Stopaj, Tevkifat, and ÖTV in integer cents (kuruş), zero float math.
3. Due date resolution: checks PaymentTerms and PaymentMeans; falls back to commercial standard
   (default 30 days) with date_is_estimated marking when unstated.
4. Deterministic canonical identity linking (G2 compliance).
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import timedelta
from typing import Any

from app.core.financial import amount_to_cents
from app.core.invoice_identity import canonical_invoice_id
from app.parsers.invoice.ubl_tr import (
    KDV_TAX_CODE,
    NotAnInvoiceError,
    ParsedUBLInvoice,
    UBLTRInvoiceParser,
)

logger = logging.getLogger(__name__)

# GİB standard tax codes
STOPAJ_TAX_CODES = {"0003", "0011", "0022"}  # Gelir/Kurumlar Vergisi Stopajı
OTV_TAX_CODES = {"0071", "0073", "0074", "0075", "0076", "0077"}  # Özel Tüketim Vergisi

# Maximum extracted size for Zip bombs protection (50 MB)
MAX_ZIP_EXTRACTED_BYTES = 50 * 1024 * 1024
MAX_ZIP_FILES = 500


class UBLTaxBreakdown:
    def __init__(
        self,
        matrah_cents: int,
        kdv_cents: int,
        stopaj_cents: int,
        otv_cents: int,
        other_tax_cents: int,
        payable_cents: int,
    ) -> None:
        self.matrah_cents = matrah_cents
        self.kdv_cents = kdv_cents
        self.stopaj_cents = stopaj_cents
        self.otv_cents = otv_cents
        self.other_tax_cents = other_tax_cents
        self.payable_cents = payable_cents

    def to_dict(self) -> dict[str, int]:
        return {
            "matrah_cents": self.matrah_cents,
            "kdv_cents": self.kdv_cents,
            "stopaj_cents": self.stopaj_cents,
            "otv_cents": self.otv_cents,
            "other_tax_cents": self.other_tax_cents,
            "payable_cents": self.payable_cents,
        }


def extract_tax_breakdown(inv: ParsedUBLInvoice) -> UBLTaxBreakdown:
    """Extract strict integer kuruş tax breakdown from parsed UBL invoice."""
    matrah_cents = abs(amount_to_cents(inv.tax_exclusive_total or inv.line_extension_total))
    payable_cents = abs(amount_to_cents(inv.payable_amount or inv.tax_inclusive_total))

    kdv_cents = 0
    otv_cents = 0
    stopaj_cents = 0
    other_cents = 0

    for sub in inv.tax_subtotals:
        code = str(sub.tax_category_code or "").strip()
        amt = abs(amount_to_cents(sub.tax_amount))
        if code == KDV_TAX_CODE:
            kdv_cents += amt
        elif code in OTV_TAX_CODES:
            otv_cents += amt
        elif code in STOPAJ_TAX_CODES:
            stopaj_cents += amt
        else:
            other_cents += amt

    # If withholding tax was separately declared on WithholdingTaxTotal
    if inv.withholding_tax_amount:
        withheld_cents = abs(amount_to_cents(inv.withholding_tax_amount))
        stopaj_cents = max(stopaj_cents, withheld_cents)

    return UBLTaxBreakdown(
        matrah_cents=matrah_cents,
        kdv_cents=kdv_cents,
        stopaj_cents=stopaj_cents,
        otv_cents=otv_cents,
        other_tax_cents=other_cents,
        payable_cents=payable_cents,
    )


def ubl_to_transaction_dict(
    inv: ParsedUBLInvoice,
    *,
    default_due_days: int = 30,
) -> dict[str, Any]:
    """Convert a ParsedUBLInvoice into a standard transaction dictionary with zero data loss."""
    is_income = inv.direction == "sale"
    tx_type = "income" if is_income else "expense"
    category = "revenue" if is_income else "cogs"
    counterparty = inv.customer.title if is_income else (inv.supplier.title or "Tedarikçi")

    taxes = extract_tax_breakdown(inv)
    doc_id = canonical_invoice_id(inv.invoice_uuid, inv.invoice_number, None)

    # Due date calculation
    due_date = inv.payment_due_date
    date_is_estimated = False
    payment_note = inv.payment_note or ""

    if due_date is None and inv.issue_date:
        due_date = inv.issue_date + timedelta(days=default_due_days)
        date_is_estimated = True
        payment_note = (
            f"Belgede vade belirtilmedi; {default_due_days} günlük ticari teamül uygulandı."
        )

    confidence = 0.4 if inv.needs_review else 0.98

    return {
        "amount_cents": taxes.payable_cents or taxes.matrah_cents,
        "kdv_cents": taxes.kdv_cents if taxes.kdv_cents > 0 else None,
        "stopaj_cents": taxes.stopaj_cents if taxes.stopaj_cents > 0 else None,
        "currency": inv.currency_code or "TRY",
        "type": tx_type,
        "category": category,
        "description": f"e-Fatura {inv.invoice_number}: {counterparty}",
        "vendor": counterparty if not is_income else None,
        "counterparty": counterparty,
        "transaction_date": inv.issue_date.isoformat() if inv.issue_date else None,
        "due_date": due_date.isoformat() if due_date else None,
        "date_is_estimated": date_is_estimated,
        "document_id": doc_id or inv.invoice_uuid,
        "payment_note": payment_note or None,
        "confidence": confidence,
        "taxes": taxes.to_dict(),
        "invoice_uuid": inv.invoice_uuid,
        "invoice_number": inv.invoice_number,
        "profile_id": inv.profile_id,
        "invoice_type": inv.invoice_type,
    }


def parse_ubl_zip(
    zip_bytes: bytes,
    *,
    own_vkn: str = "",
) -> list[ParsedUBLInvoice]:
    """Extract and parse all valid UBL-TR invoices from a ZIP archive safely."""
    invoices: list[ParsedUBLInvoice] = []
    total_extracted_bytes = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        infolist = zf.infolist()
        if len(infolist) > MAX_ZIP_FILES:
            raise ValueError(
                f"ZIP arşivi çok fazla dosya içeriyor ({len(infolist)} > {MAX_ZIP_FILES})"
            )

        for info in infolist:
            if info.is_dir():
                continue
            name = info.filename.lower()
            if not name.endswith(".xml"):
                continue

            total_extracted_bytes += info.file_size
            if total_extracted_bytes > MAX_ZIP_EXTRACTED_BYTES:
                raise ValueError(
                    f"ZIP içeriği güvenlik limitini aşıyor ({MAX_ZIP_EXTRACTED_BYTES} bayt)"
                )

            try:
                xml_data = zf.read(info.filename)
                # Quick pre-filter before XML parsing
                if b"<Invoice" not in xml_data and b":Invoice" not in xml_data:
                    continue
                inv = UBLTRInvoiceParser.parse_xml(xml_data, own_vkn=own_vkn)
                invoices.append(inv)
            except (NotAnInvoiceError, Exception) as exc:
                logger.debug("Dosya %s UBL faturası olarak okunamadı: %s", info.filename, exc)
                continue

    return invoices
