"""Read a trial balance (mizan): the accounts, whether the books balance, what it says.

A mizan lists every account with its total debit and credit and the balance that
leaves. This reads it, checks it, and summarises the income-statement side. It
does NOT turn it into ledger rows: a mizan is a snapshot of balances, usually
cumulative from 1 January, and booking one as movements would count the months
before it twice. That waits for a real sample and a decision about periods.

Nothing here is invented: the period is not guessed (the table reader drops the
title rows it sits in, so it says "unknown"), an income-statement account the
chart map does not know is listed rather than assigned, and a parent row (100)
is dropped from the totals only when the rows beneath it add up to it exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.core import tdhp
from app.services.ingest import schemas as S
from app.services.ingest.table import Tablo, anahtar, bos, sayi

_KOD = re.compile(r"^\d{3}[\d.\- ]*$")


@dataclass(frozen=True)
class MizanHesap:
    kod: str
    ad: str
    borc_kurus: int
    alacak_kurus: int
    borc_bakiye_kurus: int
    alacak_bakiye_kurus: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "kod": self.kod, "ad": self.ad,
            "borc_kurus": self.borc_kurus, "alacak_kurus": self.alacak_kurus,
            "borc_bakiye_kurus": self.borc_bakiye_kurus,
            "alacak_bakiye_kurus": self.alacak_bakiye_kurus,
        }


@dataclass
class MizanOzeti:
    hesaplar: list[MizanHesap] = field(default_factory=list)
    ust_hesap_atlanan: int = 0
    toplam_borc_kurus: int = 0
    toplam_alacak_kurus: int = 0
    # None when the file has no such columns: unknown is not "balanced".
    dengeli: bool | None = None
    bakiye_dengeli: bool | None = None
    fark_kurus: int = 0                       # debit minus credit
    gelir_tablosu: dict[str, int] = field(default_factory=dict)
    taninmayan_hesaplar: list[str] = field(default_factory=list)
    uyarilar: list[str] = field(default_factory=list)
    donem: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "hesap_sayisi": len(self.hesaplar),
            "ust_hesap_atlanan": self.ust_hesap_atlanan,
            "toplam_borc_kurus": self.toplam_borc_kurus,
            "toplam_alacak_kurus": self.toplam_alacak_kurus,
            "dengeli": self.dengeli,
            "bakiye_dengeli": self.bakiye_dengeli,
            "fark_kurus": self.fark_kurus,
            "gelir_tablosu": dict(self.gelir_tablosu),
            "taninmayan_hesaplar": list(self.taninmayan_hesaplar),
            "uyarilar": list(self.uyarilar),
            "donem": self.donem,
        }


def _kurus(v: Any) -> int:
    """Integer kuruş from a cell as written ("1.234.567,89"). Empty is zero."""
    n = sayi(v)
    return 0 if n is None else int((Decimal(str(n)) * 100).to_integral_value())


def _sutunlar(basliklar: list[str]) -> dict[str, int]:
    esler = {anahtar(e): a.ad for a in S.SEMA_BY_TUR[S.MIZAN].alanlar for e in a.esler}
    bulunan: dict[str, int] = {}
    for i, h in enumerate(basliklar):
        ad = esler.get(anahtar(h)) if h else None
        if ad and ad not in bulunan:
            bulunan[ad] = i
    return bulunan


def _hucre(satir: list[Any], i: int | None) -> Any:
    return satir[i] if i is not None and i < len(satir) else None


def mizan_oku(tablo: Tablo) -> MizanOzeti:
    kolon = _sutunlar(tablo.basliklar)
    ozet = MizanOzeti()
    hareket_var = "borç" in kolon or "alacak" in kolon
    bakiye_var = "borç bakiye" in kolon or "alacak bakiye" in kolon

    satirlar: list[MizanHesap] = []
    atlanan = 0
    for r in tablo.satirlar:
        ham = _hucre(r, kolon.get("hesap kodu"))
        kod = "" if bos(ham) else str(ham).strip()
        if not _KOD.match(kod):
            atlanan += 1  # a group heading, a note: not an account
            continue
        ad = _hucre(r, kolon.get("hesap adı"))
        satirlar.append(MizanHesap(
            kod=kod, ad="" if bos(ad) else str(ad).strip(),
            borc_kurus=_kurus(_hucre(r, kolon.get("borç"))),
            alacak_kurus=_kurus(_hucre(r, kolon.get("alacak"))),
            borc_bakiye_kurus=_kurus(_hucre(r, kolon.get("borç bakiye"))),
            alacak_bakiye_kurus=_kurus(_hucre(r, kolon.get("alacak bakiye"))),
        ))

    yaprak, ust = _ust_hesaplari_ayir(satirlar, ozet)
    ozet.hesaplar = yaprak
    ozet.ust_hesap_atlanan = ust

    if hareket_var:
        ozet.toplam_borc_kurus = sum(h.borc_kurus for h in yaprak)
        ozet.toplam_alacak_kurus = sum(h.alacak_kurus for h in yaprak)
        ozet.fark_kurus = ozet.toplam_borc_kurus - ozet.toplam_alacak_kurus
        ozet.dengeli = ozet.fark_kurus == 0
        if not ozet.dengeli:
            ozet.uyarilar.append(
                f"Borç ve alacak toplamları dengeli değil: fark {_tl(ozet.fark_kurus)}. "
                "Dosya eksik ya da bozuk olabilir; müşavire danışın."
            )
    if bakiye_var:
        b = sum(h.borc_bakiye_kurus for h in yaprak)
        a = sum(h.alacak_bakiye_kurus for h in yaprak)
        ozet.bakiye_dengeli = b == a
        if not ozet.bakiye_dengeli:
            ozet.uyarilar.append(f"Borç ve alacak bakiyeleri dengeli değil: fark {_tl(b - a)}.")
        if not hareket_var:
            ozet.fark_kurus = b - a

    _gelir_tablosu(ozet, yaprak, bakiye_var)
    if atlanan:
        ozet.uyarilar.append(f"{atlanan} satır hesap kodu taşımadığı için okunmadı (başlık / not satırı).")
    ozet.uyarilar.append(
        "Dönem dosyadan okunamadı; mizan dönem bilgisi olmadan gösteriliyor. "
        "Kümülatif (yıl başından) mi dönem hareketi mi olduğunu ayrıca bilmek gerekir."
    )
    return ozet


def _ust_hesaplari_ayir(
    satirlar: list[MizanHesap], ozet: MizanOzeti
) -> tuple[list[MizanHesap], int]:
    """Drop a parent row from the totals only when the rows under it add up to it.

    "100" and "100.01 / 100.02" are one money counted twice if all are summed. But
    "100" and "10001" may be two accounts that merely share digits, so the
    relationship is read from the numbers: a row is a parent when it has leaf
    descendants (by code prefix) whose debit and credit sums equal its own.
    """
    kodlar = [h.kod for h in satirlar]
    yapraklar = {
        h.kod for h in satirlar
        if not any(k != h.kod and k.startswith(h.kod) for k in kodlar)
    }
    ust: set[str] = set()
    for h in satirlar:
        if h.kod in yapraklar:
            continue
        alt = [x for x in satirlar if x.kod in yapraklar and x.kod != h.kod and x.kod.startswith(h.kod)]
        tutuyor = (
            sum(x.borc_kurus for x in alt) == h.borc_kurus
            and sum(x.alacak_kurus for x in alt) == h.alacak_kurus
            and sum(x.borc_bakiye_kurus for x in alt) == h.borc_bakiye_kurus
            and sum(x.alacak_bakiye_kurus for x in alt) == h.alacak_bakiye_kurus
        )
        if tutuyor:
            ust.add(h.kod)
        else:
            ozet.uyarilar.append(
                f"'{h.kod}' hesabı ile altındaki hesapların toplamı tutmuyor; "
                "hepsi ayrı hesap sayıldı. Kontrol edin."
            )
    return [h for h in satirlar if h.kod not in ust], len(ust)


def _gelir_tablosu(ozet: MizanOzeti, hesaplar: list[MizanHesap], bakiye_var: bool) -> None:
    gelir = gider = 0
    for h in hesaplar:
        rol = tdhp.hesap(h.kod)
        ana = tdhp.ana_hesap(h.kod)
        if rol is None:
            if ana and ana[0] in "67":
                ozet.taninmayan_hesaplar.append(h.kod)  # reported, never guessed
            continue
        b, a = (h.borc_bakiye_kurus, h.alacak_bakiye_kurus) if bakiye_var else (h.borc_kurus, h.alacak_kurus)
        sonuc = tdhp.hareket(rol, b, a)
        if sonuc is None or rol.rol not in ("gelir", "gelir_indirimi", "gider"):
            continue
        tur, tutar = sonuc
        if tur == "income":
            gelir += tutar
        else:
            gider += tutar
    ozet.gelir_tablosu = {"gelir_kurus": gelir, "gider_kurus": gider, "net_kurus": gelir - gider}
    if ozet.taninmayan_hesaplar:
        ozet.uyarilar.append(
            "Gelir tablosu hesap planında bulunmayan hesaplar okunmadı: "
            + ", ".join(sorted(set(ozet.taninmayan_hesaplar))) + "."
        )


def _tl(kurus: int) -> str:
    """12345678 → "123.456,78 ₺" (Turkish separators)."""
    isaret = "-" if kurus < 0 else ""
    k = abs(kurus)
    tam, kes = divmod(k, 100)
    return f"{isaret}{tam:,}".replace(",", ".") + f",{kes:02d} ₺"


def ozet_metni(o: MizanOzeti) -> str:
    """What the person is told: what was read, whether it balances, and that nothing was booked."""
    parca = [f"Mizan okundu: {len(o.hesaplar)} hesap"]
    if o.dengeli is not None:
        parca.append(
            f"borç {_tl(o.toplam_borc_kurus)} / alacak {_tl(o.toplam_alacak_kurus)}"
            + (" (dengeli)" if o.dengeli else f" (DENGELİ DEĞİL, fark {_tl(o.fark_kurus)})")
        )
    g = o.gelir_tablosu
    if g:
        parca.append(f"gelir tablosu: gelir {_tl(g['gelir_kurus'])}, gider {_tl(g['gider_kurus'])}")
    return (
        ", ".join(parca)
        + "; deftere işlenmedi — mizan bakiye özetidir ve yıl başından kümülatif olabilir, "
        "dönemi netleşmeden hareket olarak sayılırsa önceki aylar iki kez girer."
    )
