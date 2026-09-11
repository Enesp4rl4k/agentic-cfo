"""Berat, paket ve GİB web servisi — GİB'in kendi örnek çiftine karşı.

The berat is checked the way the defter was: against the authority. GİB's
package ships a signed yevmiye (`…-Y-000000.xml`) together with its berat
(`…-YB-000000.xml`). Feed the first to `build_berat` and every derived value
has to come out as GİB's second file has it — the entry count, the size, the
ten tax-detail totals, the signature value that binds the pair.

A berat cannot pass GİB's schema without its own XAdES signature, and this
server cannot make one. So the schema check here is precise about that: the
draft fails for the signature and for nothing else, which is shown by
splicing in GİB's own signature element and watching it pass.

Nothing here talks to GİB. The web-service tests run on httpx's
MockTransport, and one of them exists to prove a missing signer stops the
call before a connection is opened.
"""
from __future__ import annotations

import copy
import io
import zipfile
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from lxml import etree

from app.services.edefter_berat import (
    NS,
    BeratError,
    NoSigner,
    SignerUnavailable,
    build_berat,
    sign_berat,
    size_mib,
)
from app.services.edefter_package import PackageError, build_package
from app.services.edefter_xbrl import EDefterXBRLGenerator, LedgerOwner
from app.services.gib_edefter_ws import (
    ENDPOINTS,
    GibEDefterClient,
    GibWsError,
    GibWsNotConfigured,
)

PKG = Path(__file__).resolve().parent / "fixtures" / "gib_corpus" / "e_defter" / "e-Defter Paketi"
XML = PKG / "xml"
XSD = PKG / "xsd" / "edefter.xsd"
Y = "1234567808-201804-Y-000000.xml"
YB = "1234567808-201804-YB-000000.xml"
K = "1234567808-201804-K-000000.xml"
KB = "1234567808-201804-KB-000000.xml"

COR = NS["gl-cor"]
BUS = NS["gl-bus"]
DS = NS["ds"]


def _bytes(name: str) -> bytes:
    path = XML / name
    if not path.is_file():
        pytest.skip("GİB e-Defter paketi yok — python scripts/fetch_gib_corpus.py")
    return path.read_bytes()


def _root(xml: bytes) -> etree._Element:
    return etree.fromstring(xml)


def _gib_signature(berat_name: str) -> etree._Element:
    """GİB's own berat signature element, to stand in for a mali mühür."""
    node = _root(_bytes(berat_name)).find(f"{{{DS}}}Signature")
    assert node is not None
    return copy.deepcopy(node)


def _with_signature(xml: bytes, sig: etree._Element) -> bytes:
    root = _root(xml)
    root.append(sig)
    return bytes(etree.tostring(root, xml_declaration=True, encoding="UTF-8"))


class _SpliceSigner:
    """Test double: appends a pre-made signature. Proves plumbing, not crypto."""

    def __init__(self, sig: etree._Element) -> None:
        self.sig = sig

    def sign_enveloped(self, xml: bytes) -> bytes:
        return _with_signature(xml, copy.deepcopy(self.sig))


def _schema():
    if not XSD.is_file():
        pytest.skip("GİB e-Defter paketi yok")
    try:
        return etree.XMLSchema(etree.parse(str(XSD)))
    except Exception as exc:  # pragma: no cover - offline machines
        pytest.skip(f"edefter.xsd derlenemedi (ağ gerekebilir): {exc}")


def _tax(root: etree._Element) -> dict[tuple[str, str], Decimal]:
    out = {}
    for d in root.iter(f"{{{COR}}}entryDetail"):
        out[(
            d.findtext(f"{{{COR}}}account/{{{COR}}}accountMainID"),
            d.findtext(f"{{{COR}}}debitCreditCode"),
        )] = Decimal(d.findtext(f"{{{COR}}}amount"))
    return out


