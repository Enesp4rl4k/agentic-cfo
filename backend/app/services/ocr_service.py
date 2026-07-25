"""
OCR Service — Multi-strategy PDF text extraction.
==================================================

Extraction strategy (fast → slow, high-quality → fallback):

  1. PyMuPDF text layer      — native text, zero cost, fastest
     → Works for: digital bank statements, CSV exports saved as PDF, Logo Tiger reports
     → Confidence: 0.95 if text length > threshold

  2. PyMuPDF + pdfplumber    — table-aware extraction
     → Works for: structured financial tables in digital PDFs
     → Confidence: 0.90

  3. PyMuPDF → image → Tesseract OCR
     → Works for: scanned invoices, photographed bank statements, fax receipts
     → Confidence: 0.70–0.85 depending on scan quality

  4. LLM vision (GPT-4o/Gemini)  — last resort for complex layouts
     → Works for: hand-written amounts, rotated text, mixed layouts
     → Confidence: 0.60–0.80
     → Not implemented here — falls back to LLM text extraction in data_ingestion.py

Each page gets a per-strategy confidence score. The service returns the
highest-confidence text along with metadata about which strategy succeeded.

Turkish language support:
  - Tesseract language: tur+eng (Turkish + English)
  - Character set includes ğ, ş, ı, ö, ü, ç
  - Amount regex handles Turkish number format: 1.234,56

Usage:
    from app.services.ocr_service import extract_text_from_pdf, OCRResult
    result = extract_text_from_pdf("path/to/invoice.pdf")
    print(result.text)           # extracted text
    print(result.confidence)     # 0.0–1.0
    print(result.strategy_used)  # "native" | "pdfplumber" | "tesseract" | "failed"
    print(result.page_count)     # number of pages
"""
from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Minimum character count to consider native text extraction successful
_MIN_NATIVE_CHARS_PER_PAGE = 50

# Tesseract DPI for rendering (300 DPI is OCR standard)
_TESSERACT_DPI = 300

# Turkish + English language codes for Tesseract
_TESSERACT_LANG = "tur+eng"


@dataclass
class PageResult:
    """OCR result for a single PDF page."""
    page_num: int
    text: str
    confidence: float          # 0.0–1.0
    strategy: str              # "native" | "pdfplumber" | "tesseract"
    char_count: int
    word_count: int
    has_tables: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class OCRResult:
    """Full OCR result for a PDF document."""
    text: str                          # Combined text from all pages
    confidence: float                  # Average confidence across pages
    strategy_used: str                 # Dominant strategy used
    page_count: int
    page_results: list[PageResult]
    file_path: str
    has_tables: bool = False
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_reliable(self) -> bool:
        """True if confidence is above the threshold for structured parsing."""
        return self.confidence >= 0.70

    @property
    def needs_llm_fallback(self) -> bool:
        """True if text quality is too low for rule-based parsing."""
        return self.confidence < 0.55 or len(self.text.strip()) < 100


def _try_native_extraction(page: Any) -> tuple[str, float]:
    """
    Strategy 1: Extract native text layer from PyMuPDF page.
    Returns (text, confidence).
    """
    text = page.get_text("text")
    chars = len(text.strip())
    if chars >= _MIN_NATIVE_CHARS_PER_PAGE:
        # Higher confidence for longer, denser text
        conf = min(0.95, 0.70 + chars / 2000)
        return text, conf
    return text, 0.0  # not enough text — try other strategies


def _try_pdfplumber_extraction(file_path: str, page_num: int) -> tuple[str, float, bool]:
    """
    Strategy 2: Use pdfplumber for better table extraction.
    Returns (text, confidence, has_tables).
    """
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            if page_num >= len(pdf.pages):
                return "", 0.0, False
            pg = pdf.pages[page_num]
            # Extract tables first
            tables = pg.extract_tables()
            has_tables = bool(tables)
            table_text = ""
            if tables:
                for table in tables:
                    for row in table:
                        if row:
                            clean_row = [str(c or "").strip() for c in row]
                            table_text += "\t".join(clean_row) + "\n"

            # Regular text
            plain_text = pg.extract_text() or ""
            combined = (table_text + "\n" + plain_text).strip()
            chars = len(combined)
            if chars >= _MIN_NATIVE_CHARS_PER_PAGE:
                conf = min(0.92, 0.75 + chars / 3000)
                return combined, conf, has_tables
            return combined, 0.0, has_tables
    except ImportError:
        logger.debug("pdfplumber not installed — skipping table extraction")
        return "", 0.0, False
    except Exception as e:
        logger.debug("pdfplumber extraction failed for page %d: %s", page_num, e)
        return "", 0.0, False


