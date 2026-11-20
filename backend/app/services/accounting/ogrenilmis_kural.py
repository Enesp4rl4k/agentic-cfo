"""What the accountant corrects, the agent remembers.

A corrected account used to feed only the confidence calibration
(`guven.gecmisten_olc`). The same vendor came back next month classified by the
same keyword, wrong the same way. This turns a person's repeated corrections of
one recurring description into a rule for that organisation.

The rules of the rules:

* **One correction is not a rule**, it could be a one-off. Two consistent ones are
  (`ESIK`).
* **A conflict switches it off**, it does not pick a side: if the accountant has
  corrected the same key to two accounts and neither clearly leads (the leader
  needs three times the other's count), there is no rule.
* **Only a person's single correction teaches.** A bulk approval is not a
  judgement on each account and never reaches this module (see
  `guven.gecmisten_olc` for the same reason).
* **A rule is a suggestion with a measured track record, not a verdict.** Its
  evidence level (`guven.OGRENILMIS`) has no corpus measurement, so until the
  organisation has enough of its own decisions at that level the entry is still
  held for review, account already filled in. Approvals and corrections then
  measure it, and trust is earned from that measurement, not assumed.
* Rules belong to one organisation. The source's own account still wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.turkish import fold
from app.models.smmm_hesap_kurali import SMMMHesapKurali

# Corrections of one key to one account before it counts as a rule.
ESIK = 2
# A leader must out-count the strongest rival by this factor, else no rule.
USTUNLUK = 3
_EN_FAZLA_KELIME = 5
_EN_AZ_UZUNLUK = 3

_AYLAR = {
    "ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul",
    "ekim", "kasim", "aralik",
}
_GURULTU = {"no", "nolu", "sayili", "tarihli", "fatura", "fis", "ref", "adet"}


@dataclass(frozen=True)
class KurumKurali:
    anahtar: str
    hesap_kodu: str
    hesap_adi: str | None
    onay_sayisi: int


def anahtar_uret(description: str | None, vendor: str | None = None) -> str:
    """The normalised key a recurring description is recognised by; "" if none.

    A vendor is the best key. Otherwise the description with what changes every
    month removed (digits, dates, month names, document numbers): "Kira ödemesi
    Ocak 2026 No:123" and "KİRA ÖDEMESİ Şubat 2026 No:456" are the same key.
    """
    ham = vendor if (vendor or "").strip() else description
    t = fold(ham)
    t = re.sub(r"\d+([./-]\d+)*", " ", t)
    t = re.sub(r"[^a-z\s]", " ", t)
    kelimeler = [
        w for w in t.split()
        if len(w) >= 2 and w not in _AYLAR and w not in _GURULTU
    ]
    anahtar = " ".join(kelimeler[:_EN_FAZLA_KELIME])
    return anahtar if len(anahtar) >= _EN_AZ_UZUNLUK else ""


async def ogren(
    db: AsyncSession,
    org_id: str,
    description: str | None,
    vendor: str | None,
    hesap_kodu: str,
    hesap_adi: str | None = None,
) -> bool:
    """Record one correction of this description to `hesap_kodu`. False if it has no key.

    The caller commits.
    """
    anahtar = anahtar_uret(description, vendor)
    if not anahtar or not hesap_kodu:
        return False
    satir = (
        await db.execute(
            select(SMMMHesapKurali).where(
                SMMMHesapKurali.org_id == str(org_id),
                SMMMHesapKurali.anahtar == anahtar,
                SMMMHesapKurali.hesap_kodu == hesap_kodu,
            )
        )
    ).scalar_one_or_none()
    if satir is None:
        db.add(SMMMHesapKurali(
            org_id=str(org_id), anahtar=anahtar, hesap_kodu=hesap_kodu,
            hesap_adi=hesap_adi, onay_sayisi=1,
        ))
    else:
        satir.onay_sayisi += 1
        if hesap_adi:
            satir.hesap_adi = hesap_adi
    await db.flush()
    return True


def _gecerli(lider_sayisi: int, rakip_sayisi: int) -> bool:
    """Whether a key's leading account is a rule: enough corrections, a clear lead."""
    return lider_sayisi >= ESIK and lider_sayisi >= USTUNLUK * rakip_sayisi