def _flat(el: etree._Element, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    seen: dict[str, int] = {}
    for c in el:
        tag = etree.QName(c).localname
        seen[tag] = seen.get(tag, 0) + 1
        key = f"{prefix}/{tag}[{seen[tag]}]"
        if len(c):
            out.update(_flat(c, key))
        else:
            out[key] = (c.text or "").strip()
    return out


# ── The berat, derived from GİB's signed defter ──────────────────────────────

@pytest.fixture
def gib_yb():
    return build_berat(_bytes(Y), defter_file_name=Y)


def test_the_berat_is_named_after_its_defter(gib_yb) -> None:
    assert gib_yb.file_name == YB
    assert gib_yb.kind == "YB"


def test_entry_count_matches_gibs_berat(gib_yb) -> None:
    ours = _root(gib_yb.xml).findtext(f".//{{{BUS}}}numberOfEntries")
    theirs = _root(_bytes(YB)).findtext(f".//{{{BUS}}}numberOfEntries")
    assert ours == theirs == "11"


def test_size_is_mib_to_two_places_as_gib_writes_it(gib_yb) -> None:
    theirs = _root(_bytes(YB)).findtext(f".//{{{BUS}}}measurableQuantity")
    assert gib_yb.size_mib == theirs == "0.06"
    # Divided by 10⁶ this same file would read 0.07.
    assert size_mib(66_097) == "0.06"


def test_tax_detail_equals_gibs_ten_totals(gib_yb) -> None:
    ours = _tax(_root(gib_yb.xml))
    theirs = _tax(_root(_bytes(YB)))
    assert len(theirs) == 10
    assert ours == theirs


def test_the_berat_is_bound_to_the_defter_by_its_signature_value(gib_yb) -> None:
    def top_sv(xml: bytes) -> str:
        return "".join(_root(xml).findtext(f"{{{DS}}}SignatureValue").split())

    assert top_sv(gib_yb.xml) == top_sv(_bytes(YB))
    assert gib_yb.defter_signed


def test_document_info_is_the_defters_own(gib_yb) -> None:
    ours = _flat(_root(gib_yb.xml).find(f".//{{{COR}}}documentInfo"))
    theirs = _flat(_root(_bytes(YB)).find(f".//{{{COR}}}documentInfo"))
    # entriesComment is free text; GİB's sample appends "beratı". We carry the
    # defter's comment unchanged rather than write prose into a legal file.
    diff = {k for k in ours.keys() | theirs.keys() if ours.get(k) != theirs.get(k)}
    assert diff == {"/entriesComment[1]"}
    assert ours["/uniqueID[1]"] == "YEV201804000004"


def test_entity_information_is_copied_not_rewritten(gib_yb) -> None:
    ours = _flat(_root(gib_yb.xml).find(f".//{{{COR}}}entityInformation"))
    defter = _flat(_root(_bytes(Y)).find(f".//{{{COR}}}entityInformation"))
    assert ours == defter
    # GİB's sample berat differs from its own defter in exactly one field
    # (fiscalYearStart 2018-01-01 vs 2018-04-01). We follow the defter.
    theirs = _flat(_root(_bytes(YB)).find(f".//{{{COR}}}entityInformation"))
    assert {k for k in ours if ours[k] != theirs.get(k)} == {"/fiscalYearStart[1]"}


def test_the_only_thing_the_schema_misses_is_the_berats_own_signature(gib_yb) -> None:
    schema = _schema()
    assert not schema.validate(_root(gib_yb.xml)), "imzasız berat şemadan geçmemeli"
    messages = " ".join(e.message for e in schema.error_log)
    assert "Signature" in messages
    signed = _with_signature(gib_yb.xml, _gib_signature(YB))
    assert schema.validate(_root(signed)), [e.message for e in schema.error_log][:5]


def test_ledger_berat_matches_gibs_and_has_no_entry_count() -> None:
    kb = build_berat(_bytes(K), defter_file_name=K)
    assert kb.file_name == KB and kb.number_of_entries is None
    root = _root(kb.xml)
    assert root.find(f".//{{{BUS}}}numberOfEntries") is None
    assert _tax(root) == _tax(_root(_bytes(KB)))
    assert kb.size_mib == _root(_bytes(KB)).findtext(f".//{{{BUS}}}measurableQuantity")
    assert _schema().validate(_root(_with_signature(kb.xml, _gib_signature(KB))))


def test_a_fresh_uuid_per_berat(gib_yb) -> None:
    again = build_berat(_bytes(Y), defter_file_name=Y)
    assert gib_yb.unique_id != again.unique_id
    assert len(gib_yb.unique_id) == 36


# ── Our own, unsigned defter ─────────────────────────────────────────────────

OWNER = LedgerOwner(vkn="1234567808", title="TechNova Yazılım A.Ş.")
ENTRIES = [
    {
        "kayit_id": "e1", "tarih": "2024-01-15T00:00:00", "aciklama": "Satış",
        "satirlar": [
            {"hesap_kodu": "120.01", "hesap_adi": "Alıcılar", "borc": 28_500_00, "alacak": 0},
            {"hesap_kodu": "600.01", "hesap_adi": "Yurtiçi Satışlar", "borc": 0, "alacak": 23_750_00},
            {"hesap_kodu": "391.01", "hesap_adi": "Hesaplanan KDV", "borc": 0, "alacak": 4_750_00},
        ],
    },
    {
        "kayit_id": "e2", "tarih": "2024-01-20T00:00:00", "aciklama": "Alış",
        "satirlar": [
            {"hesap_kodu": "153.01", "hesap_adi": "Ticari Mallar", "borc": 10_000_00, "alacak": 0},
            {"hesap_kodu": "191.01", "hesap_adi": "İndirilecek KDV", "borc": 2_000_00, "alacak": 0},
            {"hesap_kodu": "320.01", "hesap_adi": "Satıcılar", "borc": 0, "alacak": 12_000_00},
        ],
    },
]


@pytest.fixture
def ours():
    pkg = EDefterXBRLGenerator.generate_journal(ENTRIES, period="2024-01", owner=OWNER)
    return pkg, build_berat(pkg.xml.encode("utf-8"), defter_file_name=pkg.file_name)


def test_an_unsigned_defter_gets_a_preview_that_says_so(ours) -> None:
    _pkg, berat = ours
    assert not berat.defter_signed and not berat.filable
    assert len(berat.missing) == 2
    assert "yeniden üretilmeli" in berat.missing[0]
    assert _root(berat.xml).find("HashValue") is not None


def test_tax_detail_is_summed_from_the_file_not_the_rows(ours) -> None:
    _pkg, berat = ours
    t = berat.tax_detail
    assert t[("391", "C")] == Decimal("4750.00")
    assert t[("191", "D")] == Decimal("2000.00")
    assert t[("600", "C")] == Decimal("23750.00")
    assert t[("601", "D")] == Decimal(0) and t[("602", "C")] == Decimal(0)
    assert berat.number_of_entries == 2


def test_our_preview_is_structurally_a_berat(ours) -> None:
    _pkg, berat = ours
    assert _schema().validate(_root(_with_signature(berat.xml, _gib_signature(YB))))


def test_the_name_must_match_the_ledger_inside() -> None:
    with pytest.raises(BeratError, match="entriesType"):
        build_berat(_bytes(K), defter_file_name=Y.replace("-Y-", "-Y-"))  # K file, Y name
    with pytest.raises(BeratError, match="VKN"):
        build_berat(_bytes(Y), defter_file_name="9999999999-201804-Y-000000.xml")
    with pytest.raises(BeratError, match="biçiminde"):
        build_berat(_bytes(Y), defter_file_name="defter.xml")


def test_garbage_is_refused_not_parsed_into_something() -> None:
    with pytest.raises(BeratError):
        build_berat(b"<not-closed", defter_file_name=Y)


# ── Signing goes through an interface, and is checked on the way out ─────────

def test_this_server_has_no_signer_and_says_so(gib_yb) -> None:
    with pytest.raises(SignerUnavailable):
        sign_berat(gib_yb, NoSigner())


def test_a_signer_that_adds_nothing_does_not_produce_a_signed_berat(gib_yb) -> None:
    class Lazy:
        def sign_enveloped(self, xml: bytes) -> bytes:
            return xml

    with pytest.raises(BeratError, match="ds:Signature"):
        sign_berat(gib_yb, Lazy())


def test_a_signed_berat_is_filable_once_both_signatures_exist(gib_yb) -> None:
    signed = sign_berat(gib_yb, _SpliceSigner(_gib_signature(YB)))
    assert signed.berat_signed and signed.filable and not signed.missing


def test_an_unsigned_defters_berat_is_not_signed(ours) -> None:
    _pkg, berat = ours
    with pytest.raises(BeratError, match="önce defter"):
        sign_berat(berat, _SpliceSigner(_gib_signature(YB)))


# ── The package ──────────────────────────────────────────────────────────────

def test_gibs_own_pair_makes_a_package() -> None:
    p = build_package(defter_xml=_bytes(Y), defter_file_name=Y, berat_xml=_bytes(YB), berat_file_name=YB)
    assert p.file_name == "1234567808-201804-YB-000000.zip"
    assert p.paket_id == "1234567808-201804-YB-000000"
    with zipfile.ZipFile(io.BytesIO(p.zip_bytes)) as zf:
        assert sorted(zf.namelist()) == sorted([Y, YB])
        assert zf.read(Y) == _bytes(Y)
    again = build_package(defter_xml=_bytes(Y), defter_file_name=Y, berat_xml=_bytes(YB), berat_file_name=YB)
    assert again.zip_bytes == p.zip_bytes, "aynı iki dosya aynı paketi vermeli"


def test_a_berat_from_another_defter_is_refused() -> None:
    # KB is a real, signed GİB berat — for the kebir, not this yevmiye.
    with pytest.raises(PackageError):
        build_package(defter_xml=_bytes(Y), defter_file_name=Y, berat_xml=_bytes(KB), berat_file_name=KB)
    renamed = YB  # right name, wrong content
    with pytest.raises(PackageError, match="SignatureValue"):
        build_package(defter_xml=_bytes(Y), defter_file_name=Y, berat_xml=_bytes(KB), berat_file_name=renamed)


def test_an_unsigned_defter_never_becomes_a_package(ours) -> None:
    pkg, berat = ours
    signed_looking = _with_signature(berat.xml, _gib_signature(YB))
    with pytest.raises(PackageError, match="defter imzasız"):
        build_package(defter_xml=pkg.xml.encode("utf-8"), defter_file_name=pkg.file_name,
                      berat_xml=signed_looking, berat_file_name=berat.file_name)


def test_an_unsigned_berat_never_becomes_a_package(gib_yb) -> None:
    with pytest.raises(PackageError, match="berat imzasız"):
        build_package(defter_xml=_bytes(Y), defter_file_name=Y, berat_xml=gib_yb.xml, berat_file_name=YB)


def test_names_must_agree_on_the_part() -> None:
    with pytest.raises(PackageError, match="part"):
        build_package(defter_xml=_bytes(Y), defter_file_name=Y, berat_xml=_bytes(YB),
                      berat_file_name="1234567808-201804-YB-000001.xml")


# ── The web service client ───────────────────────────────────────────────────

class _EnvelopeSigner:
    """Marks the envelope signed. The transport is mocked; no key is involved."""

    def sign_envelope(self, envelope: bytes) -> bytes:
        return envelope.replace(b"</wsse:Security>", b"<ds:Signature xmlns:ds='http://www.w3.org/2000/09/xmldsig#'/></wsse:Security>")


def _soap(body: str) -> bytes:
    return (
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">'
        f"<soap:Body>{body}</soap:Body></soap:Envelope>"
    ).encode()


def _client(handler) -> tuple[GibEDefterClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return GibEDefterClient(signer=_EnvelopeSigner(), transport=httpx.MockTransport(wrapped)), seen


@pytest.mark.asyncio
async def test_without_a_signer_nothing_leaves_the_building() -> None:
    calls: list[httpx.Request] = []
    client = GibEDefterClient(
        signer=None,
        transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)),
    )
    with pytest.raises(GibWsNotConfigured):
        await client.batch_status("1234567808-201804-YB-000000")
    assert calls == []


