"""e-Defter beratı — bitmiş defterden türetilir, hiçbir değeri uydurulmaz.

A berat is the receipt that makes a ledger filable. GİB's package pairs every
defter part with one, and its schema says what a berat is:

    <xs:element name="berat">
      <xs:sequence>
        <xs:element ref="xbrli:xbrl"/>
        <xs:element name="extensions" minOccurs="0"/>
        <xs:choice>
          <xs:element name="HashValue"/>
          <xs:element ref="ds:SignatureValue"/>
        </xs:choice>
        <xs:element ref="ds:Signature"/>        <!-- zorunlu -->

Read against GİB's own sample pair (`…-Y-000000.xml` / `…-YB-000000.xml`),
every value in the berat is a function of the finished defter:

- `documentInfo` and `entityInformation` are the defter's own, uniqueID
  included (YEV201804000004 on both files).
- The context carries a segment: `gl-bus:numberOfEntries` (journal only) is
  the defter's entryHeader count, `gl-bus:measurableQuantity` its file size
  in MiB to two places (66 097 bytes → 0.06), `gl-cor:uniqueID` a fresh GUID.
- The one `entryHeader` is the tax detail: debit and credit period totals of
  391 / 191 / 600 / 601 / 602, ten lines, zero where nothing moved. In the
  sample every one of the ten equals the sum over the defter.
- The top-level `ds:SignatureValue` is the defter's signature value — that is
  what binds this receipt to that file and no other.

So this module reads the defter and derives, rather than taking the numbers
from wherever they came from upstream. A berat computed from the journal rows
could agree with the journal and disagree with the file that was actually
signed, and the file is what GİB reads.

What it cannot do is sign. The berat's own `ds:Signature` needs the taxpayer's
mali mühür, and an unsigned defter has no signature value to bind to. Both
gaps are carried on the result, as reasons, never collapsed into one flag.
Signing goes through `Signer`: an interface, deliberately without an
implementation here. XAdES over a smart card or HSM is done with the vendor's
library, and cryptography written for this codebase would be the one part of
it nobody could audit.
"""
from __future__ import annotations

import copy
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from lxml import etree

NS = {
    "edefter": "http://www.edefter.gov.tr",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "xades": "http://uri.etsi.org/01903/v1.3.2#",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xbrli": "http://www.xbrl.org/2003/instance",
    "gl-cor": "http://www.xbrl.org/int/gl/cor/2006-10-25",
    "gl-bus": "http://www.xbrl.org/int/gl/bus/2006-10-25",
}

# The tax detail, in GİB's order. Names as the sample writes them: the berat
# states what the account is, independent of how the ledger labelled it.
TAX_DETAIL_ACCOUNTS: tuple[tuple[str, str], ...] = (
    ("391", "Hesaplanan KDV"),
    ("191", "İndirilecek KDV"),
    ("600", "Yurt İçi Satışlar"),
    ("601", "Yurt Dışı Satışlar"),
    ("602", "Diğer Gelirler Hesabı"),
)

DEFTER_NAME = re.compile(r"^(?P<vkn>\d{10,11})-(?P<period>\d{6})-(?P<kind>Y|K)-(?P<part>\d{6})\.xml$")

_MIB = Decimal(1024 * 1024)


class BeratError(ValueError):
    """This defter cannot carry a berat."""


class SignerUnavailable(RuntimeError):
    """No mali mühür is wired to this server."""


class Signer(Protocol):
    """Adds an enveloped XAdES-BES `ds:Signature` as the last child of the root.

    GİB's profile, as the samples use it: one reference with `URI=""` plus the
    SignedProperties reference, c14n `REC-xml-c14n-20010315#WithComments`,
    `rsa-sha256`, `KeyInfo/X509Data/X509Certificate`, and `SigningTime` and
    `SigningCertificate` in the qualifying properties. The key belongs to the
    taxpayer (or to the accountant or software firm holding their
    muvafakatname) — never to this server's operator by default.
    """

    def sign_enveloped(self, xml: bytes) -> bytes: ...


