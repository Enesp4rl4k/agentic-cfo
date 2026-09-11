"""GİB e-Defter web servisi — üç işlem, SOAP 1.2, WS-Security imzalı.

From GİB's "e-Defter Uygulaması Web Servis Kılavuzu" (v1.7, Mayıs 2024):

- `sendDocumentFile(Attachment{fileName, binaryData})` → a string,
  "[paketAdı] paketi işleme alındı".
- `getBatchStatus(paketID)` → `durum{durumAciklama, durumKodu, paketKimligi}`,
  the newest attempt for that id.
- `receiveDocumentFile(PaketID)` → `Attachment`, the GİB-approved berat.

Document style, targetNamespace `http://webservice.edefter.gib.gov.tr/`,
children unqualified (`<web:getBatchStatus><paketID>…`, exactly as the
guide's sample message). The Timestamp and Body must be signed with WS-Security
(BinarySecurityToken X509PKIPathv1 by DirectReference, exc-c14n, rsa-sha256)
using a mali mühür or a qualified certificate — the taxpayer's own, or an
approved software firm's.

That signature is the one thing this module does not do, for the same reason
the berat module does not sign: it goes through `SoapSigner`, and with no
signer this client refuses before it opens a connection. There is no code path
that sends an unsigned envelope, and no default that points at production —
the environment is `test` unless someone writes `prod`.

Not verified against the live service: whether it insists on MTOM for the
attachment. Error 107 ("datahandler") hints at a JAX-WS DataHandler; inline
base64 is what the schema type allows and what this sends. The first real call
against the test endpoint settles it.
"""
from __future__ import annotations

import base64
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
from lxml import etree

ENDPOINTS = {
    "test": "https://edeftertest.gib.gov.tr/edefter/services/EDefterWsPort",
    "prod": "https://edefter.gib.gov.tr/edefter/services/EDefterWsPort",
}

SOAP12 = "http://www.w3.org/2003/05/soap-envelope"
WEB = "http://webservice.edefter.gib.gov.tr/"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"

PAKET_ID = re.compile(r"^\d{10,11}-\d{6}-(Y|K|YB|KB)-\d{6}$")

# The guide's table, verbatim in meaning. A code is a stable thing to branch
# on; the prose is for the person reading the screen.
ERROR_CODES: dict[str, str] = {
    "101": "Kullanıcı bulunamadı",
    "102": "Kullanıcının e-Defter rolü yok",
    "103": "Attachment boş (null)",
    "104": "Paket adı boş",
    "105": "Paket içeriği boş",
    "106": "Paket azami boyutu aşıyor",
    "107": "Paket okunamadı (datahandler)",
    "108": "Paket adı geçersiz",
    "109": "SOAP imzası sahibinin bu paketi gönderme yetkisi yok",
    "110": "GİB veritabanı hatası",
    "111": "Bu paket daha önce yüklenmiş",
    "112": "GİB disk hatası",
    "113": "GİB kuyruk hatası",
    "114": "Mükellef şu anda paket yükleyemez",
    "203": "GİB veritabanı hatası",
    "204": "Bu paket için işlenmiş berat yok",
    "205": "SOAP imzası sahibinin bu beratı indirme yetkisi yok",
    "206": "GİB disk hatası",
    "303": "GİB veritabanı hatası",
    "304": "Bu paket bulunamadı",
    "305": "SOAP imzası sahibinin bu paketi sorgulama yetkisi yok",
}

# Worth retrying later: the fault is GİB's infrastructure, not the package.
TRANSIENT = frozenset({"110", "112", "113", "203", "206", "303"})


class GibWsNotConfigured(RuntimeError):
    """No WS-Security signer: nothing will be sent."""


class GibWsError(RuntimeError):
    def __init__(self, code: str | None, message: str, raw: str = "") -> None:
        self.code = code
        self.raw = raw
        self.transient = code in TRANSIENT if code else False
        known = ERROR_CODES.get(code or "", "")
        super().__init__(f"[{code or '?'}] {known or message}")


class SoapSigner(Protocol):
    """Signs wsu:Timestamp and soap:Body into the wsse:Security header.

    Must add the BinarySecurityToken (X509PKIPathv1) and reference it by
    DirectReference; exc-c14n; rsa-sha256. Returns the full envelope.
    """

    def sign_envelope(self, envelope: bytes) -> bytes: ...


@dataclass
class BatchStatus:
    paket_id: str
    code: str
    description: str


@dataclass
class ReceivedFile:
    file_name: str
    data: bytes