def _try_tesseract_ocr(page: Any, dpi: int = _TESSERACT_DPI) -> tuple[str, float]:
    """
    Strategy 3: Render page to image and run Tesseract OCR.
    Returns (text, confidence).

    Requires: pytesseract, Pillow, tesseract binary with tur+eng models.
    """
    try:
        import pytesseract
        from PIL import Image
        import io

        # Render page to pixmap (PNG)
        mat = page.get_pixmap(dpi=dpi)
        img_bytes = mat.tobytes("png")
        image = Image.open(io.BytesIO(img_bytes))

        # Run Tesseract with Turkish + English
        # --oem 3: best engine (LSTM), --psm 6: assume uniform block of text
        custom_config = f"--oem 3 --psm 6 -l {_TESSERACT_LANG}"

        # Get text + confidence data
        ocr_data = pytesseract.image_to_data(
            image,
            config=custom_config,
            output_type=pytesseract.Output.DICT,
        )

        # Extract text and compute mean confidence
        words = []
        confidences = []
        for i, word in enumerate(ocr_data["text"]):
            conf = int(ocr_data["conf"][i])
            if conf > 0 and word.strip():  # -1 means no confidence (header rows)
                words.append(word)
                confidences.append(conf / 100.0)  # normalize to 0–1

        text = " ".join(words)
        avg_conf = statistics.mean(confidences) if confidences else 0.0

        # Penalize if very few words detected
        if len(words) < 10:
            avg_conf *= 0.5

        return text, round(avg_conf, 3)

    except ImportError:
        logger.debug("pytesseract or Pillow not installed — OCR skipped")
        return "", 0.0
    except Exception as e:
        logger.warning("Tesseract OCR failed: %s", e)
        return "", 0.0


def _clean_ocr_text(text: str) -> str:
    """
    Post-process OCR output to fix common Turkish OCR errors.

    Common Tesseract issues with Turkish documents:
    - 'I' instead of 'İ' in all-caps text
    - Extra spaces in numbers: "1 500,00" → "1500,00"
    - 'ı' confused with 'i'
    - Line breaks inside numbers/amounts
    """
    if not text:
        return text

    # Normalize excessive whitespace (but keep line breaks)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Fix number formatting: remove spaces between digits (OCR artifact)
    # "1 500 ,00" → "1500,00"
    text = re.sub(r"(\d) (\d{3})", r"\1\2", text)
    text = re.sub(r"(\d) ,(\d{2})", r"\1,\2", text)

    # Fix common Turkish character confusions in amounts
    # "TL" or "TRY" after amounts
    text = re.sub(r"(\d),(\d{2})\s*T[Ll]", r"\1,\2 TL", text)

    # Remove common OCR noise characters
    text = re.sub(r"[|]{2,}", "", text)
    text = re.sub(r"[-]{4,}", "---", text)

    return text.strip()


