"""
Turkish Invoice Parser — GİB e-Fatura ve genel PDF fatura formatları.
======================================================================

Desteklenen fatura tipleri:

1. GİB e-Fatura (UBL-TR XML tabanlı, PDF render)
   - Satış faturası / Alış faturası
   - İhracat faturası
   - İade faturası

2. Serbest format / muhasebe programı faturaları
   - Logo Tiger PDF çıktısı
   - Mikro/Netsis fatura raporu
   - Genel muhasebe fatura formatı

3. Zincir mağaza / büyük firmalar
   - Standart tablo bazlı faturalar
   - Çok sayfalı detaylı faturalar

Parser mimarisi:
  - `can_parse()` → hızlı marker tespiti
  - `parse()` → OCR + regex ile ParsedStatement döner
  - `extract_invoice_data()` → yapılandırılmış fatura dict döner

İnvoice → ParsedTransaction dönüşümü:
  - Satış faturası  → income
  - Alış faturası   → expense
  - İade faturası   → income (alış iadesi) veya expense (satış iadesi)
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from app.parsers.base import BankParser, ParsedStatement, ParsedTransaction
from app.services.ocr_service import extract_invoice_fields, extract_text_from_pdf

logger = logging.getLogger(__name__)


# ── GİB e-Fatura marker'ları ───────────────────────────────────────────────────

_GIB_MARKERS = [
    "e-Fatura", "E-FATURA", "GİB", "Gelir İdaresi Başkanlığı",
    "ETTN", "Senaryo:", "TEMELFATURA", "TICARIFATURA",
    "Mal/Hizmet Bedeli", "Vergi Dairesi",
]

# Logo Tiger / Mikro / genel muhasebe fatura marker'ları
_ACCOUNTING_INVOICE_MARKERS = [
    "SATIŞ FATURASI", "ALIŞ FATURASI", "Satış Faturası", "Alış Faturası",
    "PROFORMA FATURA", "Proforma Fatura",
    "Fatura Tarihi", "FATURA TARİHİ",
    "KDV Dahil Toplam", "Genel Toplam",
    "Mal Hizmet Tutarı",
]


def _detect_invoice_type(text: str) -> str:
    """
    Detect invoice type from text content.
    Returns: 'satis' | 'alis' | 'iade' | 'proforma' | 'unknown'
    """
    text_upper = text.upper()
    # iade/credit check first (to avoid matching "satis" inside "satis iadesi")
    if any(k in text_upper for k in ["İADE FATUR", "IADE FATUR", "CREDIT NOTE", "CREDIT MEMO", "IADE EDILEN"]):
        return "iade"
    if any(k in text_upper for k in ["ALIŞ FATUR", "ALIS FATUR", "PURCHASE INVOICE", "ALIM FATUR"]):
        return "alis"
    if any(k in text_upper for k in [
        "SATIŞ FATUR", "SATIS FATUR", "SALE INVOICE",
        # GİB e-Fatura contains "TEMELFATURA" or "TICARIFATURA" which are sales invoices
        "TEMELFATURA", "TICARIFATURA",
        # If it has ETTN (e-Fatura UUID) and no other type indicator, it's a sales invoice
        "ETTN",
    ]):
        return "satis"
    if any(k in text_upper for k in ["PROFORMA", "TEKLIF", "TEKLİF"]):
        return "proforma"
    # Generic "INVOICE" or "FATURA" without qualifier = assume sales
    if any(k in text_upper for k in ["INVOICE", "FATURA"]):
        return "satis"
    return "unknown"


def _invoice_type_to_tx_type(invoice_type: str, context: str = "") -> str:
    """Guess direction from the wording on the page. Last resort only.

    The wording is a poor witness and always has been. "ALIŞ FATURASI" is the
    buyer's phrase and is printed on almost no invoice — a supplier heads its
    own document "FATURA", which this reads as a sale. Worse, the markers that
    promote to `satis` include ETTN, TEMELFATURA and TICARIFATURA, and every
    e-Fatura carries those whichever direction it travelled. Used alone this
    books nearly everything as revenue.

    `_resolve_direction` calls this only when the VKNs settle nothing, and
    marks the result uncertain so it stops at the review gate.
    """
    if invoice_type == "satis":
        return "income"    # We sold something → we receive money
    elif invoice_type == "alis":
        return "expense"   # We bought something → we pay money
    elif invoice_type == "iade":
        # Default: treat as income (we get a refund on purchase)
        # Context override: if caller explicitly signals "satis_iadesi"
        return "expense" if "satis_iade" in context.lower() else "income"
    else:
        return "expense"   # Default: treat unknown as expense


def _normalize_vkn(raw: Any) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits if len(digits) in (10, 11) else ""


def _resolve_direction(
    fields: dict[str, Any], invoice_type: str, own_vkn: str
) -> tuple[str, str, bool]:
    """Which way the money goes: `(tx_type, basis, certain)`.

    Decided by whose VKN is on the document, exactly as the UBL-TR parser does
    it. `extract_invoice_fields` has always pulled `vendor_tax_id` and
    `buyer_tax_id` off the page; nothing read them.
    """
    mine = _normalize_vkn(own_vkn)
    vendor = _normalize_vkn(fields.get("vendor_tax_id"))
    buyer = _normalize_vkn(fields.get("buyer_tax_id"))

    if mine and vendor and buyer and vendor == buyer:
        pass  # same number twice: the extraction, not the invoice, is telling
    elif mine and mine == vendor:
        return "income", f"satıcı VKN {vendor} bizim VKN'mizle eşleşti", True
    elif mine and mine == buyer:
        return "expense", f"alıcı VKN {buyer} bizim VKN'mizle eşleşti", True

    reason = "kendi VKN'miz yapılandırılmamış" if not mine else (
        f"VKN {mine} ne satıcıyla ({vendor or 'yok'}) ne alıcıyla ({buyer or 'yok'}) eşleşti"
    )
    return (
        _invoice_type_to_tx_type(invoice_type),
        f"{reason} — yön belge metninden tahmin edildi ({invoice_type})",
        False,
    )


def _extract_line_items(text: str) -> list[dict[str, Any]]:
    """
    Extract individual line items from invoice text.

    Looks for patterns like:
    1  Yazılım Geliştirme Hizmeti  10 saat  500,00  5.000,00
    2  Danışmanlık                  5 gün    800,00  4.000,00
    """
    items = []

    # Match lines with: quantity, description, unit price, total
    line_pattern = re.compile(
        r"^\s*(?P<qty>\d+(?:[.,]\d+)?)\s+"     # quantity
        r"(?P<desc>[^\d\n]{5,60}?)\s+"          # description
        r"(?P<unit_price>[\d.,]+)\s+"           # unit price
        r"(?P<total>[\d.,]+)\s*$",              # total
        re.MULTILINE,
    )

    for m in line_pattern.finditer(text):
        try:
            qty_str = m.group("qty").replace(",", ".")
            total_str = m.group("total").replace(".", "").replace(",", ".")
            items.append({
                "description": m.group("desc").strip(),
                "quantity": float(qty_str),
                "unit_price": None,  # Not always parseable
                "total": float(total_str),
            })
        except (ValueError, AttributeError):
            continue

    return items[:20]  # Cap at 20 line items


class TurkishInvoiceParser(BankParser):
    """
    Parser for Turkish invoices (GİB e-Fatura and general formats).

    Handles both digital PDFs and OCR-extracted text.
    Each invoice becomes a single ParsedTransaction.
    """
    bank_id = "turkish_invoice"
    bank_display_name = "Turkish Invoice (GİB / Muhasebe)"

    @classmethod
    def can_parse(cls, text: str) -> bool:
        """Return True if text looks like a Turkish invoice."""
        text_upper = text.upper()
        gib_match = sum(1 for m in _GIB_MARKERS if m.upper() in text_upper)
        acc_match = sum(1 for m in _ACCOUNTING_INVOICE_MARKERS if m.upper() in text_upper)

        # Need at least 2 markers (to avoid false positives with bank statements)
        return (gib_match >= 1) or (acc_match >= 2)

    @classmethod
    def can_parse_file(cls, file_path: str) -> tuple[bool, str]:
        """
        Check if a file is an invoice by extracting first page text.
        Returns (can_parse, extracted_text).
        """
        try:
            result = extract_text_from_pdf(file_path)
            # Check only first 2 pages for speed
            first_pages = " ".join(
                pr.text for pr in result.page_results[:2]
            )
            return cls.can_parse(first_pages), result.text
        except Exception:
            return False, ""

    def parse(self, text: str, file_path: str = "") -> ParsedStatement:
        """
        Parse invoice text into a ParsedStatement.

        For a single invoice: returns 1 transaction.
        For a multi-invoice PDF (e.g., invoice list export): returns multiple.
        """
        statement = ParsedStatement(
            bank_name=self.bank_display_name,
            account_number=None,
            statement_period_start=None,
            statement_period_end=None,
        )

        # Extract structured fields using regex patterns
        fields = extract_invoice_fields(text)
        invoice_type = _detect_invoice_type(text)

        own_vkn = ""
        try:
            from app.config import get_settings
            own_vkn = get_settings().gib_vkn
        except Exception:  # pragma: no cover - parser must work without settings
            pass
        tx_type, direction_basis, direction_certain = _resolve_direction(
            fields, invoice_type, own_vkn
        )

        # Amount: prefer total_amount, fall back to subtotal
        amount_float = fields.get("total_amount") or fields.get("subtotal")
        if not amount_float:
            # Try to find any large number as amount
            amounts = re.findall(r"[\d]{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})", text)
            parsed = []
            for a in amounts:
                try:
                    v = float(a.replace(".", "").replace(",", "."))
                    if v > 0:
                        parsed.append(v)
                except ValueError:
                    continue
            amount_float = max(parsed) if parsed else None

        if amount_float is None:
            statement.parse_warnings.append(
                "Could not extract amount from invoice — transaction skipped"
            )
            return statement

        amount_cents = int(amount_float * 100)

        # Parse date
        parsed_date = None
        if fields.get("invoice_date"):
            for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                try:
                    parsed_date = datetime.strptime(
                        fields["invoice_date"], fmt
                    ).replace(tzinfo=UTC)
                    break
                except ValueError:
                    continue

        # Build description
        desc_parts = []
        if fields.get("invoice_no"):
            desc_parts.append(f"Fatura #{fields['invoice_no']}")
        if invoice_type == "satis":
            desc_parts.append("Satış Faturası")
        elif invoice_type == "alis":
            desc_parts.append("Alış Faturası")
        elif invoice_type == "iade":
            desc_parts.append("İade Faturası")

        vendor = fields.get("vendor_name") or fields.get("buyer_name")
        description = " — ".join(desc_parts) if desc_parts else "Fatura"

        # Confidence: higher if we found invoice_no + date + amount
        confidence = 0.70
        if fields.get("invoice_no"):
            confidence += 0.10
        if fields.get("invoice_date"):
            confidence += 0.10
        if fields.get("vendor_tax_id"):
            confidence += 0.05
        confidence = min(0.98, confidence)
        if not direction_certain:
            # Every other field can be right and the entry still lands on the
            # wrong side of the ledger, where it will reconcile perfectly.
            confidence = min(confidence, 0.60)
            statement.parse_warnings.append(
                f"Fatura yönü kesin değil: {direction_basis}"
            )

        tx = ParsedTransaction(
            date=parsed_date or datetime.now(UTC),
            description=description,
            amount_cents=amount_cents,
            tx_type=tx_type,
            currency=fields.get("currency", "TRY"),
            vendor=vendor,
            reference=fields.get("invoice_no"),
            raw_row=text[:500],  # first 500 chars for audit
            confidence=confidence,
            confidence_note=direction_basis if not direction_certain else "",
        )
        statement.transactions.append(tx)

        # Set statement period from invoice date
        if parsed_date:
            statement.statement_period_start = parsed_date
            statement.statement_period_end = parsed_date

        return statement

    def parse_file(self, file_path: str) -> ParsedStatement:
        """
        Parse a PDF invoice file using OCR pipeline.
        Preferred entry point for PDF files.
        """
        try:
            ocr_result = extract_text_from_pdf(file_path)
            if not ocr_result.text.strip():
                empty = ParsedStatement(
                    bank_name=self.bank_display_name,
                    account_number=None,
                    statement_period_start=None,
                    statement_period_end=None,
                )
                empty.parse_warnings.append(
                    f"Could not extract text from {file_path} "
                    f"(confidence={ocr_result.confidence:.0%}, "
                    f"strategy={ocr_result.strategy_used})"
                )
                return empty

            statement = self.parse(ocr_result.text, file_path)

            # Annotate with OCR metadata
            if ocr_result.confidence < 0.70:
                statement.parse_warnings.append(
                    f"Low OCR confidence ({ocr_result.confidence:.0%}) — "
                    f"some fields may be missing or incorrect"
                )

            return statement

        except Exception as exc:
            logger.exception("Invoice parse_file failed for %s: %s", file_path, exc)
            error_stmt = ParsedStatement(
                bank_name=self.bank_display_name,
                account_number=None,
                statement_period_start=None,
                statement_period_end=None,
            )
            error_stmt.parse_warnings.append(f"Parse error: {exc}")
            return error_stmt


class InvoiceBatchParser(TurkishInvoiceParser):
    """
    Parser for multi-invoice PDF exports (e.g., monthly invoice list from muhasebe).

    Splits the document into individual invoices by detecting invoice boundaries.
    Each detected invoice section becomes a separate ParsedTransaction.
    """
    bank_id = "invoice_batch"
    bank_display_name = "Invoice Batch (Multi-Invoice PDF)"

    @classmethod
    def can_parse(cls, text: str) -> bool:
        """True if text contains multiple invoices (>2 invoice markers)."""
        inv_count = len(re.findall(
            r"(?:Fatura\s*No|FATURA\s*NO|Invoice\s*No)[:\s#]*[A-Z0-9\-/]+",
            text, re.IGNORECASE
        ))
        return inv_count >= 2

    def parse(self, text: str, file_path: str = "") -> ParsedStatement:
        """Split multi-invoice text and parse each invoice individually."""
        statement = ParsedStatement(
            bank_name=self.bank_display_name,
            account_number=None,
            statement_period_start=None,
            statement_period_end=None,
        )

        # Split at invoice boundaries:
        # 1. "--- Page N ---" separators (from OCR service page markers)
        # 2. Explicit "SATIŞ/ALIŞ FATURASI" headers
        sections = re.split(
            r"(?:---\s*Page\s*\d+\s*---)",
            text, flags=re.IGNORECASE
        )

        # If page-based split didn't work, try header-based split
        if len(sections) <= 1:
            sections = re.split(
                r"(?=(?:SATIŞ\s*FATURA|ALIŞ\s*FATURA|İADE\s*FATURA|SATIS\s*FATURA|ALIS\s*FATURA))",
                text, flags=re.IGNORECASE
            )

        base_parser = TurkishInvoiceParser()
        dates_seen = []
        for section in sections:
            section = section.strip()
            if len(section) < 30:
                continue

            # Parse even if can_parse is False — batch mode is more lenient
            sub_stmt = base_parser.parse(section, file_path)
            for tx in sub_stmt.transactions:
                statement.transactions.append(tx)
                if tx.date:
                    dates_seen.append(tx.date)
            statement.parse_warnings.extend(sub_stmt.parse_warnings)

        if dates_seen:
            statement.statement_period_start = min(dates_seen)
            statement.statement_period_end = max(dates_seen)

        return statement
