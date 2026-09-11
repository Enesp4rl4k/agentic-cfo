"""
Data Ingestion Agent — Skill 1 of 5.

Responsibility: Read the uploaded file (PDF/Excel/CSV), extract raw text
and structured transactions, persist them to the DB.

Parse strategy (fast → slow):
  1. Bank-specific parser (ParserRegistry.detect) — rule-based, free, fast
  2. LLM extraction (_extract_transactions_with_llm) — fallback only

Confidence signals:
- 1.0  → all transactions parsed with vendor + amount + date
- 0.85 → some fields missing but majority parseable
- 0.60 → low-quality OCR or too many unparseable rows → triggers review gate
"""
from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

from app.agents.state import AgentRunConfig, CFOState, SkillResult
from app.config import get_settings
from app.core.turkish import fold
from app.parsers.base import ParsedStatement
from app.parsers.registry import ParserRegistry

logger = logging.getLogger(__name__)

# Category keywords ordered by SPECIFICITY (most specific first wins on tie).
# Each entry: (category, keywords, priority)
# Higher priority = wins when multiple categories match.
_CATEGORY_RULES: list[tuple[str, list[str], int]] = [
    # ── Income ────────────────────────────────────────────────────────────────
    ("revenue",       ["sales invoice", "payment received", "customer payment",
                       "invoice issued", "gelir", "satış", "tahsilat",
                       "sales", "income", "revenue"],                           90),
    ("other_income",  ["other income", "diğer gelir", "grant", "refund received"], 85),
    # ── COGS ──────────────────────────────────────────────────────────────────
    ("cogs",          ["raw material", "hammadde", "goods purchased",
                       "product cost", "manufacturing", "inventory",
                       "mal alımı", "stok alımı"],                              80),
    # ── Payroll ───────────────────────────────────────────────────────────────
    ("salary",        ["salary", "payroll", "maaş", "ücret", "sigorta",
                       "wages", "employee", "social security",
                       "sgk", "personel", "staff"],                             75),
    # ── Tax ── (before "loan" to avoid confusing withholding with bank payment)
    ("tax",           ["kdv", "stopaj", "kurumlar vergisi", "gelir vergisi",
                       "vat", "withholding", "corporate tax", "income tax",
                       "tax payment", "vergi"],                                 73),
    # ── Loan / Finance ────────────────────────────────────────────────────────
    ("loan",          ["kredi ödemesi", "taksit", "loan repayment",
                       "debt payment", "faiz", "interest payment",
                       "installment", "loan", "debt", "credit",
                       "bank loan"],                                             70),
    # ── Rent ──────────────────────────────────────────────────────────────────
    ("rent",          ["kira", "office rent", "rent payment",
                       "lease payment", "rent", "lease"],                       65),
    # ── Utilities ─────────────────────────────────────────────────────────────
    ("utilities",     ["elektrik", "su faturası", "doğalgaz", "fatura",
                       "electricity", "water bill", "gas bill",
                       "internet", "phone", "telecom", "utilities"],           60),
    # ── Marketing ─────────────────────────────────────────────────────────────
    ("marketing",     ["google ads", "meta ads", "facebook ads", "reklam",
                       "advertising", "marketing", "social media",
                       "campaign", "dijital reklam"],                           55),
    # ── Technology ────────────────────────────────────────────────────────────
    ("technology",    ["aws", "azure", "google cloud", "digitalocean",
                       "github", "jira", "figma", "saas",
                       "software license", "server", "cloud",
                       "subscription", "license", "yazılım"],                  50),
    # ── Other expense fallback ────────────────────────────────────────────────
    ("other_expense", [],                                                       0),
]

# Build a fast lookup: category → (keywords, priority)
_CATEGORY_MAP: list[tuple[str, list[str], int]] = [
    (cat, kws, pri) for cat, kws, pri in _CATEGORY_RULES if kws
]

# Public alias for tests / callers that still import CATEGORY_KEYWORDS.
CATEGORY_KEYWORDS: dict[str, list[str]] = {cat: list(kws) for cat, kws, _pri in _CATEGORY_RULES}

