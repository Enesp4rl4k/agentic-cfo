"""A journal is kept per currency: one run per currency, merged without mixing them.

A yevmiye entry is balanced inside itself, so a journal of entries in several currencies is balanced per
currency; what must never happen is a trial balance (mizan) or a total adding USD to TRY. No exchange rate
is kept (`core/currency_totals`), so rows in another currency are NOT dropped from what the accountant sees:
every entry is tagged `para_birimi`, the accountant's packet lists all of them with a total per currency,
and only the statutory outputs (mizan, e-Defter, the journal tables) are restricted to the primary
currency, with the left-out count said (`entries_of`).
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.agents.accounting.orchestrator import MuhasebeSonucu
from app.core.currency_totals import DEFAULT_BASE, normalise, split_by_currency


def groups_by_currency(rows: Iterable[Any], primary: str) -> dict[str, list[Any]]:
    """Rows per currency, the primary currency first (it may be absent)."""
    primary = normalise(primary) or DEFAULT_BASE
    mine, other = split_by_currency(rows, primary)
    out: dict[str, list[Any]] = {primary: mine} if mine else {}
    out.update({c: other[c] for c in sorted(other)})
    return out


def balance_by_currency(entries: Iterable[dict[str, Any]], primary: str) -> dict[str, dict[str, Any]]:
    """{currency: {entries, toplam_borc, toplam_alacak, dengeli}} over tagged journal entries.

    An entry with no `para_birimi` (a journal saved before currencies were kept) belongs to `primary`.
    """
    primary = normalise(primary) or DEFAULT_BASE
    out: dict[str, dict[str, Any]] = {}
    for e in entries:
        cur = normalise(e.get("para_birimi")) or primary
        slot = out.setdefault(cur, {"kayit_sayisi": 0, "toplam_borc": 0, "toplam_alacak": 0})
        slot["kayit_sayisi"] += 1
        lines = e.get("satirlar")
        if lines is not None:
            slot["toplam_borc"] += sum(int(x.get("borc") or 0) for x in lines)
            slot["toplam_alacak"] += sum(int(x.get("alacak") or 0) for x in lines)
        else:
            slot["toplam_borc"] += int(e.get("toplam_borc") or 0)
            slot["toplam_alacak"] += int(e.get("toplam_alacak") or 0)
    for slot in out.values():
        slot["dengeli"] = slot["toplam_borc"] == slot["toplam_alacak"]
    return out


def merge_runs(runs: dict[str, MuhasebeSonucu], primary: str) -> MuhasebeSonucu:
    """One result from the per-currency runs; nothing from different currencies is added together
    except counts. `mizan` is the primary currency's; every currency's is in `mizan_para_birimi`."""
    primary = normalise(primary) or DEFAULT_BASE
    first = next(iter(runs.values()))
    lead_key = primary if primary in runs else next(iter(runs))
    lead = runs[lead_key]
    entries: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []
    errors: list[str] = []
    thp: dict[str, int] = {}
    mizan_by: dict[str, Any] = {}
    for cur, run in runs.items():
        for e in run.yevmiye_kayitlari:
            entries.append({**e, "para_birimi": cur})
        for item in run.onay_kuyrugu:
            queue.append({**item, "para_birimi": cur})
        errors += [f"[{cur}] {h}" for h in run.denge_hatalari]
        for code, n in run.thp_dagilim.items():
            thp[code] = thp.get(code, 0) + n
        mizan_by[cur] = run.mizan
    islem = sum(r.islem_sayisi for r in runs.values())
    weighted = sum(r.ortalama_confidence * r.islem_sayisi for r in runs.values())
    balance = balance_by_currency(entries, primary)
    return MuhasebeSonucu(
        job_id=first.job_id,
        islem_sayisi=islem,
        kayit_sayisi=len(entries),
        onay_bekleyen=sum(r.onay_bekleyen for r in runs.values()),
        dengeli=all(r.dengeli for r in runs.values()) and all(b["dengeli"] for b in balance.values()),
        denge_hatalari=errors,
        mizan=lead.mizan,
        thp_dagilim=thp,
        ortalama_confidence=weighted / islem if islem else 0.0,
        dusuk_confidence_sayisi=sum(r.dusuk_confidence_sayisi for r in runs.values()),
        yevmiye_kayitlari=entries,
        onay_kuyrugu=queue,
        tamamlanma_zamani=lead.tamamlanma_zamani,
        hata=lead.hata,
        birincil_para_birimi=lead_key,
        para_birimleri=balance,
        mizan_para_birimi=mizan_by,
    )


def entries_of(
    entries: Iterable[dict[str, Any]], currency: str | None
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """(entries in `currency`, how many were left out per other currency). An untagged entry (a journal
    saved before currencies were kept) is in `currency`. `currency` None keeps everything."""
    if not currency:
        return list(entries), {}
    cur = normalise(currency)
    kept: list[dict[str, Any]] = []
    left: dict[str, int] = {}
    for e in entries:
        code = normalise(e.get("para_birimi")) or cur
        if code == cur:
            kept.append(e)
        else:
            left[code] = left.get(code, 0) + 1
    return kept, left
