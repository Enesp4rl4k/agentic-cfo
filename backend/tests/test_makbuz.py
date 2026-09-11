"""e-Müstahsil ve e-SMM — GİB'in kılavuz ve şemasına göre.

GİB publishes no complete sample document for either. So the fixtures here
are assembled from what it does publish, and checked against it:

- e-Müstahsil: the element examples of the UBL-TR Müstahsil Makbuzu Kılavuzu
  v1.1 (a 17 500 TL line, 2 % stopaj of 350 TL under code 0003). The guide's
  LegalMonetaryTotal example (90 / 80 / 94) is illustrative and does not match
  its own line, so the totals below are the ones the line implies.
- e-SMM: built to `eArsivVeri.xsd` from GİB's e-Arşiv package, and the first
  test validates it against that schema. If the fixture drifts from what GİB
  accepts, that test fails before any parser test can pass on it.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.parsers.invoice.makbuz import NotAMakbuzError, parse_makbuz

XSD = Path(__file__).resolve().parent / "fixtures" / "gib_corpus" / "e_arsiv" / "eArsivVeri.xsd"

BUYER = "1234567890"        # the guide's supplier party: issues the receipt
FARMER = "14604153088"      # the guide's customer party: the producer
PROFESSIONAL = "9876543210"
CLIENT = "1234567808"


def _mm(*, type_code: str | None = "MUSTAHSILMAKBUZ", profile: str = "EARSIVBELGE",
        extra_tax: str = "", payable: str = "17150") -> str:
    tc = f"<cbc:CreditNoteTypeCode>{type_code}</cbc:CreditNoteTypeCode>" if type_code else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<CreditNote xmlns="urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:UBLVersionID>2.1</cbc:UBLVersionID>
  <cbc:CustomizationID>TR1.2.1</cbc:CustomizationID>
  <cbc:ProfileID>{profile}</cbc:ProfileID>
  <cbc:ID>GIB2026000000001</cbc:ID>
  <cbc:CopyIndicator>false</cbc:CopyIndicator>
  <cbc:UUID>e093a490-dd99-11dd-ad8b-0800200c9a66</cbc:UUID>
  <cbc:IssueDate>2026-09-01</cbc:IssueDate>
  {tc}
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">{BUYER}</cbc:ID></cac:PartyIdentification>
    <cac:PartyName><cbc:Name>AAA Anonim Şirketi</cbc:Name></cac:PartyName>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="TCKN">{FARMER}</cbc:ID></cac:PartyIdentification>
    <cac:Person><cbc:FirstName>ÇifçiAd</cbc:FirstName><cbc:FamilyName>ÇifçiSoyad</cbc:FamilyName></cac:Person>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="TRY">350</cbc:TaxAmount>
    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="TRY">17500</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="TRY">350</cbc:TaxAmount>
      <cbc:Percent>2</cbc:Percent>
      <cac:TaxCategory><cac:TaxScheme>
        <cbc:Name>GELİR VERGİSİ S. (MUHTASAR)</cbc:Name><cbc:TaxTypeCode>0003</cbc:TaxTypeCode>
      </cac:TaxScheme></cac:TaxCategory>
    </cac:TaxSubtotal>
    {extra_tax}
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="TRY">17500</cbc:LineExtensionAmount>
    <cbc:PayableAmount currencyID="TRY">{payable}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:CreditNoteLine>
    <cbc:ID>1</cbc:ID>
    <cbc:CreditedQuantity unitCode="C62">5</cbc:CreditedQuantity>
    <cbc:LineExtensionAmount currencyID="TRY">17500</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Büyükbaş hayvan</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="TRY">3500</cbc:PriceAmount></cac:Price>
  </cac:CreditNoteLine>
</CreditNote>"""