# The categories anything downstream knows how to group by. A row carrying
# anything else is invisible to every report that groups on category, and
# nothing complains — so a category read off a file has to be checked against
# this before it is believed.
KNOWN_CATEGORIES: frozenset[str] = frozenset(cat for cat, _kw, _pri in _CATEGORY_RULES)


def _guess_category(description: str) -> str:
    """
    Match description against CATEGORY_RULES using keyword matching.

    When multiple categories match, the one with the highest priority wins.
    This prevents "bank payment" (loan) from beating "salary" (payroll)
    just because it appears first in a naive loop.
    """
    if not description:
        return "other_expense"
    # Folded on both sides: statements write "maas" and "dogalgaz" at least as
    # often as "maaş" and "doğalgaz".
    desc_lower = fold(description)
    best_category = "other_expense"
    best_priority = -1

    for category, keywords, priority in _CATEGORY_MAP:
        if priority <= best_priority:
            continue  # can't beat current winner even if matched
        if any(fold(kw) in desc_lower for kw in keywords):
            best_category = category
            best_priority = priority

    return best_category


def _detect_currency(raw_text: str) -> str:
    """
    Detect the primary currency from document text.
    Returns ISO-4217 code: "TRY", "USD", "EUR", "GBP" etc.
    Defaults to "TRY" for documents that appear to be Turkish.
    """
    text_upper = raw_text[:2000].upper()  # Only scan the header

    # Explicit Turkish lira markers
    if any(marker in text_upper for marker in ["₺", "TL ", " TL\n", "TRY", "TÜRK LİRASI", "TÜRK LIRASI"]):
        return "TRY"
    # Euro markers
    if any(marker in text_upper for marker in ["€", "EUR ", " EUR\n", "EURO"]):
        return "EUR"
    # GBP
    if any(marker in text_upper for marker in ["£", "GBP ", " GBP\n"]):
        return "GBP"
    # USD
    if any(marker in text_upper for marker in ["$", "USD ", " USD\n", "DOLLAR"]):
        return "USD"

    # Turkish document heuristics (common Turkish words in financial docs)
    turkish_markers = ["HESAP", "BANKA", "FATURA", "TARİH", "TUTAR", "BORÇ", "ALACAK"]
    if sum(1 for m in turkish_markers if m in text_upper) >= 2:
        return "TRY"

    return "TRY"  # safe default for this product's target market


def _parse_amount(raw: str) -> int | None:
    """Parse an amount string into the smallest currency unit (cents/kurus).

    Handles:
      - "1000.50"  → 100050
      - "1.000,50" → 100050 (European format: dot=thousands, comma=decimal)
      - "1,000.50" → 100050 (Anglo format: comma=thousands, dot=decimal)
      - "₺1,500"   → 150000 (TRY symbol + Anglo format)
    """
    # Strip currency symbols and whitespace
    s = re.sub(r"[^\d,.]", "", raw)
    if not s:
        return None

    # Detect format: if both separators present, identify which is decimal
    has_dot   = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        # Whichever appears last is the decimal separator
        last_dot   = s.rfind(".")
        last_comma = s.rfind(",")
        if last_comma > last_dot:
            # European format: 1.000,50 → remove dots, replace comma with dot
            s = s.replace(".", "").replace(",", ".")
        else:
            # Anglo format: 1,000.50 → remove commas
            s = s.replace(",", "")
    elif has_comma and not has_dot:
        # Could be decimal comma (1000,50) or thousands comma (1,500)
        # If there are exactly 3 digits after the comma, treat as thousands sep
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) == 3:
            s = s.replace(",", "")  # thousands separator
        else:
            s = s.replace(",", ".")  # decimal separator
    # If only dots, leave as-is

    try:
        return round(float(s) * 100)
    except (ValueError, TypeError):
        return None


