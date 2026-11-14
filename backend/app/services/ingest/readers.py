"""Reading an uploaded file to text: PDF (and the e-belge XML GİB embeds in it), Excel, CSV, XML.

Moved out of app/agents/data_ingestion.py unchanged (plan v11 A0.3); that module
re-exports what its callers import from it.
"""

from __future__ import annotations

import logging

from app.parsers.invoice.makbuz import EARSIV_NS

logger = logging.getLogger("app.agents.data_ingestion")


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


# The e-Arşiv marker is GİB's XML namespace, compared as text; it is not a URL anything connects to.
_EBELGE_MARKERS = ("urn:oasis:names:specification:ubl:schema:xsd:", EARSIV_NS)


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