def _smm(*, tevkifat: str = "", currency: str = "TRY", payable: str = "1000") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<earsiv:eArsivVeri xmlns:earsiv="http://earsiv.efatura.gov.tr">
  <earsiv:baslik>
    <earsiv:mukellef><earsiv:vkn>{PROFESSIONAL}</earsiv:vkn></earsiv:mukellef>
    <earsiv:hazirlayan><earsiv:vkn>{PROFESSIONAL}</earsiv:vkn></earsiv:hazirlayan>
  </earsiv:baslik>
  <earsiv:serbestMeslekMakbuz>
    <earsiv:makbuzNo>CDE2026000000001</earsiv:makbuzNo>
    <earsiv:ETTN>3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d</earsiv:ETTN>
    <earsiv:gonderimSekli>ELEKTRONIK</earsiv:gonderimSekli>
    <earsiv:dosyaAdi>SerbestMeslekMakbuz_CDE2026000000001.pdf</earsiv:dosyaAdi>
    <earsiv:belgeTarihi>2026-09-01</earsiv:belgeTarihi>
    <earsiv:toplamTutar>1000</earsiv:toplamTutar>
    <earsiv:odenecekTutar>{payable}</earsiv:odenecekTutar>
    <earsiv:paraBirimi>{currency}</earsiv:paraBirimi>
    <earsiv:vergiBilgisi>
      <earsiv:vergilerToplami>400</earsiv:vergilerToplami>
      <earsiv:vergi>
        <earsiv:matrah>1000</earsiv:matrah><earsiv:vergiKodu>0015</earsiv:vergiKodu>
        <earsiv:vergiTutari>200</earsiv:vergiTutari><earsiv:vergiOrani>20</earsiv:vergiOrani>
      </earsiv:vergi>
      <earsiv:vergi>
        <earsiv:matrah>1000</earsiv:matrah><earsiv:vergiKodu>0003</earsiv:vergiKodu>
        <earsiv:vergiTutari>200</earsiv:vergiTutari><earsiv:vergiOrani>20</earsiv:vergiOrani>
      </earsiv:vergi>
      {tevkifat}
    </earsiv:vergiBilgisi>
    <earsiv:aliciBilgileri>
      <earsiv:tuzelKisi><earsiv:vkn>{CLIENT}</earsiv:vkn><earsiv:unvan>TechNova Yazılım A.Ş.</earsiv:unvan></earsiv:tuzelKisi>
      <earsiv:adres>
        <earsiv:caddeSokak>Büyükdere Cd.</earsiv:caddeSokak><earsiv:binaAd>Plaza</earsiv:binaAd>
        <earsiv:binaNo>1</earsiv:binaNo><earsiv:kapiNo>5</earsiv:kapiNo><earsiv:kasabaKoy>-</earsiv:kasabaKoy>
        <earsiv:semt>Levent</earsiv:semt><earsiv:sehir>İstanbul</earsiv:sehir>
        <earsiv:postaKod>34330</earsiv:postaKod><earsiv:ulke>TR</earsiv:ulke>
        <earsiv:vDaire>Boğaziçi</earsiv:vDaire>
      </earsiv:adres>
    </earsiv:aliciBilgileri>
    <earsiv:malHizmetBilgisi>
      <earsiv:malHizmet>
        <earsiv:ad>Hukuki danışmanlık</earsiv:ad>
        <earsiv:vergiBilgisi>
          <earsiv:vergilerToplami>400</earsiv:vergilerToplami>
          <earsiv:vergi>
            <earsiv:matrah>1000</earsiv:matrah><earsiv:vergiKodu>0015</earsiv:vergiKodu>
            <earsiv:vergiTutari>200</earsiv:vergiTutari><earsiv:vergiOrani>20</earsiv:vergiOrani>
          </earsiv:vergi>
        </earsiv:vergiBilgisi>
        <earsiv:burutUcret>1000</earsiv:burutUcret>
      </earsiv:malHizmet>
    </earsiv:malHizmetBilgisi>
  </earsiv:serbestMeslekMakbuz>