def extract_text_from_pdf(file_path: str, force_ocr: bool = False) -> OCRResult:
    """
    Extract text from a PDF using the best available strategy.

    Args:
        file_path: Path to the PDF file
        force_ocr: If True, skip native extraction and always use Tesseract

    Returns:
        OCRResult with text, confidence, and metadata
    """
    path = Path(file_path)
    if not path.exists():
        return OCRResult(
            text="",
            confidence=0.0,
            strategy_used="failed",
            page_count=0,
            page_results=[],
            file_path=file_path,
            warnings=[f"File not found: {file_path}"],
        )

    try:
        import fitz  # PyMuPDF
    except ImportError:
        return OCRResult(
            text="",
            confidence=0.0,
            strategy_used="failed",
            page_count=0,
            page_results=[],
            file_path=file_path,
            warnings=["PyMuPDF (fitz) not installed. Run: pip install pymupdf"],
        )

    page_results: list[PageResult] = []
    all_warnings: list[str] = []
    doc_has_tables = False

    try:
        with fitz.open(file_path) as doc:
            page_count = doc.page_count
            doc_meta = {
                "title": doc.metadata.get("title", ""),
                "author": doc.metadata.get("author", ""),
                "creator": doc.metadata.get("creator", ""),
                "page_count": page_count,
            }

            for page_num in range(page_count):
                page = doc[page_num]
                best_text = ""
                best_conf = 0.0
                best_strategy = "failed"
                page_has_tables = False
                page_warnings: list[str] = []

                if not force_ocr:
                    # Strategy 1: Native text layer
                    native_text, native_conf = _try_native_extraction(page)
                    if native_conf >= 0.70:
                        best_text = native_text
                        best_conf = native_conf
                        best_strategy = "native"

                    # Strategy 2: pdfplumber (better for tables)
                    if best_conf < 0.80:
                        pl_text, pl_conf, has_tables = _try_pdfplumber_extraction(file_path, page_num)
                        if pl_conf > best_conf:
                            best_text = pl_text
                            best_conf = pl_conf
                            best_strategy = "pdfplumber"
                            page_has_tables = has_tables

                # Strategy 3: Tesseract OCR (for scanned pages)
                if force_ocr or best_conf < 0.60:
                    ocr_text, ocr_conf = _try_tesseract_ocr(page)
                    if ocr_conf > best_conf:
                        best_text = _clean_ocr_text(ocr_text)
                        best_conf = ocr_conf
                        best_strategy = "tesseract"
                    elif ocr_conf == 0.0 and best_conf < 0.60:
                        page_warnings.append(
                            f"Page {page_num + 1}: Low confidence text extraction. "
                            "Install pytesseract for better results."
                        )

                if page_has_tables:
                    doc_has_tables = True

                word_count = len(best_text.split()) if best_text else 0
                page_results.append(PageResult(
                    page_num=page_num,
                    text=best_text,
                    confidence=best_conf,
                    strategy=best_strategy,
                    char_count=len(best_text),
                    word_count=word_count,
                    has_tables=page_has_tables,
                    warnings=page_warnings,
                ))
                all_warnings.extend(page_warnings)

    except Exception as e:
        logger.exception("PDF extraction failed for %s", file_path)
        return OCRResult(
            text="",
            confidence=0.0,
            strategy_used="failed",
            page_count=0,
            page_results=[],
            file_path=file_path,
            warnings=[f"PDF extraction error: {e}"],
        )

    # Combine all page texts
    full_text = "\n\n".join(
        f"--- Page {pr.page_num + 1} ---\n{pr.text}"
        for pr in page_results
        if pr.text.strip()
    )

    # Overall confidence = weighted average (longer pages count more)
    if page_results:
        total_chars = sum(pr.char_count for pr in page_results)
        if total_chars > 0:
            weighted_conf = sum(
                pr.confidence * pr.char_count / total_chars
                for pr in page_results
            )
        else:
            weighted_conf = statistics.mean(pr.confidence for pr in page_results)
    else:
        weighted_conf = 0.0

    # Dominant strategy (most pages)
    strategies = [pr.strategy for pr in page_results if pr.strategy != "failed"]
    from collections import Counter
    dominant_strategy = Counter(strategies).most_common(1)[0][0] if strategies else "failed"

    result = OCRResult(
        text=full_text,
        confidence=round(weighted_conf, 3),
        strategy_used=dominant_strategy,
        page_count=len(page_results),
        page_results=page_results,
        file_path=file_path,
        has_tables=doc_has_tables,
        warnings=all_warnings,
        metadata=doc_meta,
    )

    logger.info(
        "PDF extracted: %s | pages=%d | strategy=%s | confidence=%.2f | chars=%d",
        path.name, result.page_count, result.strategy_used,
        result.confidence, len(result.text),
    )

    return result