def _envelope(operation: str, children: list[tuple[str, str]]) -> bytes:
    """Unsigned SOAP 1.2 envelope with an empty Security header and a Timestamp."""
    env = etree.Element(f"{{{SOAP12}}}Envelope", nsmap={"soap": SOAP12, "web": WEB})
    header = etree.SubElement(env, f"{{{SOAP12}}}Header")
    sec = etree.SubElement(header, f"{{{WSSE}}}Security", nsmap={"wsse": WSSE, "wsu": WSU})
    sec.set(f"{{{SOAP12}}}mustUnderstand", "true")
    now = datetime.now(UTC)
    ts = etree.SubElement(sec, f"{{{WSU}}}Timestamp")
    ts.set(f"{{{WSU}}}Id", f"TS-{uuid.uuid4().hex}")
    etree.SubElement(ts, f"{{{WSU}}}Created").text = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    etree.SubElement(ts, f"{{{WSU}}}Expires").text = (
        now + timedelta(minutes=5)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = etree.SubElement(env, f"{{{SOAP12}}}Body", nsmap={"wsu": WSU})
    body.set(f"{{{WSU}}}Id", f"id-{uuid.uuid4().hex}")
    op = etree.SubElement(body, f"{{{WEB}}}{operation}")
    parent = op
    if operation == "sendDocumentFile":
        parent = etree.SubElement(op, "Attachment")
    for tag, text in children:
        etree.SubElement(parent, tag).text = text
    return bytes(etree.tostring(env, xml_declaration=True, encoding="UTF-8"))


def _local(el: etree._Element) -> str:
    return str(etree.QName(el).localname)


def _find_local(root: etree._Element, name: str) -> etree._Element | None:
    for el in root.iter():
        if isinstance(el.tag, str) and _local(el) == name:
            return el
    return None


def parse_response(xml: bytes) -> etree._Element:
    """Return the Body's first child, or raise the Fault as a GibWsError."""
    try:
        root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise GibWsError(None, f"GİB yanıtı XML değil: {exc}", xml[:500].decode("utf-8", "replace")) from exc
    body = root.find(f"{{{SOAP12}}}Body")
    if body is None or not len(body):
        raise GibWsError(None, "GİB yanıtında SOAP gövdesi yok", xml[:500].decode("utf-8", "replace"))
    first = body[0]
    if _local(first) == "Fault":
        text = " ".join(t.strip() for t in first.itertext() if t.strip())
        # The guide lists codes, not the fault layout. Take a known code if the
        # fault carries one anywhere; keep the raw text either way.
        code = next((c for c in re.findall(r"\b([123]\d\d)\b", text) if c in ERROR_CODES), None)
        raise GibWsError(code, text or "SOAP Fault", text)
    return first


class GibEDefterClient:
    def __init__(
        self,
        *,
        signer: SoapSigner | None,
        environment: str = "test",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        if environment not in ENDPOINTS:
            raise ValueError(f"ortam test ya da prod olmalı: {environment!r}")
        self.signer = signer
        self.environment = environment
        self.url = ENDPOINTS[environment]
        self._transport = transport
        self._timeout = timeout

    async def _call(self, operation: str, children: list[tuple[str, str]]) -> etree._Element:
        if self.signer is None:
            raise GibWsNotConfigured(
                "GİB e-Defter web servisi için WS-Security imzalayıcısı yok — "
                "SOAP mesajı mali mühürle imzalanmadan hiçbir şey gönderilmez."
            )
        signed = self.signer.sign_envelope(_envelope(operation, children))
        if b"Signature" not in signed:
            raise GibWsNotConfigured("imzalayıcı zarfı imzasız döndürdü — gönderilmedi")
        async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
            resp = await client.post(
                self.url,
                content=signed,
                headers={"Content-Type": f'application/soap+xml; charset=utf-8; action="{operation}"'},
            )
        # SOAP 1.2 faults come back as 500 with a body; read it either way.
        return parse_response(resp.content)

    async def send_package(self, file_name: str, zip_bytes: bytes) -> str:
        if not file_name.endswith(".zip") or not PAKET_ID.match(file_name[:-4]):
            raise ValueError(f"paket adı GİB biçiminde değil: {file_name!r}")
        if not zip_bytes:
            raise ValueError("paket boş")
        op = await self._call("sendDocumentFile", [
            ("fileName", file_name),
            ("binaryData", base64.b64encode(zip_bytes).decode("ascii")),
        ])
        ret = _find_local(op, "return")
        return str(ret.text or "").strip() if ret is not None else ""

    async def batch_status(self, paket_id: str) -> list[BatchStatus]:
        self._require_id(paket_id)
        op = await self._call("getBatchStatus", [("paketID", paket_id)])
        out: list[BatchStatus] = []
        for el in op.iter():
            if isinstance(el.tag, str) and _local(el) == "durum":
                fields = {_local(c): (c.text or "").strip() for c in el if isinstance(c.tag, str)}
                out.append(BatchStatus(
                    paket_id=fields.get("paketKimligi", paket_id),
                    code=fields.get("durumKodu", ""),
                    description=fields.get("durumAciklama", ""),
                ))
        return out

    async def receive_berat(self, paket_id: str) -> ReceivedFile:
        self._require_id(paket_id)
        op = await self._call("receiveDocumentFile", [("PaketID", paket_id)])
        name = _find_local(op, "fileName")
        data = _find_local(op, "binaryData")
        if data is None or not (data.text or "").strip():
            raise GibWsError(None, "GİB yanıtında dosya yok")
        return ReceivedFile(
            file_name=(name.text or "").strip() if name is not None else f"{paket_id}.zip",
            data=base64.b64decode(data.text or ""),
        )

    @staticmethod
    def _require_id(paket_id: str) -> None:
        if not PAKET_ID.match(paket_id):
            raise ValueError(f"paket ID GİB biçiminde değil: {paket_id!r}")