</earsiv:eArsivVeri>"""


def _lines(m) -> dict[str, tuple[Decimal, Decimal]]:
    return {e.account_code: (e.debit_amount, e.credit_amount) for e in m.suggested_tdhp_entries}


# ── e-SMM fixture is what GİB's schema accepts ───────────────────────────────

def test_the_smm_fixture_passes_gibs_earsiv_schema() -> None:
    etree = pytest.importorskip("lxml.etree")
    if not XSD.is_file():
        pytest.skip("GİB e-Arşiv paketi yok — python scripts/fetch_gib_corpus.py")
    schema = etree.XMLSchema(etree.parse(str(XSD)))
    doc = etree.fromstring(_smm().encode("utf-8"))
    assert schema.validate(doc), [e.message for e in schema.error_log][:5]


# ── e-Müstahsil ──────────────────────────────────────────────────────────────

def test_the_buyer_books_produce_stopaj_and_the_farmer_payable() -> None:
    m = parse_makbuz(_mm(), own_vkn=BUYER)
    assert m.kind == "mustahsil" and m.direction == "purchase"
    assert (m.gross, m.stopaj, m.payable) == (Decimal("17500"), Decimal("350"), Decimal("17150"))
    lines = _lines(m)
    assert lines["153.01"] == (Decimal("17500"), 0)
    assert lines["360.01"] == (0, Decimal("350"))
    assert lines["320.01"] == (0, Decimal("17150"))
    assert m.payee.title == "ÇifçiAd ÇifçiSoyad"


def test_the_farmer_reading_it_books_a_sale_and_a_tax_prepayment() -> None:
    m = parse_makbuz(_mm(), own_vkn=FARMER)
    assert m.direction == "sale"
    lines = _lines(m)
    assert lines["120.01"] == (Decimal("17150"), 0)
    assert lines["193.01"] == (Decimal("350"), 0)
    assert lines["600.01"] == (0, Decimal("17500"))


def test_a_stranger_gets_no_entry() -> None:
    m = parse_makbuz(_mm(), own_vkn="5555555555")
    assert m.direction == "unknown" and m.needs_review


def test_another_creditnote_on_the_same_profile_is_not_a_makbuz() -> None:
    with pytest.raises(NotAMakbuzError):
        parse_makbuz(_mm(type_code="ADISYON"), own_vkn=BUYER)
    with pytest.raises(NotAMakbuzError):
        parse_makbuz(_mm(profile="TICARIFATURA"), own_vkn=BUYER)


def test_no_type_code_is_read_but_not_posted() -> None:
    m = parse_makbuz(_mm(type_code=None), own_vkn=BUYER)
    assert m.needs_review and "CreditNoteTypeCode" in m.posting_note


def test_an_unknown_deduction_is_not_guessed_into_an_account() -> None:
    extra = """<cac:TaxSubtotal><cbc:TaxableAmount currencyID="TRY">17500</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="TRY">175</cbc:TaxAmount>
      <cac:TaxCategory><cac:TaxScheme><cbc:TaxTypeCode>9999</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory>
    </cac:TaxSubtotal>"""
    m = parse_makbuz(_mm(extra_tax=extra, payable="16975"), own_vkn=BUYER)
    assert m.needs_review and "9999" in m.posting_note


def test_a_receipt_that_does_not_add_up_is_held() -> None:
    m = parse_makbuz(_mm(payable="17500"), own_vkn=BUYER)
    assert m.needs_review and "tutmuyor" in m.posting_note


# ── e-SMM ────────────────────────────────────────────────────────────────────

def test_the_client_books_the_fee_kdv_stopaj_and_the_net_payable() -> None:
    m = parse_makbuz(_smm(), own_vkn=CLIENT)
    assert m.kind == "serbest_meslek" and m.direction == "purchase"
    lines = _lines(m)
    assert lines["770.01"] == (Decimal("1000"), 0)
    assert lines["191.01"] == (Decimal("200"), 0)
    assert lines["360.01"] == (0, Decimal("200"))
    assert lines["320.01"] == (0, Decimal("1000"))
    assert m.payer.title == "TechNova Yazılım A.Ş."


def test_the_professional_books_revenue_kdv_and_the_stopaj_as_prepaid_tax() -> None:
    m = parse_makbuz(_smm(), own_vkn=PROFESSIONAL)
    assert m.direction == "sale"
    lines = _lines(m)
    assert lines["120.01"] == (Decimal("1000"), 0)
    assert lines["193.01"] == (Decimal("200"), 0)
    assert lines["600.01"] == (0, Decimal("1000"))
    assert lines["391.01"] == (0, Decimal("200"))


def test_tevkifat_is_held_rather_than_guessed() -> None:
    tev = """<earsiv:tevkifat><earsiv:tevkifatKodu>410</earsiv:tevkifatKodu>
      <earsiv:tevkifatTutari>36</earsiv:tevkifatTutari><earsiv:tevkifatOrani>20</earsiv:tevkifatOrani></earsiv:tevkifat>"""
    m = parse_makbuz(_smm(tevkifat=tev, payable="964"), own_vkn=CLIENT)
    assert m.withholding == Decimal("36")
    assert m.needs_review and "tevkifat" in m.posting_note


def test_a_foreign_currency_receipt_is_not_booked_in_lira() -> None:
    m = parse_makbuz(_smm(currency="EUR"), own_vkn=CLIENT)
    assert m.needs_review and "EUR" in m.posting_note


# ── Ingestion: the upload no longer disappears ──────────────────────────────

@pytest.mark.parametrize(("doc", "own", "typ", "category", "cents"), [
    (_mm, BUYER, "expense", "cogs", 1_715_000),
    (_smm, CLIENT, "expense", "other_expense", 100_000),
    (_smm, PROFESSIONAL, "income", "revenue", 100_000),
])
def test_ingestion_turns_a_receipt_into_a_transaction(monkeypatch, doc, own, typ, category, cents) -> None:
    """Both used to reach the UBL path, fail the Invoice check, and be logged
    as "not an invoice, skipped" — the uploaded document produced nothing."""
    from app.agents.data_ingestion import KNOWN_CATEGORIES, _try_parse_ubl_xml
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "gib_vkn", own)
    rows = _try_parse_ubl_xml(doc())
    assert rows and len(rows) == 1
    row = rows[0]
    assert (row["type"], row["category"], row["amount_cents"]) == (typ, category, cents)
    assert row["category"] in KNOWN_CATEGORIES
    assert row["confidence"] == 0.95


def test_an_esmm_pdf_is_read_from_its_attachment(tmp_path, monkeypatch) -> None:
    """GİB delivers e-SMM as a PDF with the data attached as XML (§7). The
    page text is a rendering; the attachment is the record."""
    pymupdf = pytest.importorskip("pymupdf")
    from app.agents.data_ingestion import _pdf_embedded_xml, _try_parse_ubl_xml
    from app.config import get_settings

    pdf = tmp_path / "SerbestMeslekMakbuz_CDE2026000000001.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Serbest Meslek Makbuzu - görüntü")
    doc.embfile_add("makbuz.xslt", b"<xsl:stylesheet/>")          # not a document
    doc.embfile_add("CDE2026000000001.xml", _smm().encode("utf-8"))
    doc.save(str(pdf))
    doc.close()

    found = _pdf_embedded_xml(str(pdf))
    assert len(found) == 1 and "serbestMeslekMakbuz" in found[0]

    monkeypatch.setattr(get_settings(), "gib_vkn", CLIENT)
    row = _try_parse_ubl_xml(found[0])[0]
    assert (row["type"], row["amount_cents"]) == ("expense", 100_000)


def test_a_plain_pdf_has_no_embedded_documents(tmp_path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    from app.agents.data_ingestion import _pdf_embedded_xml

    pdf = tmp_path / "ekstre.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Hesap ekstresi")
    doc.save(str(pdf))
    doc.close()
    assert _pdf_embedded_xml(str(pdf)) == []


def test_an_unposted_receipt_is_kept_behind_the_gate(monkeypatch) -> None:
    from app.agents.data_ingestion import _try_parse_ubl_xml
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "gib_vkn", "5555555555")
    row = _try_parse_ubl_xml(_mm())[0]
    assert row["confidence"] < 0.8
    assert "Kayıt üretilmedi" in row["raw_text"]


def test_neither_format_is_confused_with_an_invoice() -> None:
    with pytest.raises(NotAMakbuzError):
        parse_makbuz(b"<Invoice xmlns='urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'/>")
    with pytest.raises(NotAMakbuzError):
        parse_makbuz(b"<not-closed")