def extract_invoice_fields(text: str) -> dict[str, Any]:
    """
    Extract structured fields from invoice text using regex patterns.

    Handles both Turkish GİB e-invoices and general invoice formats.
    Returns a dict with extracted fields — all values are None if not found.

    Fields extracted:
    - invoice_no: Fatura numarası
    - invoice_date: Fatura tarihi
    - vendor_name: Tedarikçi adı
    - vendor_tax_id: Vergi kimlik numarası
    - buyer_name: Alıcı adı
    - buyer_tax_id: Alıcı VKN
    - subtotal: Ara toplam (KDV hariç)
    - vat_amount: KDV tutarı
    - total_amount: Genel toplam
    - currency: Para birimi
    - line_items: Kalem listesi
    """
    fields: dict[str, Any] = {
        "invoice_no":    None,
        "invoice_date":  None,
        "vendor_name":   None,
        "vendor_tax_id": None,
        "buyer_name":    None,
        "buyer_tax_id":  None,
        "subtotal":      None,
        "vat_amount":    None,
        "total_amount":  None,
        "currency":      "TRY",
        "line_items":    [],
    }

    if not text:
        return fields

    # ── Invoice number ─────────────────────────────────────────────────────────
    inv_patterns = [
        r"(?:Fatura\s*No|Invoice\s*No|FATURA\s*NO)[:\s#]*([A-Z0-9\-/]+)",
        r"(?:Belge\s*No|Document\s*No)[:\s]*([A-Z0-9\-/]+)",
        r"(?:F\.?\s*No)[:\s]*([A-Z0-9\-/]+)",
    ]
    for pat in inv_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            fields["invoice_no"] = m.group(1).strip()
            break

    # ── Invoice date ───────────────────────────────────────────────────────────
    date_patterns = [
        r"(?:Fatura\s*Tarihi|Invoice\s*Date|TARIH)[:\s]*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
        r"(?:Düzenleme\s*Tarihi)[:\s]*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
        r"Tarih[:\s]*(\d{2}\.\d{2}\.\d{4})",
    ]
    for pat in date_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            fields["invoice_date"] = m.group(1).strip()
            break

    # ── Tax ID (VKN / Vergi Kimlik No) ─────────────────────────────────────────
    vkn_patterns = [
        r"(?:Vergi\s*(?:Kimlik\s*)?No|VKN|Tax\s*ID|T\.?C\.?\s*Vergi)[:\s]*(\d{10,11})",
        r"(?:V\.?K\.?N)[:\s.]*(\d{10})",
    ]
    # First occurrence = vendor, second = buyer
    all_vkn = []
    for pat in vkn_patterns:
        all_vkn.extend(re.findall(pat, text, re.IGNORECASE))

    if all_vkn:
        fields["vendor_tax_id"] = all_vkn[0]
    if len(all_vkn) > 1:
        fields["buyer_tax_id"] = all_vkn[1]

    # ── Amounts (Turkish format: 1.234,56 or 1234.56) ──────────────────────────
    def _parse_tr_amount(raw: str) -> float | None:
        if not raw:
            return None
        # Remove dots used as thousands separators, replace comma decimal
        cleaned = raw.replace(".", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None

    # Turkish amount pattern: matches 7.800,00 or 15.600,00 or 5000,00 or 1300.00
    # Must start with a digit and have at least 4 characters to avoid %20 matches
    _AMT = r"(\d{1,3}(?:[.]\d{3})*(?:[,]\d{2})|\d+[.,]\d{2})"

    # Total amount (most important) — labeled totals
    # Note: "Genel Toplam" > "Toplam" > standalone "TOPLAM"
    # We search for all candidates and pick the largest (most complete total)
    total_patterns = [
        rf"(?:Genel\s*Toplam)[:\s]*(?:TL|TRY|₺)?[\s]*{_AMT}",
        rf"(?:Ödenecek\s*Tutar|Amount\s*Due)[:\s]*(?:TL|TRY|₺)?[\s]*{_AMT}",
        rf"(?:Total\s*Amount)[:\s]*(?:TL|TRY|₺)?[\s]*{_AMT}",
        # Standalone TOPLAM at line start (not "Ara Toplam" or "KDV Toplam")
        rf"^TOPLAM[:\s]*(?:TL|TRY|₺)?[\s]*{_AMT}",
        # "TOPLAM:" anywhere but not preceded by "ARA" or "KDV"
        rf"(?<!ARA\s)(?<!KDV\s)TOPLAM[:\s]+(?:TL|TRY|₺)?[\s]*{_AMT}",
    ]
    _total_candidates: list[float] = []
    for pat in total_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE | re.MULTILINE):
            val = _parse_tr_amount(m.group(1))
            if val and val > 10:
                _total_candidates.append(val)
    if _total_candidates:
        # The largest labeled amount is most likely the grand total
        fields["total_amount"] = max(_total_candidates)

    # VAT amount — labeled KDV amounts
    vat_patterns = [
        rf"(?:Toplam\s*KDV|KDV\s*Tutarı|VAT\s*Amount)[:\s]*(?:TL|TRY|₺)?[\s]*{_AMT}",
        rf"(?:Katma\s*Değer\s*Vergisi)[:\s]*{_AMT}",
        # "KDV (%20):   1.300,00" pattern
        rf"KDV\s*\(%\d+\)\s*[:\s]*{_AMT}",
    ]
    for pat in vat_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = _parse_tr_amount(m.group(1))
            if val and val > 1:
                fields["vat_amount"] = val
                break

    # Subtotal (KDV hariç)
    sub_patterns = [
        rf"(?:Mal\s*Hizmet\s*Tutarı|KDV\s*Hariç\s*Toplam)[:\s]*(?:TL|TRY|₺)?[\s]*{_AMT}",
        rf"(?:Ara\s*Toplam)[:\s]*{_AMT}",
        rf"(?:Subtotal)[:\s]*(?:TL|TRY|₺)?[\s]*{_AMT}",
    ]
    for pat in sub_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = _parse_tr_amount(m.group(1))
            if val and val > 1:
                fields["subtotal"] = val
                break

    # ── Currency ───────────────────────────────────────────────────────────────
    if re.search(r"\bUSD\b|\$", text):
        fields["currency"] = "USD"
    elif re.search(r"\bEUR\b|€", text):
        fields["currency"] = "EUR"
    else:
        fields["currency"] = "TRY"

    return fields
