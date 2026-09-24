"""What is this file? Decided from its columns, and said plainly when it cannot be.

A file is a candidate for a type when it has every required column of that
type's schema. Among candidates, the one that accounts for more of the file's
columns wins. When two candidates explain the file equally well the answer is
"belirsiz" and both are offered: the person picks, nothing is guessed.

There is no confidence percentage. A recognition is `kesin` (one type clearly
fits), `belirsiz` (more than one fits equally), or `taninmadi` — with the
closest type and the columns it would still need.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any

from app.core.turkish import fold
from app.services.ingest import schemas as S
from app.services.ingest.table import (
    OkunamayanDosya,
    Tablo,
    anahtar,
    bos,
    satirlari_oku,
    sayi,
    tabloyu_bul,
    tarih,
)

KESIN = "kesin"
BELIRSIZ = "belirsiz"
TANINMADI = "taninmadi"

FINANSAL_BELGE = "finansal_belge"   # PDF / XML: bank statement or e-document, read by the CFO pipeline
GIT_LOG = "git_log"

# alias key → canonical, per schema; and every alias any schema knows
_ESLER: dict[str, dict[str, str]] = {
    s.tur: {anahtar(e): a.ad for a in s.alanlar for e in a.esler} for s in S.SEMALAR
}
BILINEN: set[str] = {k for m in _ESLER.values() for k in m}
# (type, header key) → the column is monthly and is written as a year
_AYLIK: set[tuple[str, str]] = {(s.tur, anahtar(e)) for s in S.SEMALAR for a in s.alanlar for e in a.aylik}
_KATEGORI: dict[str, str] = {fold(tr): en for tr, en in S.KATEGORI_DEGERLERI.items()}


@dataclass
class Aday:
    tur: str
    alan: str
    etiket: str
    eslesen: dict[str, str]          # canonical column → the file's header
    eksik: list[str]                 # required columns not found (for the closest miss)
    aciklanan: int                   # how many of the file's columns this type accounts for

    def to_dict(self) -> dict[str, Any]:
        return {"tur": self.tur, "alan": self.alan, "etiket": self.etiket,
                "eslesen": self.eslesen, "eksik": self.eksik}


@dataclass
class Tanima:
    durum: str                                   # kesin | belirsiz | taninmadi
    tur: str | None = None
    alan: str | None = None
    etiket: str | None = None
    adaylar: list[Aday] = field(default_factory=list)
    satir_sayisi: int = 0
    sayfa: str | None = None
    ozet: str = ""
    tablo: Tablo | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "durum": self.durum, "tur": self.tur, "alan": self.alan, "etiket": self.etiket,
            "adaylar": [a.to_dict() for a in self.adaylar], "satir_sayisi": self.satir_sayisi,
            "sayfa": self.sayfa, "ozet": self.ozet,
            "sutunlar": self.tablo.basliklar if self.tablo else [],
        }


def _eslestir(sema: S.Sema, basliklar: list[str]) -> Aday:
    esler = _ESLER[sema.tur]
    eslesen: dict[str, str] = {}
    for h in basliklar:
        ad = esler.get(anahtar(h)) if h else None
        if ad and ad not in eslesen:
            eslesen[ad] = h
    eksik = [a.ad for a in sema.alanlar if a.zorunlu and a.ad not in eslesen]
    if sema.en_az_biri and not any(a in eslesen for a in sema.en_az_biri):
        eksik.append(" / ".join(sema.en_az_biri))
    return Aday(sema.tur, sema.alan, sema.etiket, eslesen, eksik, len(eslesen))


def tabloyu_tani(tablo: Tablo) -> Tanima:
    adaylar = [_eslestir(s, tablo.basliklar) for s in S.SEMALAR]
    uyan = sorted((a for a in adaylar if not a.eksik), key=lambda a: -a.aciklanan)
    n = len(tablo.satirlar)
    if not uyan:
        yakin = sorted(adaylar, key=lambda a: (len(a.eksik), -a.aciklanan))[:2]
        en = yakin[0]
        return Tanima(
            TANINMADI, adaylar=yakin, satir_sayisi=n, sayfa=tablo.sayfa, tablo=tablo,
            ozet=(f"Dosya tanınamadı. En yakın tür '{en.etiket}', ama şu sütunlar bulunamadı: "
                  f"{', '.join(en.eksik)}. Sütun adlarını kontrol edin ya da türü kendiniz seçin."),
        )
    en_iyi = uyan[0]
    esit = [a for a in uyan if a.aciklanan == en_iyi.aciklanan]
    if len(esit) > 1:
        return Tanima(
            BELIRSIZ, adaylar=esit, satir_sayisi=n, sayfa=tablo.sayfa, tablo=tablo,
            ozet=("Bu dosya birden fazla türe uyuyor: " + " ya da ".join(f"'{a.etiket}'" for a in esit)
                  + ". Hangisi olduğunu seçin."),
        )
    ozet = f"{en_iyi.etiket} olarak tanındı: {n} kayıt, {len(en_iyi.eslesen)} sütun eşleşti."
    aylik = [h for h in en_iyi.eslesen.values() if (en_iyi.tur, anahtar(h)) in _AYLIK]
    if aylik:
        ozet += (f" '{', '.join(aylik)}' aylık tutar olarak okundu ve yıllığa çevrildi (×12); "
                 "tutarlar yıllıksa başlığa 'Yıllık' ekleyin.")
    return Tanima(
        KESIN, tur=en_iyi.tur, alan=en_iyi.alan, etiket=en_iyi.etiket, adaylar=uyan[:3],
        satir_sayisi=n, sayfa=tablo.sayfa, tablo=tablo, ozet=ozet,
    )


def _git_log_mu(veri: bytes) -> bool:
    bas = veri[:4000].decode("utf-8", errors="ignore")
    return bas.lstrip().startswith("commit ") and "\nAuthor:" in bas


# An XML namespace identifier, never fetched: it must equal the string GİB's
# documents declare, scheme included.
EDEFTER_NS = "http://www.edefter.gov.tr"  # NOSONAR — namespace URI, not a network call
_EDEFTER_ADLARI = {"defter": "e-Defter (yevmiye / kebir)", "berat": "e-Defter beratı",
                   "defterraporu": "e-Defter raporu"}


def edefter_turu(veri: bytes) -> str | None:
    """The e-Defter document kind, decided by the root element — or None.

    A company's own journal and ledger arrive as XML the door accepted as a
    "financial document"; nothing reads them yet, so the analysis ended with
    no transactions and no word why. They are named at the door instead.
    """
    from app.core.xml_safety import UnsafeXMLError, parse_xml

    try:
        kok = parse_xml(veri)
    except (UnsafeXMLError, Exception):
        return None
    if not kok.tag.startswith("{" + EDEFTER_NS + "}"):
        return None
    return _EDEFTER_ADLARI.get(kok.tag.split("}", 1)[1], "e-Defter belgesi")


def tani(veri: bytes, dosya_adi: str) -> Tanima:
    """Recognise a file from its bytes and name."""
    uzanti = dosya_adi.rsplit(".", 1)[-1].lower() if "." in dosya_adi else ""
    if uzanti in ("pdf", "xml"):
        return Tanima(KESIN, tur=FINANSAL_BELGE, alan="cfo", etiket="Finansal belge (ekstre / fatura)",
                      ozet="Finansal belge: banka ekstresi, e-Fatura ya da makbuz olarak okunacak.")
    if uzanti in ("txt", "log") and _git_log_mu(veri):
        return Tanima(KESIN, tur=GIT_LOG, alan="cto", etiket="Kod geçmişi (git log)",
                      ozet="Kod geçmişi (git log) olarak tanındı.")
    try:
        sayfalar = satirlari_oku(veri, uzanti)
    except OkunamayanDosya as exc:
        return Tanima(TANINMADI, ozet=str(exc))

    sonuclar: list[Tanima] = []
    for ad, rows in sayfalar:
        tablo = tabloyu_bul(rows, BILINEN, sayfa=ad)
        if tablo is not None:
            sonuclar.append(tabloyu_tani(tablo))
    if not sonuclar:
        return Tanima(TANINMADI, ozet=(
            "Dosyada tanıdık bir sütun başlığı bulunamadı. İlk satırlarda 'Tarih', 'Açıklama', "
            "'Ad Soyad', 'Kampanya' gibi başlıkların olduğu bir liste yükleyin."))
    sira = {KESIN: 0, BELIRSIZ: 1, TANINMADI: 2}
    # A workbook: the sheet that is most clearly something, then the one with the most rows.
    return sorted(sonuclar, key=lambda t: (sira[t.durum], -t.satir_sayisi))[0]


def tabloyu_sec(veri: bytes, dosya_adi: str, tur: str) -> Tablo | None:
    """The table in the file for a type the person chose (or recognition settled)."""
    uzanti = dosya_adi.rsplit(".", 1)[-1].lower() if "." in dosya_adi else ""
    sema = S.SEMA_BY_TUR.get(tur)
    if sema is None:
        return None
    bilinen = set(_ESLER[tur])
    best: Tablo | None = None
    for ad, rows in satirlari_oku(veri, uzanti):
        t = tabloyu_bul(rows, bilinen, sayfa=ad)
        if t and (best is None or _eslestir(sema, t.basliklar).aciklanan > _eslestir(sema, best.basliklar).aciklanan):
            best = t
    return best


# ── Normalisation ───────────────────────────────────────────────────────────

def _deger(alan: S.Alan, v: Any, carpan: int = 1) -> Any:
    if bos(v):
        return ""
    if alan.tur == S.SAYI:
        n = sayi(v)
        if n is None:
            return str(v).strip()
        n *= carpan
        return int(n) if n.is_integer() and abs(n) < 1e15 else round(n, 6)
    if alan.tur == S.TARIH:
        return tarih(v) or str(v).strip()
    if alan.tur == S.KATEGORI:
        k = str(v).strip().lower()
        return _KATEGORI.get(fold(k), k)
    if alan.tur == S.EVET_HAYIR:
        k = str(v).strip().lower()
        return "yes" if k in S.EVET else "no" if k in S.HAYIR else k
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def standart_csv(tablo: Tablo, tur: str) -> tuple[str, dict[str, str]]:
    """The table as the domain parser reads it: its column names, plain numbers, ISO dates.

    Columns the schema does not know are kept under their own names, so nothing
    the person uploaded is dropped. Returns the CSV and the column mapping used.
    """
    sema = S.SEMA_BY_TUR[tur]
    esler = _ESLER[tur]
    alan_by_ad = {a.ad: a for a in sema.alanlar}
    cikis: list[tuple[int, str, S.Alan | None, int]] = []
    kullanilan: set[str] = set()
    eslesme: dict[str, str] = {}
    for i, h in enumerate(tablo.basliklar):
        ad = esler.get(anahtar(h)) if h else None
        if ad and ad not in kullanilan:
            kullanilan.add(ad)
            eslesme[ad] = h
            cikis.append((i, ad, alan_by_ad[ad], 12 if (tur, anahtar(h)) in _AYLIK else 1))
        elif h:
            cikis.append((i, h, None, 1))

    signed_amount = tur == S.BANKA_EKSTRESI and "tutar" not in kullanilan and (
        "borç" in kullanilan or "alacak" in kullanilan)

    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow([ad for _, ad, _, _ in cikis] + (["tutar"] if signed_amount else []))
    for row in tablo.satirlar:
        vals = [(_deger(a, row[i], k) if a else ("" if bos(row[i]) else str(row[i]).strip()))
                for i, _, a, k in cikis]
        if signed_amount:
            # Debit is money leaving the account, credit money arriving; one
            # signed amount is what the statement parser reads.
            by = {ad: row[i] for i, ad, _, _ in cikis}
            borc, alacak = sayi(by.get("borç")), sayi(by.get("alacak"))
            tutar = -abs(borc) if borc else (abs(alacak) if alacak else None)
            vals.append("" if tutar is None else (int(tutar) if tutar.is_integer() else round(tutar, 2)))
        w.writerow(vals)
    return out.getvalue(), eslesme