class NoSigner:
    """The signer this server has: none. Says so instead of pretending."""

    def sign_enveloped(self, xml: bytes) -> bytes:
        raise SignerUnavailable(
            "Mali mühür imzalayıcısı yapılandırılmadı — defter ve berat "
            "mükellefin mali mührüyle, onun donanımında imzalanmalı."
        )


@dataclass
class EDefterBerat:
    """A berat, and exactly how far it is from being filable."""

    file_name: str               # VKN-YYYYMM-YB-000000.xml
    xml: bytes
    defter_file_name: str
    kind: str                    # "YB" | "KB"
    unique_id: str
    number_of_entries: int | None    # journal only, as GİB's rules require
    size_mib: str
    tax_detail: dict[tuple[str, str], Decimal]
    defter_signed: bool
    berat_signed: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def missing(self) -> list[str]:
        """What stands between this file and GİB, in the order it has to happen."""
        out: list[str] = []
        if not self.defter_signed:
            out.append(
                "defter mali mühürle imzalanmadı — berat, imzalı defterden "
                "yeniden üretilmeli (imza değeri beratın içine yazılır)"
            )
        if not self.berat_signed:
            out.append("berat mali mühürle imzalanmadı")
        return out

    @property
    def filable(self) -> bool:
        return not self.missing


