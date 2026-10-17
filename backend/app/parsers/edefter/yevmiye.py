"""
Yevmiye defterinden tahakkuk esaslı gelir tablosu satırları.

A Turkish company's journal (e-Defter, XBRL-GL) records every entry in
Tekdüzen Hesap Planı accounts. The income statement lives in the 6xx accounts
and, under the 7/A cost system, the 7x0 cost accounts. Reading those gives the
accrual picture an SMMM expects: a sale is income when invoiced, not when paid.
(The owner chose accrual; cash would read 100/102 instead.)

What is read, and what is not:

- Only the journal (`entriesType = journal`). The ledger (kebir) holds the same
  entries sorted by account — reading both would count everything twice — and
  the inventory book (envanter) holds balances, not movements.
- Income accounts (60x, 64x, 67x) count on the credit side; a debit on them is
  a correction and reduces income. Sales deductions (61x) reduce revenue.
- Expense accounts (62x, 63x, 65x, 66x, 68x, 691, and 7x0 under 7/A) count on
  the debit side; a credit on them is a correction and reduces the expense.
- Entries that touch a transfer account (7x1 "yansıtma", 798/799 under 7/B) are
  skipped whole: they move costs already counted in 7xx into 6xx, and counting
  both halves would double every expense.
- Closing entries (690, 692) are skipped whole: they reverse the period's income
  statement into profit.
- Balance-sheet accounts (1xx–5xx) are not income-statement events and are not
  read. An income-statement account this map does not know is reported, and
  holds the analysis for review rather than being guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.financial import amount_to_cents
from app.core.xml_safety import parse_xml

EDEFTER_NS = "http://www.edefter.gov.tr"  # NOSONAR — XML namespace URI, never fetched
_GL = "{http://www.xbrl.org/int/gl/cor/2006-10-25}"  # NOSONAR — XML namespace URI

# account main-code prefix → (type, category). Longest prefix wins.
_GELIR: dict[str, str] = {
    "600": "revenue", "601": "revenue", "602": "revenue",
    "610": "revenue", "611": "revenue", "612": "revenue",   # deductions: reduce revenue
    "64": "other_income", "67": "other_income",
}
_GIDER: dict[str, str] = {
    "62": "cogs",
    "630": "other_expense", "631": "marketing", "632": "other_expense",
    "65": "other_expense", "66": "other_expense", "68": "other_expense",
    "691": "tax",
    # 7/A cost accounts, before they are transferred into 6xx
    "710": "cogs", "720": "cogs", "730": "cogs", "740": "cogs",
    "750": "other_expense", "760": "marketing", "770": "other_expense", "780": "other_expense",
    # 7/B expense-by-nature accounts
    "790": "other_expense", "791": "other_expense", "792": "other_expense",
    "793": "other_expense", "794": "other_expense", "795": "other_expense",
    "796": "other_expense", "797": "other_expense",
}
# Sales deductions carry a debit balance: a debit reduces revenue.
_GELIR_INDIRIMI = ("610", "611", "612")
# Entries touching these are transfers or closings: skipped whole.
_YANSITMA = ("711", "721", "731", "741", "751", "761", "771", "781", "798", "799")
_KAPANIS = ("690", "692")


class NotAJournal(ValueError):
    """The document is an e-Defter, but not a journal this reader can use."""

    def __init__(self, tur: str) -> None:
        super().__init__(tur)
        self.tur = tur


@dataclass
class YevmiyeSonucu:
    islemler: list[dict[str, Any]]
    kayit_sayisi: int
    atlanan_kayit: int
    tanimsiz_hesaplar: list[str] = field(default_factory=list)
    donem: tuple[date, date] | None = None


def _eslestir(hesap: str, tablo: dict[str, str]) -> str | None:
    for uzunluk in (3, 2):
        kategori = tablo.get(hesap[:uzunluk])
        if kategori is not None:
            return kategori
    return None


def _defter_turu(kok: Any) -> str:
    tur = (kok.findtext(f".//{_GL}documentInfo/{_GL}entriesType") or "").strip()
    return tur or "bilinmiyor"


def yevmiye_oku(xml: bytes) -> YevmiyeSonucu:
    """Income-statement rows of a journal, on the accrual basis."""
    kok = parse_xml(xml)
    if not kok.tag.startswith("{" + EDEFTER_NS + "}"):
        raise NotAJournal("e-Defter değil")
    tur = _defter_turu(kok)
    if kok.tag != "{" + EDEFTER_NS + "}defter" or tur != "journal":
        raise NotAJournal(tur if kok.tag.endswith("}defter") else kok.tag.split("}", 1)[1])

    islemler: list[dict[str, Any]] = []
    tanimsiz: set[str] = set()
    kayitlar = atlanan = 0
    tarihler: list[date] = []

    for kayit in kok.iter(f"{_GL}entryHeader"):
        kayitlar += 1
        satirlar = list(kayit.iter(f"{_GL}entryDetail"))
        hesaplar = [(s.findtext(f"{_GL}account/{_GL}accountMainID") or "").strip() for s in satirlar]
        if any(h[:3] in _YANSITMA or h[:3] in _KAPANIS for h in hesaplar):
            atlanan += 1
            continue

        no = (kayit.findtext(f"{_GL}entryNumber") or "").strip()
        kayit_yorum = (kayit.findtext(f"{_GL}entryComment") or "").strip()
        kayit_tarihi = (kayit.findtext(f"{_GL}enteredDate") or "").strip()

        for satir, hesap in zip(satirlar, hesaplar, strict=True):
            if not hesap or hesap[0] not in "67":
                continue
            gelir = _eslestir(hesap, _GELIR)
            gider = _eslestir(hesap, _GIDER) if gelir is None else None
            if gelir is None and gider is None:
                tanimsiz.add(hesap[:3])
                continue

            try:
                tutar = Decimal((satir.findtext(f"{_GL}amount") or "0").strip())
            except InvalidOperation:
                tanimsiz.add(hesap[:3])
                continue
            borc = (satir.findtext(f"{_GL}debitCreditCode") or "").strip().upper() in ("D", "DEBIT")

            if gelir is not None:
                # Income grows on the credit side; deductions (61x) on the debit.
                artis = borc if hesap[:3] in _GELIR_INDIRIMI else not borc
                isaret = -1 if hesap[:3] in _GELIR_INDIRIMI else 1
                kurus = amount_to_cents(tutar) * (isaret if artis else -isaret)
                tip, kategori = "income", gelir
            elif gider is not None:
                kurus = amount_to_cents(tutar) * (1 if borc else -1)
                tip, kategori = "expense", gider
            else:  # pragma: no cover — excluded above; kept for the type checker
                continue

            tarih = (satir.findtext(f"{_GL}postingDate") or kayit_tarihi).strip()
            try:
                tarihler.append(date.fromisoformat(tarih[:10]))
            except ValueError:
                pass
            aciklama = (satir.findtext(f"{_GL}detailComment") or kayit_yorum).strip()
            islemler.append({
                "amount_cents": kurus,
                "currency": "TRY",
                "type": tip,
                "category": kategori,
                "description": f"Yevmiye {no}: {aciklama}" if aciklama else f"Yevmiye {no}",
                "vendor": None,
                "transaction_date": tarih[:10] or None,
                "raw_text": (f"e-Defter yevmiye | kayıt {no} | hesap {hesap} "
                             f"| {'borç' if borc else 'alacak'} {tutar} TL | tahakkuk esası"),
                "confidence": 0.95,
                "basis": "tahakkuk",
            })

    return YevmiyeSonucu(
        islemler=islemler,
        kayit_sayisi=kayitlar,
        atlanan_kayit=atlanan,
        tanimsiz_hesaplar=sorted(tanimsiz),
        donem=(min(tarihler), max(tarihler)) if tarihler else None,
    )
