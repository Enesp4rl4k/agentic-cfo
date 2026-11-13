"""The journal as the accountant (SMMM) left it — one source for every output.

The saved `tr_muhasebe_journal` report holds what the agent proposed. What the
accountant then did to it lives in `SMMMOnayKaydi`: approved, corrected to a
different account, or rejected. The e-Defter, the yevmiye dump and the mizan
each used to read one half of that: the first two the raw proposal (so a
rejected entry was still filed), the mizan only the reviewed rows (so every
auto-posted entry was missing) and it wrote a corrected account code onto
*every* line of an entry, bank side included.

`uygula` is the single place that decides which entries count and with which
account codes. D3 (one ledger) depends on nothing else computing this.

Rules:
- an entry the policy did not hold for review counts as it is;
- a held entry counts only once approved; corrected means the account the
  agent chose is replaced by the accountant's, on the lines that carry it and
  nowhere else;
- rejected and still-pending entries do not count. Pending is not "probably
  fine": a filing must not contain what nobody signed.
"""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.models.smmm_onay import OnayDurumu


@dataclass
class ApprovedJournal:
    entries: list[dict[str, Any]] = field(default_factory=list)
    # kayit_id -> why it is not in `entries`: "reddedildi" | "bekliyor"
    excluded: dict[str, str] = field(default_factory=dict)


def _durum(onay: Any) -> str:
    return str(getattr(onay, "durum", None) or "")


def uygula(entries: Iterable[dict[str, Any]], onaylar: Iterable[Any]) -> ApprovedJournal:
    """Apply the accountant's decisions to the proposed entries.

    `onaylar` are `SMMMOnayKaydi`-shaped (kayit_id, durum, otomatik_hesap_kodu,
    duzeltilmis_hesap_kodu, duzeltilmis_hesap_adi). Input is not mutated.
    """
    by_kayit = {str(o.kayit_id): o for o in onaylar}
    out = ApprovedJournal()
    for raw in entries:
        entry = deepcopy(raw)
        kayit_id = str(entry.get("kayit_id") or "")
        if not entry.get("onay_gerekli"):
            out.entries.append(entry)
            continue
        onay = by_kayit.get(kayit_id)
        durum = _durum(onay) if onay is not None else OnayDurumu.BEKLIYOR.value
        if durum == OnayDurumu.ONAYLANDI.value:
            out.entries.append(entry)
        elif durum == OnayDurumu.DUZELTILDI.value and onay is not None:
            _duzelt(entry, onay)
            out.entries.append(entry)
        elif durum == OnayDurumu.REDDEDILDI.value:
            out.excluded[kayit_id] = OnayDurumu.REDDEDILDI.value
        else:
            out.excluded[kayit_id] = OnayDurumu.BEKLIYOR.value
    return out


def _duzelt(entry: dict[str, Any], onay: Any) -> None:
    yeni = getattr(onay, "duzeltilmis_hesap_kodu", None)
    if not yeni:
        return
    eski = getattr(onay, "otomatik_hesap_kodu", None) or entry.get("thp_hesap_kodu")
    yeni_adi = getattr(onay, "duzeltilmis_hesap_adi", None)
    for satir in entry.get("satirlar") or []:
        # Only the line the agent classified. The counter-account (bank, cash,
        # 320 …) was not part of what the accountant corrected.
        if str(satir.get("hesap_kodu")) == str(eski):
            satir["hesap_kodu"] = yeni
            if yeni_adi:
                satir["hesap_adi"] = yeni_adi
    entry["thp_hesap_kodu"] = yeni


def mizan(entries: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Trial balance (kuruş) from already-applied entries."""
    out: dict[str, dict[str, Any]] = {}
    for entry in entries:
        for satir in entry.get("satirlar") or []:
            kod = str(satir.get("hesap_kodu") or "")
            row = out.setdefault(kod, {"hesap_adi": satir.get("hesap_adi") or "", "borc": 0, "alacak": 0})
            row["borc"] += int(satir.get("borc") or 0)
            row["alacak"] += int(satir.get("alacak") or 0)
    for row in out.values():
        row["bakiye"] = row["borc"] - row["alacak"]
    return out


async def yukle(db: Any, job_id: str) -> tuple[dict[str, Any], ApprovedJournal]:
    """Load the saved journal for a job and apply the accountant's decisions.

    Returns the raw journal (period, totals …) and the approved view of its
    entries. Raises `DefensibilityError` when no journal was saved.
    """
    from sqlalchemy import select

    from app.models.smmm_onay import SMMMOnayKaydi
    from app.services.smmm_defensibility import _load_journal

    journal = await _load_journal(db, job_id)
    onaylar = (
        (await db.execute(select(SMMMOnayKaydi).where(SMMMOnayKaydi.job_id == job_id)))
        .scalars()
        .all()
    )
    return journal, uygula(journal.get("yevmiye_kayitlari") or [], onaylar)
