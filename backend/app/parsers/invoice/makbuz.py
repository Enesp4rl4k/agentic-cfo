"""e-Müstahsil Makbuzu ve e-Serbest Meslek Makbuzu (e-SMM) okuyucu.

Two e-Arşiv documents that are not invoices, and that the invoice parser
refused — which the ingestion path then logged as "not an invoice, skipped".
A company buying produce from a farmer, or paying its lawyer, uploaded the
document and it vanished.

Formats, from GİB's own guides:

- **e-Müstahsil Makbuzu** — UBL-TR *CreditNote* (UBL-TR Müstahsil Makbuzu
  Kılavuzu v1.1, Mayıs 2026). ProfileID `EARSIVBELGE`, CreditNoteTypeCode
  `MUSTAHSILMAKBUZ`. The *supplier* party is the one who issues the receipt —
  the buyer of the goods; the *customer* party is the farmer who sold them.
  The deduction is gelir vergisi stopajı, TaxTypeCode `0003`.
- **e-SMM** — a PDF carrying the receipt data as an attached XML that follows
  the e-Arşiv data schema (`eArsivVeri.xsd`, root `eArsivVeri`, element
  `serbestMeslekMakbuz`; e-Arşiv Kılavuzu v1.18 §3.3.6 and §7). `baslik/
  mukellef` is the professional who issued it; `aliciBilgileri` is the client.
  `toplamTutar` is the fee before tax, KDV is code `0015`, stopaj `0003`.

Both are posted from the side of whoever is reading them. The receipt names
the payer and the payee; our VKN says which of the two we are, exactly as the
invoice parser settles direction. Nothing is posted when:

- our side cannot be established,
- a tax code other than KDV and stopaj appears (we will not guess what an
  unnamed deduction is, or which account it belongs to),
- the receipt carries `tevkifat`: its code comes from the İnternet Vergi
  Dairesi list, and from the code alone we cannot tell a KDV withholding from
  an income-tax one, which post to different accounts on each side,
- the amount is in a foreign currency,
- or the components do not add up to the receipt's own payable amount.

Each of those returns the reason instead, and the ingestion path holds the row
for a person.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, Field

from app.parsers.invoice.ubl_tr import (
    BALANCE_TOLERANCE,
    KDV_TAX_CODE,
    InvoiceDirection,
    InvoiceParty,
    TDHPJournalEntry,
    UBLTRInvoiceParser,
)

CREDIT_NOTE_NS = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
CREDIT_NOTE_ROOT = f"{{{CREDIT_NOTE_NS}}}CreditNote"
EARSIV_NS = "http://earsiv.efatura.gov.tr"
EARSIV_ROOT = f"{{{EARSIV_NS}}}eArsivVeri"

GV_STOPAJ_CODE = "0003"
MUSTAHSIL_PROFILE = "EARSIVBELGE"
MUSTAHSIL_TYPE = "MUSTAHSILMAKBUZ"

MakbuzKind = Literal["mustahsil", "serbest_meslek"]

_NS = UBLTRInvoiceParser.NAMESPACES


class NotAMakbuzError(ValueError):
    """Well-formed XML, but neither an e-Müstahsil nor an e-SMM."""


class ParsedMakbuz(BaseModel):
    kind: MakbuzKind
    number: str
    uuid: str = ""
    issue_date: date | None = None
    currency: str = "TRY"
    # Who wrote the receipt, and who is on the other side of it.
    issuer: InvoiceParty
    counterparty: InvoiceParty
    # The one who pays and the one who is paid. For e-Müstahsil the issuer
    # pays the farmer; for e-SMM the client pays the professional who issued it.
    payer: InvoiceParty
    payee: InvoiceParty
    gross: Decimal = Decimal("0")          # before tax and deductions
    kdv: Decimal = Decimal("0")
    stopaj: Decimal = Decimal("0")         # gelir vergisi stopajı (0003)
    other_taxes: dict[str, Decimal] = Field(default_factory=dict)
    withholding: Decimal = Decimal("0")    # e-SMM `tevkifat`
    payable: Decimal = Decimal("0")
    # What was sold or rendered, as the document names it. The classifier
    # downstream reads descriptions; a receipt number and a VKN give it nothing.
    items: list[str] = Field(default_factory=list)
    direction: InvoiceDirection = "unknown"   # "purchase": we pay
    direction_basis: str = ""
    suggested_tdhp_entries: list[TDHPJournalEntry] = Field(default_factory=list)
    posting_note: str = ""

    @property
    def needs_review(self) -> bool:
        return not self.suggested_tdhp_entries


def _dec(text: str | None) -> Decimal:
    try:
        return Decimal((text or "").strip() or "0")
    except InvalidOperation:
        return Decimal("0")


def _date(text: str | None) -> date | None:
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _side(own_vkn: str, payer: InvoiceParty, payee: InvoiceParty) -> tuple[InvoiceDirection, str]:
    mine = UBLTRInvoiceParser.normalize_vkn(own_vkn)
    if not mine:
        return "unknown", "kendi VKN'miz yapılandırılmamış (GIB_VKN)"
    pay = UBLTRInvoiceParser.normalize_vkn(payer.vkn_tckn)
    rec = UBLTRInvoiceParser.normalize_vkn(payee.vkn_tckn)
    if pay and pay == rec:
        return "unknown", f"ödeyen ve alan aynı kimliği taşıyor ({pay})"
    if mine == pay:
        return "purchase", f"ödeyen taraf ({pay}) biziz"
    if mine == rec:
        return "sale", f"ödenen taraf ({rec}) biziz"
    return "unknown", f"VKN {mine} ne ödeyenle ({pay or 'yok'}) ne alanla ({rec or 'yok'}) eşleşti"


def _entries(m: ParsedMakbuz) -> tuple[list[TDHPJournalEntry], str]:
    if m.direction == "unknown":
        return [], "makbuzda hangi taraf olduğumuz belirlenemedi — kayıt üretilmedi"
    if m.currency.upper() != "TRY":
        return [], f"makbuz {m.currency} cinsinden — TRY deftere kursuz işlenmez"
    if m.other_taxes:
        codes = ", ".join(sorted(m.other_taxes))
        return [], f"tanınmayan vergi/kesinti kodu ({codes}) — hangi hesaba gideceği tahmin edilmez"
    if m.withholding > 0:
        return [], (
            f"tevkifat var ({m.withholding}) — kodundan KDV mi gelir vergisi mi "
            "olduğu belirlenemez, kayıt üretilmedi"
        )
    if m.gross <= 0 or m.payable <= 0:
        return [], "brüt ya da ödenecek tutar yok — kayıt üretilmedi"

    desc = f"{'e-Müstahsil' if m.kind == 'mustahsil' else 'e-SMM'} No: {m.number}"
    out: list[TDHPJournalEntry] = []

    def add(code: str, name: str, *, debit: Decimal = Decimal("0"), credit: Decimal = Decimal("0")) -> None:
        if debit or credit:
            out.append(TDHPJournalEntry(
                account_code=code, account_name=name,
                debit_amount=debit, credit_amount=credit, description=desc,
            ))

    if m.direction == "purchase":
        if m.kind == "mustahsil":
            # Produce bought for resale. A manufacturer buying raw material
            # would take it to 150 — the accountant moves it; the amount is
            # the document's own.
            add("153.01", "Ticari Mallar (müstahsil alımı)", debit=m.gross)
        else:
            add("770.01", "Genel Yönetim Giderleri (serbest meslek hizmeti)", debit=m.gross)
        add("191.01", "İndirilecek KDV", debit=m.kdv)
        add("360.01", "Ödenecek Vergi ve Fonlar (gelir vergisi stopajı)", credit=m.stopaj)
        add("320.01", f"Satıcılar - {m.payee.title or 'makbuz sahibi'}", credit=m.payable)
    else:
        add("120.01", f"Alıcılar - {m.payer.title or 'ödeyen'}", debit=m.payable)
        # Tax withheld from us is a prepayment of our own income tax.
        add("193.01", "Peşin Ödenen Vergiler ve Fonlar (stopaj)", debit=m.stopaj)
        add("600.01", "Yurtiçi Satışlar", credit=m.gross)
        add("391.01", "Hesaplanan KDV", credit=m.kdv)

    debit = sum((e.debit_amount for e in out), Decimal("0"))
    credit = sum((e.credit_amount for e in out), Decimal("0"))
    if abs(debit - credit) > BALANCE_TOLERANCE:
        return [], (
            f"makbuz kendi toplamıyla tutmuyor (brüt {m.gross} + KDV {m.kdv} − stopaj "
            f"{m.stopaj} ≠ ödenecek {m.payable}) — kayıt üretilmedi"
        )
    return out, ""


# ── e-Müstahsil (UBL-TR CreditNote) ──────────────────────────────────────────

def _ubl_party(node: ET.Element | None) -> InvoiceParty:
    if node is None:
        return InvoiceParty()
    ident = UBLTRInvoiceParser._party_identifier(node)
    name = node.findtext("cac:PartyName/cbc:Name", "", _NS).strip()
    if not name:
        first = node.findtext("cac:Person/cbc:FirstName", "", _NS).strip()
        family = node.findtext("cac:Person/cbc:FamilyName", "", _NS).strip()
        name = f"{first} {family}".strip()
    return InvoiceParty(vkn_tckn=ident, title=name)


def _parse_mustahsil(root: ET.Element, own_vkn: str) -> ParsedMakbuz:
    profile = root.findtext("cbc:ProfileID", "", _NS).strip().upper()
    type_code = root.findtext("cbc:CreditNoteTypeCode", "", _NS).strip().upper()
    if profile != MUSTAHSIL_PROFILE:
        raise NotAMakbuzError(f"CreditNote ama ProfileID {profile or 'yok'} — müstahsil makbuzu değil")
    if type_code and type_code != MUSTAHSIL_TYPE:
        # e-Adisyon is a CreditNote on the same profile. It is not a purchase.
        raise NotAMakbuzError(f"CreditNoteTypeCode {type_code} — müstahsil makbuzu değil")

    issuer = _ubl_party(root.find("cac:AccountingSupplierParty/cac:Party", _NS))
    farmer = _ubl_party(root.find("cac:AccountingCustomerParty/cac:Party", _NS))

    stopaj = kdv = Decimal("0")
    other: dict[str, Decimal] = {}
    for sub in root.findall("cac:TaxTotal/cac:TaxSubtotal", _NS):
        code = sub.findtext("cac:TaxCategory/cac:TaxScheme/cbc:TaxTypeCode", "", _NS).strip()
        amount = _dec(sub.findtext("cbc:TaxAmount", "", _NS))
        if code == GV_STOPAJ_CODE:
            stopaj += amount
        elif code == KDV_TAX_CODE:
            kdv += amount
        else:
            other[code or "kodsuz"] = other.get(code or "kodsuz", Decimal("0")) + amount

    totals = root.find("cac:LegalMonetaryTotal", _NS)
    line_sum = sum(
        (_dec(line.findtext("cbc:LineExtensionAmount", "", _NS))
         for line in root.findall("cac:CreditNoteLine", _NS)),
        Decimal("0"),
    )
    gross = _dec(totals.findtext("cbc:LineExtensionAmount", "", _NS)) if totals is not None else line_sum
    payable = _dec(totals.findtext("cbc:PayableAmount", "", _NS)) if totals is not None else Decimal("0")

    m = ParsedMakbuz(
        kind="mustahsil",
        number=root.findtext("cbc:ID", "", _NS).strip(),
        uuid=root.findtext("cbc:UUID", "", _NS).strip(),
        issue_date=_date(root.findtext("cbc:IssueDate", "", _NS)),
        currency=(root.findtext("cbc:DocumentCurrencyCode", "", _NS).strip() or "TRY"),
        issuer=issuer, counterparty=farmer, payer=issuer, payee=farmer,
        gross=gross, kdv=kdv, stopaj=stopaj, other_taxes=other, payable=payable,
        items=[
            name for line in root.findall("cac:CreditNoteLine", _NS)
            if (name := line.findtext("cac:Item/cbc:Name", "", _NS).strip())
        ],
    )
    m.direction, m.direction_basis = _side(own_vkn, m.payer, m.payee)
    if not type_code:
        m.posting_note = "CreditNoteTypeCode yok — müstahsil makbuzu olduğu doğrulanamadı, kayıt üretilmedi"
        return m
    if abs(line_sum - gross) > BALANCE_TOLERANCE:
        m.posting_note = f"kalemlerin toplamı ({line_sum}) makbuz toplamıyla ({gross}) tutmuyor — kayıt üretilmedi"
        return m
    m.suggested_tdhp_entries, m.posting_note = _entries(m)
    return m


# ── e-SMM (eArsivVeri / serbestMeslekMakbuz) ─────────────────────────────────
# eArsivVeri.xsd qualifies some local elements and not others, so these
# lookups go by local name. A document cannot be half in the namespace and
# half out of it in a way that changes what the fee is.

def _local(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _kid(el: ET.Element | None, name: str) -> ET.Element | None:
    if el is None:
        return None
    return next((c for c in el if _local(c) == name), None)


def _kids(el: ET.Element | None, name: str) -> list[ET.Element]:
    return [] if el is None else [c for c in el if _local(c) == name]


def _text(el: ET.Element | None, *path: str) -> str:
    node = el
    for name in path:
        node = _kid(node, name)
    return (node.text or "").strip() if node is not None else ""


def _vkn_tckn(el: ET.Element | None) -> str:
    return _text(el, "vkn") or _text(el, "tckn")


def _parse_smm(root: ET.Element, own_vkn: str) -> ParsedMakbuz:
    smm = _kid(root, "serbestMeslekMakbuz")
    if smm is None:
        raise NotAMakbuzError("eArsivVeri içinde serbestMeslekMakbuz yok")

    professional = InvoiceParty(vkn_tckn=_vkn_tckn(_kid(_kid(root, "baslik"), "mukellef")))
    alici = _kid(smm, "aliciBilgileri")
    tuzel, gercek = _kid(alici, "tuzelKisi"), _kid(alici, "gercekKisi")
    client = InvoiceParty(
        vkn_tckn=_text(tuzel, "vkn") or _text(gercek, "tckn"),
        title=_text(tuzel, "unvan") or _text(gercek, "adiSoyadi"),
    )

    vergi = _kid(smm, "vergiBilgisi")
    stopaj = kdv = Decimal("0")
    other: dict[str, Decimal] = {}
    for v in _kids(vergi, "vergi"):
        code = _text(v, "vergiKodu")
        amount = _dec(_text(v, "vergiTutari"))
        if code == GV_STOPAJ_CODE:
            stopaj += amount
        elif code == KDV_TAX_CODE:
            kdv += amount
        else:
            other[code or "kodsuz"] = other.get(code or "kodsuz", Decimal("0")) + amount
    withholding = sum((_dec(_text(t, "tevkifatTutari")) for t in _kids(vergi, "tevkifat")), Decimal("0"))

    m = ParsedMakbuz(
        kind="serbest_meslek",
        number=_text(smm, "makbuzNo"),
        uuid=_text(smm, "ETTN"),
        issue_date=_date(_text(smm, "belgeTarihi")),
        currency=_text(smm, "paraBirimi") or "TRY",
        issuer=professional, counterparty=client, payer=client, payee=professional,
        gross=_dec(_text(smm, "toplamTutar")),
        kdv=kdv, stopaj=stopaj, other_taxes=other, withholding=withholding,
        payable=_dec(_text(smm, "odenecekTutar")),
        items=[
            name for mh in _kids(_kid(smm, "malHizmetBilgisi"), "malHizmet")
            if (name := _text(mh, "ad"))
        ],
    )
    m.direction, m.direction_basis = _side(own_vkn, m.payer, m.payee)
    m.suggested_tdhp_entries, m.posting_note = _entries(m)
    return m


def parse_makbuz(xml_content: str | bytes, *, own_vkn: str = "") -> ParsedMakbuz:
    """Read an e-Müstahsil or e-SMM. Raises NotAMakbuzError for anything else."""
    raw = xml_content.encode("utf-8") if isinstance(xml_content, str) else xml_content
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise NotAMakbuzError(f"XML okunamadı: {exc}") from exc
    if root.tag == CREDIT_NOTE_ROOT:
        return _parse_mustahsil(root, own_vkn)
    if root.tag == EARSIV_ROOT:
        return _parse_smm(root, own_vkn)
    raise NotAMakbuzError(f"kök eleman {root.tag!r} — ne e-Müstahsil ne e-SMM")
