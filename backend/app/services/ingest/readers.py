"""Reading an uploaded file to text: PDF (and the e-belge XML GİB embeds in it), Excel, CSV, XML.

Moved out of app/agents/data_ingestion.py unchanged (plan v11 A0.3); that module
re-exports what its callers import from it.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("app.agents.data_ingestion")


def _read_pdf(file_path: str) -> str:
    """
    Read PDF using multi-strategy OCR pipeline.

    Tries native text extraction first (fast, high confidence).
    Falls back to pdfplumber for table-heavy documents.
    Falls back to Tesseract OCR for scanned/image-based PDFs.

    The whole read happens in the child process of `pdf_isolation`; nothing here opens the file. A refused,
    crashed or timed-out read raises `PdfOkunamadi` with the reason; there is no in-process fallback.

    Returns the best-quality text available, with a warning comment
    prepended if confidence is low (for LLM fallback awareness).
    """
    from app.services.ocr_service import extract_text_from_pdf
    from app.services.pdf_isolation import raise_if_refused

    result = extract_text_from_pdf(file_path)
    raise_if_refused(result)

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


def _read_excel(file_path: str) -> str:
    """The workbook as tab-separated text. Opened in the child process (sheet_isolation); a refusal raises."""
    from app.services.ingest.table import satirlari_oku

    with open(file_path, "rb") as f:
        data = f.read()
    rows: list[str] = []
    for _title, sheet_rows in satirlari_oku(data, "xlsx" if not file_path.lower().endswith(".xls") else "xls"):
        for row in sheet_rows:
            cells = [str(c) if c is not None else "" for c in row]
            if any(cells):
                rows.append("\t".join(cells))
    return "\n".join(rows)


def _read_csv(file_path: str) -> str:
    # UTF-8 first, then Windows-1254: a Turkish bank or ERP export is very often
    # the latter, and reading it as UTF-8 only ended in a generic ingestion error.
    # Size and line length are bounded (sheet_child.check_text_bytes) before the text is decoded.
    from app.config import get_settings
    from app.services.ingest.table import metin_coz
    from app.services.sheet_child import SheetLimit, check_text_bytes
    from app.services.sheet_isolation import SheetOkunamadi, limits_from_settings

    limits = limits_from_settings()
    with open(file_path, "rb") as f:
        data = f.read(limits["max_bytes"] + 1)
    try:
        check_text_bytes(data, limits["max_bytes"], limits["max_csv_line_chars"])
    except SheetLimit as limit:
        params = {"limit_mb": get_settings().max_upload_size_mb, **limit.params}
        raise SheetOkunamadi(limit.code, **params) from None
    return metin_coz(data)


def _pdf_embedded_xml(file_path: str) -> list[str]:
    """XML attachments in a PDF that are GİB e-Belge documents, in PDF order.

    Read by the child process (`pdf_embedded`, size-capped while inflating, DTD/ENTITY refused) in the same
    parse as the text; here is only a lookup of that result. Anything else a PDF carries is not a document.
    """
    from app.services.ocr_service import extract_text_from_pdf

    return list(extract_text_from_pdf(file_path).embedded_xml)


def _read_xml(file_path: str) -> str:
    with open(file_path, encoding="utf-8", newline="") as f:
        return f.read()
