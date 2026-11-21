"""One journal result from the per-currency runs (see `services/accounting/currency_runs`)."""
from __future__ import annotations

from typing import Any

from app.agents.accounting.orchestrator import MuhasebeSonucu
from app.core.currency_totals import DEFAULT_BASE, normalise
from app.services.accounting.currency_runs import balance_by_currency


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
