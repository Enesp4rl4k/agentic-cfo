"""
Çalışma sermayesi döngüsü — ölçülen değerlerden, formülüyle birlikte.

DSO, DPO, DIO and CCC are exact given a balance and a flow. The endpoint that
served this page ignored the figures the person typed and answered with four
constants (current_ratio 1.5, CCC 45 days, gap 150 000 TRY) for every company;
the page then read fields that answer did not contain. Here each number is
computed from the inputs and carries the formula it came from, so a reader can
check it.

No sector benchmark is returned: the benchmark tables in this project
(app/services/benchmark.py, TCMB/BDDK) carry margins and ratios, not DSO/DPO,
and a comparison we cannot source would be a made-up number in an audited
report.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

GUN = 365


@dataclass
class CalismaSermayesiGirdisi:
    alacaklar: float          # accounts receivable, TRY
    yillik_ciro: float        # annual revenue, TRY
    borclar: float            # accounts payable, TRY
    yillik_smm: float         # annual COGS, TRY
    stok: float = 0.0         # inventory, TRY


@dataclass
class Metrik:
    ad: str
    gun: float | None
    formul: str
    aciklama: str


@dataclass
class CalismaSermayesiSonucu:
    dso: Metrik
    dpo: Metrik
    dio: Metrik
    ccc: Metrik
    yorum: str
    eksik_girdiler: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def m(x: Metrik) -> dict[str, Any]:
            return {"ad": x.ad, "gun": None if x.gun is None else round(x.gun, 1),
                    "formul": x.formul, "aciklama": x.aciklama}
        return {
            "metrikler": {"dso": m(self.dso), "dpo": m(self.dpo), "dio": m(self.dio), "ccc": m(self.ccc)},
            "yorum": self.yorum,
            "eksik_girdiler": self.eksik_girdiler,
            "olcum": "hesaplandi",
            "sektor_karsilastirmasi": None,
            "sektor_karsilastirmasi_notu":
                "DSO/DPO için sektör ortalaması verimiz yok; karşılaştırma gösterilmiyor.",
        }


def _bol(pay: float, payda: float) -> float | None:
    if payda <= 0:
        return None
    return pay / payda * GUN


def hesapla(g: CalismaSermayesiGirdisi) -> CalismaSermayesiSonucu:
    """Compute the cycle. A metric whose denominator is missing stays None —
    it is not filled with a guess, and the caller is told which input is missing."""
    eksik: list[str] = []
    if g.yillik_ciro <= 0:
        eksik.append("yıllık ciro")
    if g.yillik_smm <= 0:
        eksik.append("yıllık satılan malın maliyeti")

    dso_gun = _bol(g.alacaklar, g.yillik_ciro)
    dpo_gun = _bol(g.borclar, g.yillik_smm)
    dio_gun = _bol(g.stok, g.yillik_smm) if g.stok > 0 else 0.0

    dso = Metrik("DSO", dso_gun, "Alacaklar ÷ Yıllık ciro × 365",
                 "Kestiğiniz faturanın ortalama kaç günde tahsil edildiği.")
    dpo = Metrik("DPO", dpo_gun, "Borçlar ÷ Yıllık SMM × 365",
                 "Tedarikçinize ortalama kaç günde ödediğiniz.")
    dio = Metrik("DIO", dio_gun, "Stok ÷ Yıllık SMM × 365",
                 "Stoğun ortalama kaç gün elinizde kaldığı. Stok girilmediyse 0.")

    if dso_gun is None or dpo_gun is None:
        ccc_gun = None
        yorum = "Döngü hesaplanamadı: " + ", ".join(eksik) + " gerekli."
    else:
        ccc_gun = dso_gun + (dio_gun or 0.0) - dpo_gun
        if ccc_gun < 0:
            yorum = (f"Nakit döngünüz {abs(ccc_gun):.0f} gün negatif: tahsilatınız ödemenizden "
                     "önce geliyor, yani işletme sermayesini tedarikçiniz finanse ediyor.")
        elif ccc_gun > 60:
            yorum = (f"Nakit döngünüz {ccc_gun:.0f} gün. Tahsil ettiğiniz parayı bu kadar süre "
                     "beklemek zorundasınız; bu sürenin finansmanı sizde.")
        else:
            yorum = f"Nakit döngünüz {ccc_gun:.0f} gün."

    ccc = Metrik("CCC", ccc_gun, "DSO + DIO − DPO", "Paranın işletmede bağlı kaldığı gün sayısı.")
    return CalismaSermayesiSonucu(dso=dso, dpo=dpo, dio=dio, ccc=ccc, yorum=yorum, eksik_girdiler=eksik)
