"""The GİB e-Belge XML a PDF carries as an attachment, read INSIDE the PDF child process.

Runs only in the child of `pdf_isolation` (it imports PyMuPDF). Attachments are found the way the PDF
specification declares them, not by a marker the spec makes optional: the catalog's `/Names /EmbeddedFiles`
name tree (and `/Kids` below it), the catalog's `/AF` array, and each file specification's `/EF` stream.
A stream that merely says `/Type /EmbeddedFile` is also taken (what the old reader found), so nothing the old
reader read is lost.

Nothing is decompressed by PyMuPDF (`embfile_get` would inflate a whole stream before any size check could
run): the raw stream is read through `xref_stream_raw` and inflated here with `zlib.decompressobj`, which
stops at the cap while reading. An attachment that is not an e-Belge, or declares a DTD/ENTITY (the same rule
the XML parsers apply, `app.core.xml_safety`), is not returned, so the parent receives bounded, pre-vetted text.

Nothing is skipped silently: an attachment that was declared and could not be read (a filter other than
Flate, a predictor, over the cap, an unreadable stream, an encrypted PDF) is returned in `unread` with the
reason, and `pdf_isolation` turns that into a note on the ingestion result.
"""
from __future__ import annotations

import logging
import re
import zlib
from dataclasses import dataclass, field
from typing import Any

from app.core.xml_safety import UnsafeXMLError, guvenli_mi
from app.parsers.invoice.makbuz import EARSIV_NS

logger = logging.getLogger(__name__)

# The e-Arşiv marker is GİB's XML namespace, compared as text; it is not a URL anything connects to.
_EBELGE_MARKERS = ("urn:oasis:names:specification:ubl:schema:xsd:", EARSIV_NS)
# The upload cap: an attachment cannot legitimately exceed its file.
EMBEDDED_XML_LIMIT = 10 * 1024 * 1024
# Objects looked at while hunting for attachment streams: a file cannot claim millions to keep us busy.
_MAX_OBJECTS = 200_000
_MAX_DECLARED = 200
_MAX_FILES = 20
_MAX_TREE_NODES = 500

_REF = re.compile(r"(\d+)\s+0\s+R")
_EF_STREAMS = re.compile(r"/EF\s*<<[^>]*?/(?:UF|F)\s+(\d+)\s+0\s+R")
_KIDS = re.compile(r"/Kids\s*\[([^\]]*)\]")
_NAMES_ARRAY = re.compile(r"/Names\s*\[")


@dataclass
class Scan:
    """`found`: e-Belge XML texts in PDF order. `unread`: declared attachments that could not be read, with why."""

    found: list[str] = field(default_factory=list)
    unread: list[dict[str, str]] = field(default_factory=list)


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


def _filter_of(doc: Any, xref: int) -> str | None:
    """'' for no filter, 'flate' for FlateDecode alone (no predictor), None for anything else (reported)."""
    kind, value = doc.xref_get_key(xref, "Filter")
    value = value.replace(" ", "")
    if doc.xref_get_key(xref, "DecodeParms")[0] != "null":
        return None   # a predictor or other parameters: not decoded here
    if kind == "null":
        return ""
    if value in ("/FlateDecode", "[/FlateDecode]", "/Fl", "[/Fl]"):
        return "flate"
    return None


def _object_text(doc: Any, xref: int) -> str:
    try:
        return doc.xref_object(xref, compressed=True)
    except Exception:
        return ""


def _key_text(doc: Any, xref: int, key: str) -> str:
    """A key's value as PDF text; an indirect value is followed to its object."""
    try:
        kind, value = doc.xref_get_key(xref, key)
    except Exception:
        return ""
    if kind == "xref":
        ref = _REF.search(value)
        return _object_text(doc, int(ref.group(1))) if ref else ""
    return "" if kind == "null" else value


def _balanced_array(text: str, start: int) -> str:
    """The text of the array that opens at `start` (a `[`), nested arrays and strings included."""
    depth, i, in_str = 0, start, False
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == ")":
                in_str = False
        elif ch == "(":
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start: i + 1]
        i += 1
    return text[start:]


def _tree_texts(doc: Any, root_text: str) -> list[str]:
    """The `/Names [...]` arrays of an EmbeddedFiles name tree, walking `/Kids` (bounded)."""
    arrays: list[str] = []
    todo, seen = [root_text], 0
    while todo and seen < _MAX_TREE_NODES:
        node = todo.pop(0)
        seen += 1
        m = _NAMES_ARRAY.search(node)
        if m:
            arrays.append(_balanced_array(node, m.end() - 1))
        kids = _KIDS.search(node)
        if kids:
            todo.extend(_object_text(doc, int(r)) for r in _REF.findall(kids.group(1)))
    return arrays


