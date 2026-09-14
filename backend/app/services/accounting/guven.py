"""Güven — bir kaydın neden güvenilir ya da güvenilmez olduğu, ölçülerek.

The classifier used to report `confidence = min(1, score / 3) * 0.9`: keyword
weights run through arithmetic. "%30 güven" on the approval queue was that
number. It was not a probability of anything, so a reviewer could not know
what it meant, and the gate that held entries below 0.6 was deciding on it.

This module replaces the number with two things a person can use:

- **A level, named for its evidence.** A multi-word phrase matched exactly is
  different evidence from one word, which is different from a word fragment,
  which is different from an LLM's guess or no match at all. The level says
  which one happened, and `kanit` says what was matched.

- **A measured accuracy for that level.** Each level's hit rate is measured —
  on the calibration corpus to begin with, and on the organisation's own SMMM
  decisions once there are enough of them (an approved entry was right, a
  corrected one was wrong). The confidence number is the 95% Wilson lower bound
  of that rate: a level measured on six examples cannot look as trustworthy as
  one measured on sixty, even if both were all correct.

So "%30" becomes, for example, "Tek kelime eşleşmesi — 'kira' → 770 · test
setinde 26/29 doğru", and the number under it is honest about how much
evidence stands behind it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# Levels, strongest evidence first. Keys are stored in journals and onay
# records; labels are what a reviewer reads.
GUCLU_KURAL = "guclu_kural"
KURAL = "kural"
ZAYIF_KURAL = "zayif_kural"
LLM = "llm"
VARSAYILAN = "varsayilan"

SEVIYELER: dict[str, dict[str, str]] = {
    GUCLU_KURAL: {
        "etiket": "Güçlü eşleşme",
        "aciklama": "Açıklamada birden çok kelimelik bir hesap ifadesi birebir geçiyor.",
        "kontrol": "Genellikle doğru; tutar ve dönemi kontrol edin.",
    },
    KURAL: {
        "etiket": "Tek kelime eşleşmesi",
        "aciklama": "Açıklamada hesaba işaret eden tek bir kelime geçiyor.",
        "kontrol": "Kelime başka bir anlamda kullanılmış olabilir; belgeye bakın.",
    },
    ZAYIF_KURAL: {
        "etiket": "Zayıf eşleşme",
        "aciklama": "Hesap kelimesi başka bir kelimenin içinde geçiyor.",
        "kontrol": "Sık yanılır; hesabı belgeden doğrulayın.",
    },
    LLM: {
        "etiket": "Yapay zekâ tahmini",
        "aciklama": "Hiçbir kural eşleşmedi; hesabı dil modeli önerdi.",
        "kontrol": "İsabeti ölçülmedi; her kaydı belgeden doğrulayın.",
    },
    VARSAYILAN: {
        "etiket": "Sınıflandırılamadı",
        "aciklama": "Hiçbir kural eşleşmedi; kayıt genel hesaba atandı.",
        "kontrol": "Hesap bir tahmin bile değil; mutlaka belgeden seçin.",
    },
}

# Measured by `tests/test_guven_kalibrasyon.py` over
# `tests/fixtures/tr_corpus/thp_calibration.py` — (correct, total) per level.
# That test recomputes these and fails if they differ, so the table cannot
# describe a classifier that no longer exists. Levels that cannot be measured
# offline (the LLM needs a live key; the default is not evidence) are (0, 0).
KORPUS_OLCUMU: dict[str, tuple[int, int]] = {
    GUCLU_KURAL: (11, 11),
    KURAL: (26, 29),
    ZAYIF_KURAL: (9, 9),
    LLM: (0, 0),
    VARSAYILAN: (0, 0),
}

# Below this many of its own decisions, an organisation's history is too thin
# to replace the corpus measurement.
GECMIS_ESIGI = 20


def wilson_alt_sinir(dogru: int, toplam: int, z: float = 1.96) -> float:
    """95% Wilson lower bound of a hit rate. 0.0 when nothing was measured."""
    if toplam <= 0:
        return 0.0
    p = dogru / toplam
    denom = 1 + z * z / toplam
    centre = p + z * z / (2 * toplam)
    margin = z * math.sqrt(p * (1 - p) / toplam + z * z / (4 * toplam * toplam))
    return max(0.0, (centre - margin) / denom)


@dataclass(frozen=True)
class Guven:
    """How far to trust one classification, and why."""

    seviye: str
    kanit: str
    dogru: int
    toplam: int
    kaynak: str          # "korpus" | "kurum" | "olculmedi"

    @property
    def skor(self) -> float:
        return round(wilson_alt_sinir(self.dogru, self.toplam), 3)

    @property
    def olcum_metni(self) -> str:
        if self.toplam == 0:
            return "isabeti ölçülmedi"
        yer = "sizin onaylarınızda" if self.kaynak == "kurum" else "test setinde"
        return f"{yer} {self.dogru}/{self.toplam} doğru"

    def to_dict(self) -> dict[str, Any]:
        meta = SEVIYELER[self.seviye]
        return {
            "seviye": self.seviye,
            "etiket": meta["etiket"],
            "aciklama": meta["aciklama"],
            "kontrol": meta["kontrol"],
            "kanit": self.kanit,
            "dogru": self.dogru,
            "toplam": self.toplam,
            "kaynak": self.kaynak,
            "olcum": self.olcum_metni,
            "skor": self.skor,
        }


def degerlendir(
    seviye: str,
    kanit: str,
    gecmis: dict[str, tuple[int, int]] | None = None,
) -> Guven:
    """The trust for a classification at `seviye`.

    The organisation's own record for the level is used once it has at least
    `GECMIS_ESIGI` decisions; before that, the corpus measurement.
    """
    kendi = (gecmis or {}).get(seviye)
    if kendi and kendi[1] >= GECMIS_ESIGI:
        return Guven(seviye, kanit, kendi[0], kendi[1], "kurum")
    dogru, toplam = KORPUS_OLCUMU.get(seviye, (0, 0))
    return Guven(seviye, kanit, dogru, toplam, "korpus" if toplam else "olculmedi")


def gecmisten_olc(
    kararlar: list[tuple[str | None, str]] | list[tuple[str | None, str, bool]],
) -> dict[str, tuple[int, int]]:
    """Hit rate per level from SMMM decisions: (level, durum[, toplu]) tuples.

    `onaylandi` counts as correct and `duzeltildi` as wrong. Rejections are left
    out: a rejected entry may be refused for its amount or date, which says
    nothing about whether the account was right. Pending entries have no
    verdict yet. Bulk approvals are left out too: clearing a page of the queue
    at once is not a judgement on each account, and counting it would let the
    system earn trust from its own unexamined output.
    """
    out: dict[str, list[int]] = {}
    for karar in kararlar:
        seviye, durum = karar[0], karar[1]
        if len(karar) > 2 and karar[2]:
            continue
        if not seviye or seviye not in SEVIYELER:
            continue
        if durum == "onaylandi":
            out.setdefault(seviye, [0, 0])
            out[seviye][0] += 1
            out[seviye][1] += 1
        elif durum == "duzeltildi":
            out.setdefault(seviye, [0, 0])
            out[seviye][1] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}
