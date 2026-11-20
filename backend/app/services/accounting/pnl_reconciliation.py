"""Does the CFO's P&L agree with the journal? And when not, where do they differ.

Two things describe the same transactions and have never been compared: the
P&L the CFO pipeline computes (`pnl_agent._compute_pnl`) and the journal the
accounting agent writes. Measured on one ordinary mix of six bank movements they
disagree by a lot: revenue 120.000 in the P&L, 0 in the journal.

That is mostly not a bug, and this module does not say it is. A bank movement is
cash: the P&L counts a customer payment as revenue. The journal books it as
settling a receivable (120), because the invoice is assumed to have been
booked already. Likewise a payment to a supplier (320), a tax payment (360) or a
loan instalment: expenses to the P&L, balance-sheet movements in the journal.
The two agree only when the source is invoices or an e-Defter, which are accrual.

So the comparison is itemised, not a pass/fail:

* KDV is moved out of the way first. The P&L sums the gross amount; the journal
  splits KDV onto 191/391. Journal income and cost are compared *with* it added
  back, so a clean split never shows up as a difference.
* Entries not in the approved journal (rejected, or still pending) are counted
  on their own line, because the P&L covers every transaction and the
  approved journal does not.
* Whatever is left is the difference, and the entries the journal booked to a
  balance-sheet account are listed beside it as the likely cause. They are
  candidates, not a diagnosis: without the transaction behind each entry the
  link is not certain.

Nothing here changes a figure or gates a run. It makes the gap visible.
"""

from __future__ import annotations

from typing import Any

from app.core import tdhp


def _entry_effect(entry: dict[str, Any]) -> tuple[int, int, int, int]:
    """(income, cost, KDV payable, KDV deductible) of one entry, in kuruş."""
    gelir = gider = kdv_h = kdv_i = 0
    for satir in entry.get("satirlar") or []:
        kod = str(satir.get("hesap_kodu") or "")
        borc, alacak = int(satir.get("borc") or 0), int(satir.get("alacak") or 0)
        ana = tdhp.ana_hesap(kod)
        if ana == "391":
            kdv_h += alacak - borc
        elif ana == "191":
            kdv_i += borc - alacak
        else:
            h = tdhp.hesap(kod)
            if h is not None and h.rol in ("gelir", "gelir_indirimi"):
                gelir += alacak - borc
            elif h is not None and h.rol == "gider":
                gider += borc - alacak
    return gelir, gider, kdv_h, kdv_i


def _totals(entries: list[dict[str, Any]]) -> dict[str, int]:
    t = {"gelir": 0, "gider": 0, "kdv_hesaplanan": 0, "kdv_indirilecek": 0}
    for e in entries:
        g, d, kh, ki = _entry_effect(e)
        t["gelir"] += g
        t["gider"] += d
        t["kdv_hesaplanan"] += kh
        t["kdv_indirilecek"] += ki
    # With KDV added back: what the gross amounts the P&L sums correspond to.
    t["gelir_brut"] = t["gelir"] + t["kdv_hesaplanan"]
    t["gider_brut"] = t["gider"] + t["kdv_indirilecek"]
    return t


def _bilanco_kayitlari(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entries whose classified account is a balance-sheet one (a settlement)."""
    out = []
    for e in entries:
        h = tdhp.hesap(str(e.get("thp_hesap_kodu") or ""))
        if h is not None and h.rol == "bilanco":
            out.append({
                "kayit_id": e.get("kayit_id"),
                "hesap": e.get("thp_hesap_kodu"),
                "aciklama": e.get("aciklama"),
                "tutar_kurus": int(e.get("toplam_borc") or 0),
            })
    return out


def uzlastir(
    pnl: dict[str, Any], onayli: list[dict[str, Any]], onaysiz: list[dict[str, Any]]
) -> dict[str, Any]:
    """P&L against the approved journal, with the unapproved entries on their own line.

    `pnl` is `_compute_pnl`'s output (`revenue`, `total_expenses`, kuruş); `onayli`
    the approved entries, `onaysiz` those left out (rejected or pending).
    """
    pnl_gelir = int(pnl.get("revenue") or 0)
    pnl_gider = int(pnl.get("total_expenses") or 0)
    a = _totals(onayli)
    u = _totals(onaysiz)

    fark_gelir = pnl_gelir - a["gelir_brut"] - u["gelir_brut"]
    fark_gider = pnl_gider - a["gider_brut"] - u["gider_brut"]
    bilanco = _bilanco_kayitlari(onayli)

    notlar: list[str] = []
    if fark_gelir or fark_gider:
        notlar.append(
            "K/Z ile yevmiye aynı işlemleri farklı tabanda gösteriyor: banka hareketi nakit esaslı "
            "(K/Z gelir ya da gider sayar), yevmiye tahsilat/ödemeyi bilanço hesabına yazar. "
            "Fark kalem kalem incelenmeli; kendiliğinden hata anlamına gelmez."
        )
    if bilanco:
        notlar.append(
            f"{len(bilanco)} kayıt bilanço hesabına yazıldı (alıcılar, satıcılar, ödenecek vergi…): "
            "farkın olası kaynağı; işlemin kendisi olmadan kesin değil."
        )
    if onaysiz and (u["gelir_brut"] or u["gider_brut"]):
        notlar.append(
            f"{len(onaysiz)} kayıt onaylı yevmiyede yok (reddedildi ya da bekliyor); "
            "K/Z bunları sayıyor."
        )

    return {
        "pnl": {"gelir_kurus": pnl_gelir, "gider_kurus": pnl_gider},
        "yevmiye_onayli": {
            "gelir_kurus": a["gelir_brut"], "gider_kurus": a["gider_brut"],
            "kdv_hesaplanan_kurus": a["kdv_hesaplanan"], "kdv_indirilecek_kurus": a["kdv_indirilecek"],
        },
        "yevmiye_onaysiz": {"gelir_kurus": u["gelir_brut"], "gider_kurus": u["gider_brut"],
                            "kayit_sayisi": len(onaysiz)},
        "fark": {"gelir_kurus": fark_gelir, "gider_kurus": fark_gider},
        "tutuyor": fark_gelir == 0 and fark_gider == 0,
        "bilanco_kayitlari": bilanco,
        "notlar": notlar,
    }