def _streams_in(doc: Any, text: str, out: list[int]) -> None:
    """Add the attachment stream xrefs a piece of PDF text points at (file specs inline or by reference)."""
    for m in _EF_STREAMS.finditer(text):
        out.append(int(m.group(1)))
    for ref in _REF.findall(text):
        x = int(ref)
        if x >= doc.xref_length():
            continue
        if doc.xref_is_stream(x):
            out.append(x)
        else:
            for m in _EF_STREAMS.finditer(_object_text(doc, x)):
                out.append(int(m.group(1)))


def declared_streams(doc: Any) -> list[int]:
    """Attachment stream xrefs in order, de-duplicated: name tree, /AF, then any `/Type /EmbeddedFile` object."""
    cat = doc.pdf_catalog()
    found: list[int] = []
    for array in _tree_texts(doc, _key_text(doc, cat, "Names/EmbeddedFiles")):
        _streams_in(doc, array, found)
    _streams_in(doc, _key_text(doc, cat, "AF"), found)
    for xref in range(1, min(doc.xref_length(), _MAX_OBJECTS)):
        if doc.xref_get_key(xref, "Type") == ("name", "/EmbeddedFile"):
            found.append(xref)
    seen: set[int] = set()
    ordered = [x for x in found if not (x in seen or seen.add(x)) and doc.xref_is_stream(x)]
    return ordered[:_MAX_DECLARED]


def _names(doc: Any) -> list[str]:
    try:
        return [str(n) for n in doc.embfile_names()]
    except Exception:
        return []


def _may_be_xml(name: str) -> bool:
    """A declared attachment named like another file type (a picture, a spreadsheet) is not a lost e-Belge."""
    low = name.lower()
    return not name or "." not in low or low.endswith(".xml")


def scan_attachments(file_path: str, limit: int = EMBEDDED_XML_LIMIT) -> Scan:
    """e-Belge XML attachments of a PDF in PDF order (each at most `limit` bytes decompressed), and the
    declared attachments that could not be read."""
    scan = Scan()
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - pinned in requirements
        return scan
    try:
        with pymupdf.open(file_path) as doc:
            if doc.needs_pass:
                scan.unread.append({"name": "", "reason": "encrypted"})
                return scan
            streams = declared_streams(doc)
            names = _names(doc)
            for i, xref in enumerate(streams):
                if len(scan.found) >= _MAX_FILES:
                    break
                name = names[i] if len(names) == len(streams) else ""
                text, reason = _read_stream(doc, xref, limit)
                if reason:
                    logger.info("PDF attachment not read (xref %d): %s", xref, reason)
                    if _may_be_xml(name):
                        scan.unread.append({"name": name, "reason": reason})
                    continue
                if not (text.lstrip().startswith("<") and any(m in text[:4000] for m in _EBELGE_MARKERS)):
                    continue   # read, and it is not an e-Belge: nothing was lost
                try:
                    guvenli_mi(text)
                except UnsafeXMLError:
                    logger.warning("PDF attachment skipped: DTD/ENTITY declared (xref %d)", xref)
                    scan.unread.append({"name": name, "reason": "unsafe_xml"})
                    continue
                scan.found.append(text)
    except Exception as exc:
        logger.warning("PDF ekleri okunamadı: %s", exc)
        scan.unread.append({"name": "", "reason": "unreadable"})
    return scan


def _read_stream(doc: Any, xref: int, limit: int) -> tuple[str, str]:
    """(text, "") or ("", reason): unsupported_filter, too_large, unreadable."""
    mode = _filter_of(doc, xref)
    if mode is None:
        return "", "unsupported_filter"
    try:
        raw = doc.xref_stream_raw(xref)
    except Exception:
        return "", "unreadable"
    if mode == "":
        if len(raw) > limit:
            return "", "too_large"
        data: bytes | None = raw
    else:
        data = bounded_inflate(raw, limit)
        if data is None:
            try:   # over the cap or damaged? a damaged stream inflates to an error even with a big cap
                zlib.decompressobj().decompress(raw, 1)
            except zlib.error:
                return "", "unreadable"
            return "", "too_large"
    return data.decode("utf-8", errors="replace").lstrip("﻿"), ""


def read_ebelge_attachments(file_path: str, limit: int = EMBEDDED_XML_LIMIT) -> list[str]:
    """The e-Belge XML texts only (see `scan_attachments` for the ones that could not be read)."""
    return scan_attachments(file_path, limit).found
