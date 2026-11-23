"""The GİB e-Belge XML a PDF carries as an attachment, read INSIDE the PDF child process.

Runs only in the child of `pdf_isolation` (it imports PyMuPDF). Nothing is decompressed by PyMuPDF
(`embfile_get` would inflate a whole stream before any size check could run): the raw stream is read and
inflated here with `zlib.decompressobj`, which stops at the cap while reading. A stream with any other
filter is skipped, as is an attachment that is not an e-Belge or declares a DTD/ENTITY (the same rule the
XML parsers apply, `app.core.xml_safety`), so the parent receives bounded, pre-vetted text.
"""
from __future__ import annotations

import logging
import zlib

from app.core.xml_safety import UnsafeXMLError, guvenli_mi
from app.parsers.invoice.makbuz import EARSIV_NS

logger = logging.getLogger(__name__)

# The e-Arşiv marker is GİB's XML namespace, compared as text; it is not a URL anything connects to.
_EBELGE_MARKERS = ("urn:oasis:names:specification:ubl:schema:xsd:", EARSIV_NS)
# The upload cap: an attachment cannot legitimately exceed its file.
EMBEDDED_XML_LIMIT = 10 * 1024 * 1024
# Objects looked at while hunting for attachment streams: a file cannot claim millions to keep us busy.
_MAX_OBJECTS = 200_000
_MAX_FILES = 20


def bounded_inflate(raw: bytes, limit: int = EMBEDDED_XML_LIMIT) -> bytes | None:
    """Inflate at most `limit` bytes; None when the stream would be larger, or is not valid deflate."""
    inflater = zlib.decompressobj()
    try:
        out = inflater.decompress(raw, limit + 1)
    except zlib.error:
        return None
    if len(out) > limit or inflater.unconsumed_tail:
        return None
    return out


def _filter_of(doc, xref: int) -> str | None:
    """'' for no filter, 'flate' for FlateDecode alone, None for anything else (skipped)."""
    kind, value = doc.xref_get_key(xref, "Filter")
    value = value.replace(" ", "")
    if kind == "null":
        return ""
    if value in ("/FlateDecode", "[/FlateDecode]", "/Fl", "[/Fl]"):
        return "flate"
    return None


def read_ebelge_attachments(file_path: str, limit: int = EMBEDDED_XML_LIMIT) -> list[str]:
    """e-Belge XML attachments of a PDF in PDF order, each at most `limit` bytes decompressed."""
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - pinned in requirements
        return []
    found: list[str] = []
    try:
        with pymupdf.open(file_path) as doc:
            for xref in range(1, min(doc.xref_length(), _MAX_OBJECTS)):
                if len(found) >= _MAX_FILES:
                    break
                if doc.xref_get_key(xref, "Type") != ("name", "/EmbeddedFile"):
                    continue
                mode = _filter_of(doc, xref)
                if mode is None:
                    logger.info("PDF attachment skipped: filter is not Flate (xref %d)", xref)
                    continue
                try:
                    raw = doc.xref_stream_raw(xref)
                except Exception as exc:  # one broken object does not hide the others
                    logger.info("PDF attachment stream unreadable (xref %d): %s", xref, exc)
                    continue
                data = raw[: limit + 1] if mode == "" else bounded_inflate(raw, limit)
                if not data or len(data) > limit:
                    continue
                text = data.decode("utf-8", errors="replace").lstrip("﻿")
                if not (text.lstrip().startswith("<") and any(m in text[:4000] for m in _EBELGE_MARKERS)):
                    continue
                try:
                    guvenli_mi(text)
                except UnsafeXMLError:
                    logger.warning("PDF attachment skipped: DTD/ENTITY declared (xref %d)", xref)
                    continue
                found.append(text)
    except Exception as exc:
        logger.warning("PDF ekleri okunamadı: %s", exc)
    return found
