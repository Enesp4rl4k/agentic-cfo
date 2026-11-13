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


def _strip_ledger_prefix(value: str | None) -> str | None:
    if value and str(value).lower().startswith("doc:"):
        return str(value)[4:]
    return value


def canonical_invoice_id(
    document_id: str | None = None,
    invoice_no: str | None = None,
    description: str | None = None,
) -> str | None:
    """Derive a normalized, deterministic invoice document identity.

    Priority (the explicit fields always come before free text: a credit note whose
    description names the invoice it reverses must not take that invoice's identity):
    1. GİB 16-character invoice number in invoice_no or document_id.
    2. Clean invoice number explicitly provided in invoice_no.
    3. document_id, if it is not a raw UUID.
    4. GİB 16-character number found in the description.
    5. Invoice number extracted from a description marker (e.g. '#A-1' -> 'A-1').
    6. Normalized UUID if only an ETTN / UUID is present.
    """
    # "doc:" is the ledger's own key prefix, not part of a document number.
    document_id = _strip_ledger_prefix(document_id)
    invoice_no = _strip_ledger_prefix(invoice_no)

    # 1. Official 16-char GİB format in an explicit field
    for text in (invoice_no, document_id):
        if not text:
            continue
        m = GIB_INVOICE_PATTERN.search(str(text))
        if m:
            return m.group(1).upper()

    # 2. invoice_no explicitly
    if invoice_no:
        clean = str(invoice_no).strip().upper()
        if clean and clean != "NONE" and clean != "N/A" and len(clean) >= 2:
            return clean

    # 3. document_id if not a generic UUID
    if document_id:
        doc_str = str(document_id).strip()
        if not UUID_PATTERN.match(doc_str) and len(doc_str) >= 2:
            return doc_str.upper()

    # 4./5. Only now the free-text description
    if description:
        m = GIB_INVOICE_PATTERN.search(str(description))
        if m:
            return m.group(1).upper()
        m = INVOICE_MARKER_PATTERN.search(str(description))
        if m:
            found = m.group(1).strip().upper()
            if len(found) >= 2:
                return found

    # 6. Fallback to UUID if present
    for text in (document_id, invoice_no, description):
        if not text:
            continue
        m = UUID_PATTERN.search(str(text))
        if m:
            return m.group(1).lower()

    return None
