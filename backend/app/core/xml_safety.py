"""
Kullanıcıdan gelen XML: önce güvenlik, sonra ayrıştırma.

e-Fatura and e-Arşiv arrive as XML a person uploads, so the parser reads a file
a stranger could have written. `xml.etree.ElementTree` does not fetch external
entities, but it does expand internal ones: a few hundred bytes declaring
nested entities ("billion laughs") expands to gigabytes while parsing and takes
the process with it. A stated size limit does not help — the file is small.

Nothing GİB publishes declares a DTD or an entity, so a document that does is
refused before it is parsed, which costs one substring search.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

_DOCTYPE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_XML_BASLANGIC = re.compile(rb"^\s*(\xef\xbb\xbf)?\s*<")


class UnsafeXMLError(ValueError):
    """The document declares a DTD or an entity, or is not XML at all."""


def _as_bytes(veri: str | bytes) -> bytes:
    return veri.encode("utf-8", errors="replace") if isinstance(veri, str) else veri


def xml_gibi_mi(veri: str | bytes) -> bool:
    """Does this start like an XML document?"""
    return bool(_XML_BASLANGIC.match(_as_bytes(veri)[:64]))


def guvenli_mi(veri: str | bytes) -> None:
    """Raise UnsafeXMLError if the document must not be parsed."""
    raw = _as_bytes(veri)
    if not xml_gibi_mi(raw):
        raise UnsafeXMLError("Dosya bir XML belgesi değil.")
    # Only the prologue can carry a DTD, but an entity declared anywhere is a
    # reason to stop, so the whole document is checked.
    if _DOCTYPE.search(raw):
        raise UnsafeXMLError(
            "XML dosyası DTD ya da varlık (ENTITY) tanımı içeriyor; güvenlik nedeniyle okunmadı. "
            "e-Fatura ve e-Arşiv belgeleri bunları içermez."
        )


def parse_xml(veri: str | bytes) -> ET.Element:
    """Parse after the check. The one place user XML becomes a tree."""
    guvenli_mi(veri)
    return ET.fromstring(_as_bytes(veri))