def test_the_default_environment_is_test() -> None:
    assert GibEDefterClient(signer=None).url == ENDPOINTS["test"]
    assert "edeftertest" in ENDPOINTS["test"]


@pytest.mark.asyncio
async def test_status_request_matches_the_guides_message_shape() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_soap(
            '<ns2:getBatchStatusResponse xmlns:ns2="http://webservice.edefter.gib.gov.tr/">'
            "<durum><durumAciklama>Paket başarıyla işlendi</durumAciklama>"
            "<durumKodu>0</durumKodu><paketKimligi>1234567808-201804-YB-000000</paketKimligi></durum>"
            "</ns2:getBatchStatusResponse>"
        ))

    client, seen = _client(handler)
    out = await client.batch_status("1234567808-201804-YB-000000")
    assert out[0].code == "0" and out[0].paket_id == "1234567808-201804-YB-000000"

    req = etree.fromstring(seen[0].content)
    assert etree.QName(req).namespace == "http://www.w3.org/2003/05/soap-envelope"
    op = req.find(".//{http://webservice.edefter.gib.gov.tr/}getBatchStatus")
    assert op is not None and op.find("paketID").text == "1234567808-201804-YB-000000"
    assert "application/soap+xml" in seen[0].headers["content-type"]
    assert seen[0].url.host == "edeftertest.gib.gov.tr"