def _q(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


def _parse(xml: bytes) -> etree._Element:
    # A ledger is data from outside: no entity expansion, no network.
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    try:
        return etree.fromstring(xml, parser)
    except etree.XMLSyntaxError as exc:
        raise BeratError(f"defter XML olarak okunamadı: {exc}") from exc


def signature_value(root: etree._Element) -> str | None:
    """The defter's own signature value, whitespace-normalised, or None."""
    node = root.find(f"{_q('ds', 'Signature')}/{_q('ds', 'SignatureValue')}")
    if node is None or not (node.text or "").strip():
        return None
    return "".join((node.text or "").split())


def size_mib(n_bytes: int) -> str:
    """GİB's measurableQuantity: MiB, two places. 66 097 bytes is 0.06.

    Divided by 10⁶ the sample would read 0.07, so the unit is not a guess.
    """
    return str((Decimal(n_bytes) / _MIB).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _tax_detail(xbrl: etree._Element) -> dict[tuple[str, str], Decimal]:
    totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for detail in xbrl.iter(_q("gl-cor", "entryDetail")):
        main = detail.findtext(f"{_q('gl-cor', 'account')}/{_q('gl-cor', 'accountMainID')}")
        side = detail.findtext(_q("gl-cor", "debitCreditCode"))
        amount = detail.findtext(_q("gl-cor", "amount"))
        if not main or not side or amount is None:
            continue
        main, side = main.strip(), side.strip()
        if side not in ("D", "C"):
            continue
        try:
            totals[(main, side)] += Decimal(amount.strip())
        except ArithmeticError as exc:
            raise BeratError(f"okunamayan tutar {amount!r} ({main})") from exc
    return {
        (code, side): totals.get((code, side), Decimal(0))
        for code, _ in TAX_DETAIL_ACCOUNTS
        for side in ("D", "C")
    }


def _amount_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def build_berat(defter_xml: bytes, *, defter_file_name: str) -> EDefterBerat:
    """Derive the berat for this exact defter file.

    `defter_xml` must be the bytes as they will be filed: the size goes into
    the berat, and so does the signature value if the file is signed.
    """
    m = DEFTER_NAME.match(defter_file_name)
    if not m:
        raise BeratError(
            f"defter dosya adı GİB biçiminde değil (VKN-YYYYAA-Y|K-000000.xml): {defter_file_name!r}"
        )
    kind = m["kind"]

    root = _parse(defter_xml)
    if root.tag != _q("edefter", "defter"):
        raise BeratError(f"kök eleman edefter:defter değil: {root.tag}")
    xbrl_src = root.find(_q("xbrli", "xbrl"))
    if xbrl_src is None:
        raise BeratError("defterde xbrli:xbrl yok")

    entries_type = (xbrl_src.findtext(
        f"{_q('gl-cor', 'accountingEntries')}/{_q('gl-cor', 'documentInfo')}/{_q('gl-cor', 'entriesType')}"
    ) or "").strip()
    expected = "journal" if kind == "Y" else "ledger"
    if entries_type != expected:
        raise BeratError(
            f"dosya adı {kind} diyor, defter entriesType={entries_type!r} — ikisi aynı defteri anlatmalı"
        )
    identifier = (xbrl_src.findtext(
        f"{_q('xbrli', 'context')}/{_q('xbrli', 'entity')}/{_q('xbrli', 'identifier')}"
    ) or "").strip()
    if identifier != m["vkn"]:
        raise BeratError(f"dosya adındaki VKN {m['vkn']} ile defterdeki {identifier!r} farklı")

    sig_value = signature_value(root)
    hash_value = (root.findtext("HashValue") or "").strip()
    if sig_value is None and not hash_value:
        raise BeratError("defterde ne ds:Signature ne HashValue var — şemaya uymuyor")

    # `iso4217:TRY` and `iso639:tr` are QNames in element text. Our own defter
    # declares those prefixes on the root, and a copied subtree keeps only the
    # declarations its tags use — the berat would then fail the schema on the
    # currency unit. Rebuilt with everything in scope at the source instead.
    copied = copy.deepcopy(xbrl_src)
    xbrl = etree.Element(copied.tag, attrib=dict(copied.attrib), nsmap=xbrl_src.nsmap)
    xbrl.extend(list(copied))
    entries = xbrl.find(_q("gl-cor", "accountingEntries"))
    context = xbrl.find(_q("xbrli", "context"))
    if entries is None or context is None:
        raise BeratError("defterde accountingEntries ya da context yok")
    context_id = context.get("id") or "journal_context"
    headers = entries.findall(_q("gl-cor", "entryHeader"))
    entry_count = len(headers)
    tax = _tax_detail(xbrl_src)

    # Which unit is lira: whatever the defter's own amounts point at.
    first_amount = xbrl_src.find(f".//{_q('gl-cor', 'amount')}")
    try_unit = first_amount.get("unitRef") if first_amount is not None else None
    count_unit = None
    for unit in xbrl.findall(_q("xbrli", "unit")):
        measure = (unit.findtext(_q("xbrli", "measure")) or "").strip()
        if measure.startswith("iso4217:") and not try_unit:
            try_unit = unit.get("id")
        if measure == "xbrli:pure":
            count_unit = unit.get("id")
    if not try_unit or not count_unit:
        raise BeratError("defterde para birimi ya da sayı birimi (xbrli:pure) tanımlı değil")

    # ── segment: count, identity, size ──
    entity = context.find(_q("xbrli", "entity"))
    assert entity is not None
    for old in entity.findall(_q("xbrli", "segment")):
        entity.remove(old)
    segment = etree.SubElement(entity, _q("xbrli", "segment"))
    if kind == "Y":
        etree.SubElement(segment, _q("gl-bus", "numberOfEntries"),
                         contextRef=context_id, unitRef=count_unit).text = str(entry_count)
    unique_id = str(uuid.uuid4())
    etree.SubElement(segment, _q("gl-cor", "uniqueID"), contextRef=context_id).text = unique_id
    size = size_mib(len(defter_xml))
    etree.SubElement(segment, _q("gl-bus", "measurableQuantity"),
                     contextRef=context_id, unitRef=count_unit).text = size

    # ── one entryHeader: the tax detail ──
    for h in headers:
        entries.remove(h)
    header = etree.SubElement(entries, _q("gl-cor", "entryHeader"))
    etree.SubElement(header, _q("gl-cor", "qualifierEntry"), contextRef=context_id).text = "standard"
    line = 0
    for code, name in TAX_DETAIL_ACCOUNTS:
        for side in ("D", "C"):
            line += 1
            d = etree.SubElement(header, _q("gl-cor", "entryDetail"))
            etree.SubElement(d, _q("gl-cor", "lineNumber"), contextRef=context_id).text = str(line)
            acc = etree.SubElement(d, _q("gl-cor", "account"))
            etree.SubElement(acc, _q("gl-cor", "accountMainID"), contextRef=context_id).text = code
            etree.SubElement(acc, _q("gl-cor", "accountMainDescription"), contextRef=context_id).text = name
            etree.SubElement(d, _q("gl-cor", "amount"), contextRef=context_id,
                             decimals="INF", unitRef=try_unit).text = _amount_text(tax[(code, side)])
            etree.SubElement(d, _q("gl-cor", "debitCreditCode"), contextRef=context_id).text = side
            info = etree.SubElement(d, _q("gl-cor", "xbrlInfo"))
            etree.SubElement(info, _q("gl-cor", "xbrlInclude"), contextRef=context_id).text = "period_change"

    # ── the berat itself ──
    berat = etree.Element(
        _q("edefter", "berat"),
        nsmap={k: NS[k] for k in ("edefter", "ds", "xades", "xsi")},
    )
    berat.set(_q("xsi", "schemaLocation"), "http://www.edefter.gov.tr ../xsd/edefter.xsd")
    berat.append(xbrl)
    extensions = root.find(_q("edefter", "extensions"))
    if extensions is None:
        extensions = root.find("extensions")
    warnings: list[str] = []
    if extensions is not None and len(extensions):
        # binaryObject is allowed only in the journal itself; a berat that
        # copied it would fail GİB's rules. Nothing else is carried either,
        # and saying so beats dropping it quietly.
        warnings.append("defterdeki extensions berata taşınmadı")

    if sig_value is not None:
        etree.SubElement(berat, _q("ds", "SignatureValue")).text = sig_value
    else:
        # The schema allows it; GİB's rules do not (ds:SignatureValue is
        # required). This is a preview of the berat an unsigned defter would
        # get, and `missing` says why it is only that.
        etree.SubElement(berat, "HashValue").text = hash_value

    xml = etree.tostring(berat, xml_declaration=True, encoding="UTF-8")
    return EDefterBerat(
        file_name=defter_file_name.replace(f"-{kind}-", f"-{kind}B-", 1),
        xml=xml,
        defter_file_name=defter_file_name,
        kind=f"{kind}B",
        unique_id=unique_id,
        number_of_entries=entry_count if kind == "Y" else None,
        size_mib=size,
        tax_detail=tax,
        defter_signed=sig_value is not None,
        warnings=warnings,
    )


def sign_berat(berat: EDefterBerat, signer: Signer) -> EDefterBerat:
    """Hand the berat to a signer, and check it came back with a signature.

    A signer that returns the document unchanged would otherwise produce a
    "signed" berat with nothing in it; the check is on the output, not on the
    signer's say-so.
    """
    if not berat.defter_signed:
        raise BeratError(
            "imzasız defterin beratı imzalanmaz — önce defter imzalanmalı, "
            "berat imzalı defterden yeniden üretilmeli"
        )
    signed = signer.sign_enveloped(berat.xml)
    root = _parse(signed)
    last = root[-1] if len(root) else None
    if last is None or last.tag != _q("ds", "Signature"):
        raise BeratError("imzalayıcı ds:Signature eklemedi — berat imzasız kaldı")
    return EDefterBerat(
        file_name=berat.file_name,
        xml=signed,
        defter_file_name=berat.defter_file_name,
        kind=berat.kind,
        unique_id=berat.unique_id,
        number_of_entries=berat.number_of_entries,
        size_mib=berat.size_mib,
        tax_detail=berat.tax_detail,
        defter_signed=True,
        berat_signed=True,
        warnings=list(berat.warnings),
    )
