"""SMMM M2: what the doors let in, and how they read it.

* The upload path read a CSV as UTF-8 only. A Turkish bank or ERP export is very
  often Windows-1254, so it ended in a generic ingestion error before anything
  was recognised. (`/veri/ekle` already fell back to cp1254.)
* The mail door dropped an e-Fatura sent as `application/xml` or `text/xml` (it
  only passed octet-stream, text/plain and the spreadsheet/PDF types), so the
  document a Turkish company actually holds could not arrive by e-mail. Opening
  that door means XML reaches the parser, so the safety check at the next door
  (no DTD, no ENTITY) is tested here too.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage

import pytest

from app.agents.data_ingestion import _read_csv
from tests.test_ingest import _login
from tests.test_parsers.test_ocr_and_invoice import SAMPLE_UBL_TR_XML

SECRET = "s3cret-for-tests"
P = "/api/v1"

TURKCE = "tarih;açıklama;tutar\n05.01.2026;Müşteri tahsilatı İstanbul şubesi;1.500,00\n"


# ── the upload path reads Windows-1254 ───────────────────────────────────────

def test_a_windows_1254_csv_is_read_not_refused(tmp_path):
    f = tmp_path / "ekstre.csv"
    f.write_bytes(TURKCE.encode("cp1254"))
    assert "Müşteri tahsilatı İstanbul şubesi" in _read_csv(str(f))


def test_a_utf8_csv_with_a_bom_is_unchanged(tmp_path):
    f = tmp_path / "ekstre.csv"
    f.write_bytes(TURKCE.encode("utf-8-sig"))
    text = _read_csv(str(f))
    assert text.startswith("tarih") and "Müşteri tahsilatı" in text  # the BOM is not part of the header


# ── an e-Fatura by mail ──────────────────────────────────────────────────────

@pytest.fixture
def inbox(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "email_ingest_domain", "veri.example.com")
    monkeypatch.setattr(s, "email_inbound_secret", SECRET)


def _mail(to: str, name: str, data: bytes, ctype: str) -> bytes:
    m = EmailMessage()
    m["From"] = "muhasebe@firma.example"
    m["To"] = to
    m["Subject"] = "Ocak faturası"
    m.set_content("Ekte fatura.")
    main, sub = ctype.split("/")
    m.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return m.as_bytes()


async def _send(client, h, name, data, ctype):
    adres = (await client.get(f"{P}/email/ingest-address", headers=h)).json()["data"]["adres"]
    basic = base64.b64encode(f"inbound:{SECRET}".encode()).decode()
    r = await client.post(
        f"{P}/email/inbound", content=_mail(adres, name, data, ctype),
        headers={"Authorization": f"Basic {basic}"},
    )
    assert r.status_code == 200, r.text
    hist = (await client.get(f"{P}/email/history", headers=h)).json()["data"]
    return {d["dosya"]: d for h_ in hist for d in h_["dosyalar"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("ctype", ["application/xml", "text/xml"])
async def test_an_e_fatura_sent_as_xml_arrives(client, inbox, ctype):
    h = await _login(client)
    by = await _send(client, h, "fatura.xml", SAMPLE_UBL_TR_XML.encode("utf-8"), ctype)
    assert "fatura.xml" in by, "the attachment was dropped before it reached the door"
    assert by["fatura.xml"]["durum"] == "eklendi"


@pytest.mark.asyncio
async def test_an_xml_with_an_entity_declaration_is_refused_at_the_door(client, inbox):
    h = await _login(client)
    bomba = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa">]>'
        b"<Invoice>&a;&a;&a;</Invoice>"
    )
    by = await _send(client, h, "fatura.xml", bomba, "application/xml")
    assert by["fatura.xml"]["durum"] == "reddedildi"