async def satirlari_listele(db: AsyncSession, org_id: str | None) -> list[dict[str, object]]:
    """Everything learned for the organisation, and whether each is in force.

    For the accountant's screen: a key corrected once is listed too (not yet a
    rule), and a key with two contrary accounts shows neither in force.
    """
    if not org_id:
        return []
    satirlar = (
        await db.execute(select(SMMMHesapKurali).where(SMMMHesapKurali.org_id == str(org_id)))
    ).scalars().all()
    by_key: dict[str, list[SMMMHesapKurali]] = {}
    for s in satirlar:
        by_key.setdefault(s.anahtar, []).append(s)
    out: list[dict[str, object]] = []
    for anahtar, hepsi in sorted(by_key.items()):
        hepsi.sort(key=lambda s: -s.onay_sayisi)
        for i, s in enumerate(hepsi):
            rakip = hepsi[1].onay_sayisi if i == 0 and len(hepsi) > 1 else (hepsi[0].onay_sayisi if i else 0)
            out.append({
                "id": s.id, "anahtar": anahtar, "hesap_kodu": s.hesap_kodu,
                "hesap_adi": s.hesap_adi, "onay_sayisi": s.onay_sayisi,
                "aktif": i == 0 and _gecerli(s.onay_sayisi, rakip),
            })
    return out


async def kurallari_yukle(db: AsyncSession, org_id: str | None) -> dict[str, KurumKurali]:
    """The organisation's active rules: key → rule."""
    if not org_id:
        return {}
    satirlar = (
        await db.execute(select(SMMMHesapKurali).where(SMMMHesapKurali.org_id == str(org_id)))
    ).scalars().all()
    by_key: dict[str, list[SMMMHesapKurali]] = {}
    for s in satirlar:
        by_key.setdefault(s.anahtar, []).append(s)
    out: dict[str, KurumKurali] = {}
    for anahtar, hepsi in by_key.items():
        hepsi.sort(key=lambda s: -s.onay_sayisi)
        lider = hepsi[0]
        rakip = hepsi[1].onay_sayisi if len(hepsi) > 1 else 0
        if _gecerli(lider.onay_sayisi, rakip):
            out[anahtar] = KurumKurali(anahtar, lider.hesap_kodu, lider.hesap_adi, lider.onay_sayisi)
    return out


def kurum_sonucu(tx: dict, kurallar: dict[str, KurumKurali] | None):
    """The classification a learned rule gives a transaction; None if none applies."""
    if not kurallar:
        return None
    from app.services.accounting import guven
    from app.services.accounting.thp_classifier import THP_HESAPLARI, THPSonucu

    anahtar = anahtar_uret(tx.get("description"), tx.get("vendor"))
    kural = kurallar.get(anahtar) if anahtar else None
    if kural is None:
        return None
    tanim = THP_HESAPLARI.get(kural.hesap_kodu)
    if tanim is None:
        return None  # a code the chart does not know is not suggested
    return THPSonucu(
        hesap_kodu=kural.hesap_kodu,
        hesap_adi=tanim.adi,
        ana_grup=tanim.ana_grup,
        normal_bakiye=tanim.normal_bakiye,
        tip=tanim.tip,
        confidence=0.0,  # replaced by the measured trust of the level (guven.degerlendir)
        yontem="ogrenilmis",
        aciklama=f"Muhasebecinin önceki düzeltmesi: '{anahtar}' → {kural.hesap_kodu}",
        guven_seviyesi=guven.OGRENILMIS,
        kanit=f"önceki düzeltmeniz: '{anahtar}' → {kural.hesap_kodu} ({kural.onay_sayisi} kez)",
    )
