"""Canonical invoice and document identity resolution.

Ensures that an invoice arriving from multiple sources (manual file upload, UBL-TR XML,
Paraşüt, Logo Tiger, Netsis, or Open Banking) resolves to the exact same canonical
document identity, solving Plan v10 Gap G2 (cross-source double-counting).
"""

from __future__ import annotations

import re

# GİB (Gelir İdaresi Başkanlığı) 16-character e-Fatura / e-Arşiv pattern:
# 3 alphanumeric characters (series) + 4-digit year + 9-digit sequence
GIB_INVOICE_PATTERN = re.compile(r"\b([A-Za-z0-9]{3}20\d{2}\d{9})\b", re.IGNORECASE)

# Standard UUID pattern (e.g. ETTN)
UUID_PATTERN = re.compile(
    r"\b([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b"
)

# Explicit invoice number markers in Turkish / English accounting descriptions:
# e.g. #A-1, Fatura No: 2024-01, Inv#12345
INVOICE_MARKER_PATTERN = re.compile(
    r"(?:#|(?:\b(?:fatura|irsaliye|invoice|inv|evrak|belge|dekont)(?:\s*(?:no|numarası|nu))?[:\s#\-_]+))([A-Za-z0-9\-_]{2,24})",
    re.IGNORECASE,
)


def canonical_invoice_id(
    document_id: str | None = None,
    invoice_no: str | None = None,
    description: str | None = None,
) -> str | None:
    """Derive a normalized, deterministic invoice document identity.

    Priority:
    1. GİB 16-character invoice number (e.g. ABC2024000000001) in invoice_no, document_id, or description.
    2. Clean alphanumeric invoice number explicitly provided in invoice_no or document_id (if not a raw UUID).
    3. Extracted invoice number from description marker (e.g. '#A-1' -> 'A-1').
    4. Normalized UUID if only an ETTN / UUID is present.
    """
    candidates = [invoice_no, document_id, description]

    # 1. Search for official 16-char GİB format first
    for text in candidates:
        if not text:
            continue
        m = GIB_INVOICE_PATTERN.search(str(text))
        if m:
            return m.group(1).upper()

    # 2. Check invoice_no explicitly
    if invoice_no:
        clean = str(invoice_no).strip().upper()
        if clean and clean != "NONE" and clean != "N/A" and len(clean) >= 2:
            return clean

    # 3. Check document_id if not a generic UUID
    if document_id:
        doc_str = str(document_id).strip()
        # If it's not a raw UUID, use it as the clean document ID
        if not UUID_PATTERN.match(doc_str) and len(doc_str) >= 2:
            return doc_str.upper()

    # 4. Check description for invoice marker like #A-1 or Fatura No: ...
    if description:
        m = INVOICE_MARKER_PATTERN.search(str(description))
        if m:
            found = m.group(1).strip().upper()
            if len(found) >= 2:
                return found

    # 5. Fallback to UUID if present
    for text in (document_id, invoice_no, description):
        if not text:
            continue
        m = UUID_PATTERN.search(str(text))
        if m:
            return m.group(1).lower()

    return None