def _parse_date(raw: str) -> datetime | None:
    formats = ["%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


async def _extract_transactions_with_llm(
    raw_text: str, settings
) -> list[dict[str, Any]]:
    """
    Use LLM (DeepSeek / OpenAI compatible) to extract structured transactions.
    Returns list of dicts: date, amount, type, description, vendor, confidence.
    """
    from app.platform.model_gateway import LLMUnavailable, complete_text

    system = (
        "You are a financial data extraction specialist. "
        "Extract all financial transactions from the provided document text as a JSON array.\n"
        "For each transaction include:\n"
        "- date: transaction date (DD.MM.YYYY or YYYY-MM-DD)\n"
        "- amount: numeric amount (no currency symbol)\n"
        "- type: 'income' or 'expense'\n"
        "- description: transaction description\n"
        "- vendor: supplier or customer name (null if unknown)\n"
        "- confidence: confidence score 0-1 for this extraction\n\n"
        "Respond with ONLY a valid JSON array. No explanation, no markdown.\n"
        'Example: [{"date": "15.03.2024", "amount": 1500.00, "type": "expense", '
        '"description": "Electricity bill", "vendor": "City Power Co.", "confidence": 0.95}]'
    )
    import json
    try:
        content = (await complete_text(
            task="simple_extraction",
            system_prompt=system,
            prompt=f"Document text:\n\n{raw_text[:8000]}",
            temperature=0.0,
            max_tokens=4096,
        )).strip()
    except LLMUnavailable:
        return []
    if content.startswith("```"):
        content = re.sub(r"^```[a-z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    return json.loads(content)


def _read_pdf(file_path: str) -> str:
    """
    Read PDF using multi-strategy OCR pipeline.

    Tries native text extraction first (fast, high confidence).
    Falls back to pdfplumber for table-heavy documents.
    Falls back to Tesseract OCR for scanned/image-based PDFs.

    Returns the best-quality text available, with a warning comment
    prepended if confidence is low (for LLM fallback awareness).
    """
    try:
        from app.services.ocr_service import extract_text_from_pdf
        result = extract_text_from_pdf(file_path)

        if result.needs_llm_fallback:
            # Prepend low-confidence marker for LLM extraction path
            prefix = (
                f"[OCR_LOW_CONFIDENCE: {result.confidence:.0%} — "
                f"strategy={result.strategy_used}, pages={result.page_count}]\n\n"
            )
            return prefix + result.text

        # Append warnings for partial OCR
        text = result.text
        if result.warnings and result.confidence < 0.85:
            text += "\n\n[OCR_WARNINGS: " + "; ".join(result.warnings[:3]) + "]"

        return text

    except Exception as exc:
        # Graceful fallback to original simple extraction
        logger.warning("OCR service failed (%s), falling back to basic PDF read: %s", file_path, exc)
        import fitz
        text_parts: list[str] = []
        with fitz.open(file_path) as doc:
            for page in doc:
                text_parts.append(page.get_text())
        return "\n".join(text_parts)


def _read_excel(file_path: str) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(file_path, read_only=True, data_only=True)
    rows: list[str] = []
    for sheet in wb.worksheets:
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            if any(cells):
                rows.append("\t".join(cells))
    return "\n".join(rows)


def _read_csv(file_path: str) -> str:
    with open(file_path, encoding="utf-8-sig", newline="") as f:
        return f.read()


def _statement_to_transactions(statement: ParsedStatement) -> list[dict[str, Any]]:
    """Convert ParsedStatement (bank parser output) to the CFO pipeline's transaction format."""
    transactions = []
    for tx in statement.transactions:
        transactions.append({
            "amount_cents": tx.amount_cents,
            "currency": tx.currency,
            "type": tx.tx_type,
            "category": _guess_category(tx.description),
            "description": tx.description,
            "vendor": tx.vendor,
            "transaction_date": tx.date.isoformat() if tx.date else None,
            "raw_text": (
                f"{tx.raw_row}\n[yön] {tx.confidence_note}"
                if tx.confidence_note else tx.raw_row
            ),
            # Structured parsers are high-confidence about the *rows*; they are
            # not automatically right about which way the money went. A parser
            # that knows better says so, and only then does this cap apply.
            "confidence": min(0.95, tx.confidence),
        })
    return transactions


def _try_parse_csv(raw_text: str) -> list[dict[str, Any]] | None:
    """Attempt deterministic CSV parsing if the text is structured CSV."""
    import csv
    import io
    try:
        reader = csv.DictReader(io.StringIO(raw_text))
        if not reader.fieldnames:
            return None
        field_lower = [f.strip().lower() for f in reader.fieldnames if f]
        has_amount = any(f in ("amount", "tutar", "bakiye", "borç", "alacak", "amount_cents") for f in field_lower)
        has_date = any(f in ("date", "tarih", "işlem tarihi", "transaction_date") for f in field_lower)
        if not (has_amount and has_date):
            return None

        transactions = []
        for row in reader:
            if not row or not any(row.values()):
                continue
            r_lower = {k.strip().lower(): (v.strip() if v else "") for k, v in row.items() if k}
            raw_amt = r_lower.get("amount") or r_lower.get("tutar") or r_lower.get("bakiye") or "0"
            raw_dt = r_lower.get("date") or r_lower.get("tarih") or r_lower.get("işlem tarihi") or ""
            raw_desc = r_lower.get("description") or r_lower.get("açıklama") or r_lower.get("detay") or ""
            raw_type = r_lower.get("type") or r_lower.get("tip") or ""
            raw_cat = r_lower.get("category") or r_lower.get("kategori") or ""
            raw_vendor = r_lower.get("vendor") or r_lower.get("tedarikçi") or raw_desc

            amount_cents = _parse_amount(raw_amt)
            if amount_cents is None:
                try:
                    amount_cents = round(float(raw_amt) * 100)
                except Exception:
                    amount_cents = 0

            tx_type = raw_type if raw_type in ("income", "expense") else ("expense" if amount_cents < 0 else "income")
            # A category column is the uploader's word, not ours. "Gıda",
            # "payroll", "sales" — all reasonable to write and none of them
            # something this pipeline groups by, so an unrecognised value is
            # worse than a guessed one: it disappears from every report
            # silently. Keep it only when it is a category we know.
            cat_lower = raw_cat.strip().lower()
            category = (
                cat_lower if cat_lower in KNOWN_CATEGORIES
                else _guess_category(raw_desc or raw_cat)
            )
            parsed_dt = _parse_date(raw_dt)

            transactions.append({
                "amount_cents": abs(amount_cents),
                "currency": "TRY",
                "type": tx_type,
                "category": category,
                "description": raw_desc,
                "vendor": raw_vendor,
                "transaction_date": parsed_dt.isoformat() if parsed_dt else None,
                "raw_text": str(row),
                "confidence": 0.95,
            })
        return transactions if transactions else None
    except Exception:
        return None


_EBELGE_MARKERS = ("urn:oasis:names:specification:ubl:schema:xsd:", "http://earsiv.efatura.gov.tr")
_EMBEDDED_XML_LIMIT = 10 * 1024 * 1024   # the upload cap; an attachment cannot exceed its file


def _pdf_embedded_xml(file_path: str) -> list[str]:
    """XML attachments in a PDF that are GİB e-Belge documents, in PDF order.

    Only attachments that declare a UBL or e-Arşiv namespace are returned;
    anything else a PDF carries (an XSLT, an image) is not a document.
    """
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - pinned in requirements
        return []
    found: list[str] = []
    try:
        with pymupdf.open(file_path) as doc:
            for i in range(doc.embfile_count()):
                data = doc.embfile_get(i)
                if not data or len(data) > _EMBEDDED_XML_LIMIT:
                    continue
                text = data.decode("utf-8", errors="replace").lstrip("﻿")
                if text.lstrip().startswith("<") and any(m in text[:4000] for m in _EBELGE_MARKERS):
                    found.append(text)
    except Exception as exc:
        logger.warning("PDF ekleri okunamadı (%s): %s", file_path, exc)
    return found


def _read_xml(file_path: str) -> str:
    with open(file_path, encoding="utf-8", newline="") as f:
        return f.read()


def _try_parse_ubl_xml(raw_text: str) -> list[dict[str, Any]] | None:
    """Parse Turkish e-Fatura / e-Arşiv UBL-TR 1.2 XML into CFO transactions.

    Whether an invoice is income or expense is read from the direction the
    parser establishes by VKN, not from `InvoiceTypeCode`. The old mapping
    (`invoice_type in ("SATIS", "IHRACAT", "KOMISYON")`) treated one of GİB's
    fourteen real codes as income and thirteen as expense, and two of the three
    codes it listed are not codes GİB issues.

    When the direction cannot be established the rows are still returned — a
    withheld invoice is not a discarded one — but at a confidence that keeps
    them the other side of the review gate.
    """
    # A substring decides only whether to look; the root element decides what
    # the document is. An earlier version sent anything containing the word
    # "CreditNote" to the receipt parser — which GİB's own e-Arşiv sale does,
    # in a reference — and the invoice was dropped as "not a receipt".
    if not any(m in raw_text for m in ("<Invoice", ":Invoice", "CreditNote", "eArsivVeri")):
        return None
    try:
        from app.config import get_settings
        from app.core.financial import amount_to_cents
        from app.parsers.invoice.ubl_tr import NotAnInvoiceError, UBLTRInvoiceParser

        try:
            inv = UBLTRInvoiceParser.parse_xml(
                raw_text, own_vkn=get_settings().gib_vkn
            )
        except NotAnInvoiceError as exc:
            # e-Müstahsil is a UBL CreditNote and e-SMM is e-Arşiv data; both
            # used to stop here as "not an invoice, skipped". e-İrsaliye,
            # uygulama yanıtı and the like are neither and are still skipped —
            # they carry no monetary total and once parsed into a 0,00 TL sale.
            logger.info("UBL belgesi fatura değil, makbuz olarak deneniyor: %s", exc)
            return _try_parse_makbuz(raw_text)

        is_income = inv.direction == "sale"
        tx_type = "income" if is_income else "expense"
        # "sales" is not in _CATEGORY_MAP; the vocabulary's income term is
        # "revenue". Every other producer uses _guess_category, which can
        # only return a known category — this line was the one that could
        # not, so nothing downstream recognised what it emitted.
        category = "revenue" if is_income else "cogs"
        counterparty = (
            inv.customer.title if is_income else (inv.supplier.title or "Tedarikçi")
        )

        amount_cents = amount_to_cents(
            inv.payable_amount or inv.tax_inclusive_total or inv.line_extension_total
        )

        # Direction settled by VKN is as certain as a structured parser gets.
        # `needs_review` covers more than direction: a foreign currency with no
        # rate, or tax components that do not reach the invoice's own total,
        # also mean we did not understand the document well enough to book it.
        confidence = 0.4 if inv.needs_review else 0.95
        note = f" | Yön: {inv.direction} ({inv.direction_basis})"
        if inv.posting_note:
            note += f" | Kayıt üretilmedi: {inv.posting_note}"

        # The invoice states its KDV; carry it so the journal splits it rather
        # than holding the entry as "no rate in the source". Only when nothing
        # else is in play: withheld KDV and other taxes (ÖTV…) change which
        # part of the payable the KDV is, and the engine does not model them.
        from decimal import Decimal

        from app.parsers.invoice.ubl_tr import KDV_TAX_CODE

        only_kdv = all(
            t.tax_category_code == KDV_TAX_CODE for t in inv.tax_subtotals if t.tax_amount
        )
        kdv_cents = (
            abs(amount_to_cents(sum(
                (t.tax_amount for t in inv.tax_subtotals if t.tax_category_code == KDV_TAX_CODE),
                Decimal("0"),
            )))
            if not inv.needs_review and only_kdv and not inv.withholding_tax_amount
            else None
        )

        return [{
            "amount_cents": abs(amount_cents),
            "kdv_cents": kdv_cents,
            "currency": inv.currency_code or "TRY",
            "type": tx_type,
            "category": category,
            "description": f"e-Fatura {inv.invoice_number}: {counterparty}",
            "vendor": counterparty if not is_income else None,
            "transaction_date": inv.issue_date.isoformat() if inv.issue_date else None,
            "raw_text": (
                f"UUID: {inv.invoice_uuid} | No: {inv.invoice_number} "
                f"| Type: {inv.invoice_type}{note}"
            ),
            "confidence": confidence,
        }]
    except Exception as exc:
        # Was logged at debug. A NameError in this function turned every
        # uploaded e-Fatura into "no transactions" with nothing in the log at
        # the default level — the test for it is the only reason it was seen.
        logger.warning("UBL-TR ayrıştırılamadı, fatura atlandı: %s", exc, exc_info=True)
        return None


def _try_parse_makbuz(raw_text: str) -> list[dict[str, Any]] | None:
    """e-Müstahsil / e-SMM into one CFO transaction, held when not understood.

    Same contract as the invoice path: the side we are on is settled by VKN,
    and a receipt the parser could not post still comes back as a row — at a
    confidence that keeps it behind the review gate, with the reason attached.
    """
    try:
        from app.config import get_settings
        from app.core.financial import amount_to_cents
        from app.parsers.invoice.makbuz import NotAMakbuzError, parse_makbuz

        try:
            m = parse_makbuz(raw_text, own_vkn=get_settings().gib_vkn)
        except NotAMakbuzError as exc:
            logger.info("e-Arşiv belgesi müstahsil/SMM değil, atlandı: %s", exc)
            return None

        is_income = m.direction == "sale"
        label = "e-Müstahsil" if m.kind == "mustahsil" else "e-SMM"
        if is_income:
            category = "revenue"
        else:
            category = "cogs" if m.kind == "mustahsil" else "other_expense"
        other = m.payer if is_income else m.payee
        note = f" | Yön: {m.direction} ({m.direction_basis})"
        if m.stopaj:
            note += f" | Stopaj: {m.stopaj}"
        if m.posting_note:
            note += f" | Kayıt üretilmedi: {m.posting_note}"

        who = other.title or other.vkn_tckn or "karşı taraf"
        what = f" — {m.items[0]}" if m.items else ""
        understood = bool(m.suggested_tdhp_entries)
        return [{
            # What changes hands. Stopaj is paid to the tax office by the payer,
            # so it is not part of this movement.
            "amount_cents": abs(amount_to_cents(m.payable or m.gross)),
            # The document states both; the journal needs both to book the fee
            # at its gross and the tax where it belongs. Carried only when the
            # receipt was understood — otherwise the entry is held, not split.
            "kdv_cents": abs(amount_to_cents(m.kdv)) if understood else None,
            "stopaj_cents": abs(amount_to_cents(m.stopaj)) if understood else None,
            "currency": m.currency or "TRY",
            "type": "income" if is_income else "expense",
            "category": category,
            "description": f"{label} {m.number}: {who}{what}",
            # e-SMM data carries the professional's VKN but not their name.
            "vendor": None if is_income else who,
            "transaction_date": m.issue_date.isoformat() if m.issue_date else None,
            "raw_text": f"UUID: {m.uuid} | No: {m.number} | Tür: {label}{note}",
            "confidence": 0.4 if m.needs_review else 0.95,
        }]
    except Exception as exc:
        logger.warning("e-Müstahsil/e-SMM ayrıştırılamadı: %s", exc)
        return None


async def run_data_ingestion(
    state: CFOState, config: AgentRunConfig
) -> SkillResult:
    """
    Data Ingestion Skill.
    done_when: state['transactions'] is a non-empty list.

    Strategy:
      1. Read raw text from file (PDF / Excel / CSV)
      2. Try ParserRegistry (bank-specific rule-based parsers) — fast, free
      3. If no bank match → fall back to LLM extraction
    """
    settings = get_settings()
    file_path = state.get("file_path", "")
    file_type = state.get("file_type", "")

    if not os.path.exists(file_path):
        return SkillResult(ok=False, detail=f"File not found: {file_path}", halt=True)

    try:
        if file_type == "pdf":
            raw_text = _read_pdf(file_path)
        elif file_type in ("xlsx", "xls"):
            raw_text = _read_excel(file_path)
        elif file_type == "csv":
            raw_text = _read_csv(file_path)
        elif file_type == "xml":
            raw_text = _read_xml(file_path)
        else:
            return SkillResult(ok=False, detail=f"Unsupported file type: {file_type}", halt=True)

        if not raw_text.strip():
            return SkillResult(
                ok=False,
                detail="Could not extract any text from the file.",
                needs_review=True,
                confidence=0.0,
            )

        # ── Strategy 1.2: an e-Belge carried inside a PDF ────────────────────
        # GİB delivers e-SMM as a PAdES-signed PDF with the receipt data
        # attached as XML (e-Arşiv Kılavuzu §7), and integrators ship e-Fatura
        # and e-Arşiv the same way. The page text of such a PDF is a rendering;
        # the attachment is the document. Reading only the text meant the data
        # GİB made the payer's copy of record was never looked at.
        if file_type == "pdf":
            embedded = _pdf_embedded_xml(file_path)
            if embedded:
                raw_text = embedded[0]

        # ── Strategy 1.25: GİB UBL-TR 1.2 / 2.1 e-Fatura / e-Arşiv XML Parser ──
        if (
            file_type == "xml"
            or "<Invoice" in raw_text
            or ":Invoice" in raw_text
            or "CreditNote" in raw_text
            or "eArsivVeri" in raw_text
        ):
            ubl_txs = _try_parse_ubl_xml(raw_text)
            if ubl_txs:
                # The rows carry their own confidence — an invoice whose
                # direction could not be settled by VKN is not a certainty, and
                # this branch used to assert 1.0 regardless, which is precisely
                # how a backwards posting would reach the ledger unreviewed.
                ubl_confidence = min(float(t.get("confidence", 0.8)) for t in ubl_txs)
                logger.info(
                    "job=%s — UBL-TR XML parser parsed %d invoice transactions (conf=%.2f)",
                    state.get("job_id"), len(ubl_txs), ubl_confidence,
                )
                return SkillResult(
                    ok=True,
                    patch={"raw_text": raw_text, "transactions": ubl_txs},
                    confidence=ubl_confidence,
                    needs_review=ubl_confidence < 0.80,
                    detail=(
                        f"Parsed {len(ubl_txs)} transactions via GİB UBL-TR XML "
                        f"parser (confidence={ubl_confidence:.2f})"
                    ),
                )

        # ── Strategy 1: Bank-specific rule-based parser ────────────────────
        detected_bank = ParserRegistry.detect(raw_text)
        if detected_bank is not None:
            logger.info(
                "job=%s — using bank parser: %s",
                state.get("job_id"), detected_bank.bank_display_name,
            )
            statement: ParsedStatement = detected_bank().parse(raw_text, file_path)
            transactions = _statement_to_transactions(statement)

            if transactions:
                parseable = sum(
                    1 for tx in transactions
                    if tx["amount_cents"] > 0 and tx["transaction_date"]
                )
                overall_confidence = 0.95 if parseable / len(transactions) >= 0.8 else 0.75
                # A well-formed row booked on the wrong side is still wrong, so
                # the rows' own doubt caps the file's confidence.
                overall_confidence = min(
                    overall_confidence,
                    min(float(tx.get("confidence", 0.95)) for tx in transactions),
                )
                detail = (
                    f"[{detected_bank.bank_display_name}] Parsed {len(transactions)} transactions "
                    f"({parseable} fully parsed, confidence={overall_confidence:.2f})"
                )
                if statement.parse_warnings:
                    logger.warning(
                        "job=%s — parser warnings: %s",
                        state.get("job_id"), statement.parse_warnings,
                    )
                return SkillResult(
                    ok=True,
                    patch={"raw_text": raw_text, "transactions": transactions},
                    confidence=overall_confidence,
                    needs_review=overall_confidence < 0.80,
                    detail=detail,
                )
        # ── Strategy 1.5: Generic CSV parser (deterministic, fast, no LLM) ─
        if file_type == "csv" or "," in raw_text[:500] or ";" in raw_text[:500]:
            csv_txs = _try_parse_csv(raw_text)
            if csv_txs:
                # Confidence must reflect data quality: rows with an unparseable
                # date or a zero amount are only partially usable. A file where
                # most dates failed to parse should NOT sail through the gate.
                well_formed = sum(
                    1 for tx in csv_txs
                    if tx.get("transaction_date") and tx.get("amount_cents", 0) > 0
                )
                ratio = well_formed / len(csv_txs)
                overall_confidence = 0.95 if ratio >= 0.9 else (0.78 if ratio >= 0.6 else 0.5)
                logger.info(
                    "job=%s — deterministic CSV parser: %d transactions, %d well-formed (conf=%.2f)",
                    state.get("job_id"), len(csv_txs), well_formed, overall_confidence,
                )
                return SkillResult(
                    ok=True,
                    patch={"raw_text": raw_text, "transactions": csv_txs},
                    confidence=overall_confidence,
                    needs_review=overall_confidence < 0.80,
                    detail=(
                        f"Parsed {len(csv_txs)} transactions via CSV parser "
                        f"({well_formed} well-formed, confidence={overall_confidence:.2f})"
                    ),
                )

        # ── Strategy 2: LLM fallback ───────────────────────────────────────
        logger.info("job=%s — no bank or CSV parser matched, using LLM extraction", state.get("job_id"))
        raw_transactions = await _extract_transactions_with_llm(raw_text, settings)

        if not raw_transactions:
            return SkillResult(
                ok=False,
                detail="LLM returned no transactions from the document.",
                needs_review=True,
                confidence=0.4,
            )

        # Detect currency once from the document header — avoids per-transaction guessing
        detected_currency = _detect_currency(raw_text)
        logger.info(
            "job=%s — detected currency: %s (LLM fallback path)",
            state.get("job_id"), detected_currency,
        )

        transactions = []
        confidences: list[float] = []

        for t in raw_transactions:
            amount_cents = _parse_amount(str(t.get("amount", "")))
            parsed_date = _parse_date(str(t.get("date", "")))
            conf = float(t.get("confidence", 0.8))
            confidences.append(conf)

            # Use per-transaction currency if LLM provided one, else fall back to detected
            tx_currency = t.get("currency") or detected_currency

            transactions.append({
                "amount_cents": amount_cents or 0,
                "currency": tx_currency,
                "type": t.get("type", "expense"),
                "category": _guess_category(t.get("description", "")),
                "description": t.get("description", ""),
                "vendor": t.get("vendor"),
                "transaction_date": parsed_date.isoformat() if parsed_date else None,
                "raw_text": str(t),
                "confidence": conf,
            })

        overall_confidence = min(confidences) if confidences else 0.5
        parseable = sum(
            1 for tx in transactions
            if tx["amount_cents"] > 0 and tx["transaction_date"]
        )
        parse_ratio = parseable / len(transactions) if transactions else 0

        if parse_ratio < 0.5:
            overall_confidence = min(overall_confidence, 0.55)
        elif parse_ratio < 0.8:
            overall_confidence = min(overall_confidence, 0.75)

        return SkillResult(
            ok=True,
            patch={"raw_text": raw_text, "transactions": transactions},
            confidence=overall_confidence,
            needs_review=overall_confidence < 0.80,
            detail=(
                f"[LLM] Extracted {len(transactions)} transactions "
                f"({parseable} fully parsed, confidence={overall_confidence:.2f})"
            ),
        )

    except Exception as exc:
        logger.exception("Data ingestion failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Ingestion error: {exc}", halt=True)