@pytest.mark.asyncio
async def test_a_package_is_sent_as_a_named_attachment() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_soap(
            '<ns2:sendDocumentFileResponse xmlns:ns2="http://webservice.edefter.gib.gov.tr/">'
            "<return>1234567808-201804-YB-000000.zip paketi işleme alındı</return>"
            "</ns2:sendDocumentFileResponse>"
        ))

    client, seen = _client(handler)
    msg = await client.send_package("1234567808-201804-YB-000000.zip", b"PK\x03\x04zip")
    assert "işleme alındı" in msg
    att = etree.fromstring(seen[0].content).find(".//Attachment")
    assert att.findtext("fileName") == "1234567808-201804-YB-000000.zip"
    assert att.findtext("binaryData") == "UEsDBHppcA=="


@pytest.mark.parametrize(("code", "transient"), [("111", False), ("113", True), ("305", False)])
@pytest.mark.asyncio
async def test_gib_faults_carry_their_code(code: str, transient: bool) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=_soap(
            "<soap:Fault><soap:Code><soap:Value>soap:Receiver</soap:Value></soap:Code>"
            f"<soap:Reason><soap:Text xml:lang='tr'>{code} - hata</soap:Text></soap:Reason></soap:Fault>"
        ))

    client, _ = _client(handler)
    with pytest.raises(GibWsError) as exc:
        await client.batch_status("1234567808-201804-YB-000000")
    assert exc.value.code == code
    assert exc.value.transient is transient


@pytest.mark.asyncio
async def test_an_approved_berat_comes_back_as_bytes() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_soap(
            '<ns2:receiveDocumentFileResponse xmlns:ns2="http://webservice.edefter.gib.gov.tr/">'
            "<Attachment><fileName>GIB-1234567808-201804-YB-000000.zip</fileName>"
            "<binaryData>UEsDBA==</binaryData></Attachment></ns2:receiveDocumentFileResponse>"
        ))

    client, _ = _client(handler)
    f = await client.receive_berat("1234567808-201804-YB-000000")
    assert f.file_name.startswith("GIB-") and f.data == b"PK\x03\x04"


@pytest.mark.parametrize("bad", ["", "1234567808-201804-YB", "1234567808-201804-X-000000", "../etc"])
@pytest.mark.asyncio
async def test_a_malformed_package_id_is_refused_locally(bad: str) -> None:
    client, seen = _client(lambda r: httpx.Response(200))
    with pytest.raises(ValueError):
        await client.batch_status(bad)
    assert seen == []
