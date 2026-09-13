"""Risk göstergeleri — yalnızca gerçekten ölçülmüş olanlar.

The risk kernel produced every KRI whether or not anything had been measured.
A missing runway became 12 months, a missing revenue growth became 0% — a
green KRI — and the people, technology and market KRIs came from the other
kernels' own estimates. Proactive alerts and the risk cascade were driven by
that list.

Two sources remain, both real:

- **The CFO report.** Runway, net margin and opex/revenue, each only when the
  report contains the figures it needs. The thresholds are the kernel's —
  policy, not data — and are named on each indicator.
- **The KRI file the organisation uploaded**, as the risk orchestrator parsed
  it: its own indicators, values and thresholds, with red/amber decided there.

A category maps to a cascade trigger only where the simulator has one.
"""
from __future__ import annotations

from typing import Any

# Uploaded KRI categories → cascade simulator triggers. Categories without a
# natural trigger are listed without one; nothing is forced into a scenario.
_KATEGORI_TETIK: dict[str, str] = {
    "financial": "cash_crisis", "finans": "cash_crisis",
    "people": "key_person_loss", "hr": "key_person_loss", "insan": "key_person_loss",
    "technology": "tech_outage", "cyber": "tech_outage", "teknoloji": "tech_outage",
    "compliance": "regulatory_breach", "uyum": "regulatory_breach", "regulatory": "regulatory_breach",
    "market": "market_shock", "pazar": "market_shock",
    "customer": "customer_churn_spike", "musteri": "customer_churn_spike",
}


def _status(value: float, amber: float, red: float, *, higher_is_worse: bool) -> str:
    if higher_is_worse:
        return "red" if value >= red else "amber" if value >= amber else "green"
    return "red" if value <= red else "amber" if value <= amber else "green"


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


# Trend and time-to-red are not measured from a single period, so every
# indicator carries them as unknown rather than as "stable".
_OLCULMEDI = {"trend": None, "trajectory_months": None}


def cfo_kri(pnl: dict[str, Any] | None, forecast: dict[str, Any] | None) -> list[dict[str, Any]]:
    pnl = pnl or {}
    out: list[dict[str, Any]] = []
    runway = _num((((forecast or {}).get("scenarios") or {}).get("base") or {}).get("runway_months"))
    if runway is not None:
        st = _status(runway, 6.0, 3.0, higher_is_worse=False)
        out.append({
            "name": "Nakit Ömrü", "category": "financial", "current_value": round(runway, 1), "unit": "ay",
            "threshold_amber": 6.0, "threshold_red": 3.0, "higher_is_worse": False,
            "status": st, "source": "CFO tahmini (baz senaryo)",
            "evidence": f"Baz senaryoda nakit ömrü {runway:.1f} ay",
            "cascade_trigger": "cash_crisis" if st != "green" else None,
            "cascade_params": {"runway_months": runway},
        })
    revenue = _num(pnl.get("revenue"))
    margin = _num(pnl.get("net_margin"))
    if revenue and margin is not None:
        pct = round(margin * 100, 1)
        st = _status(pct, 5.0, 0.0, higher_is_worse=False)
        out.append({
            "name": "Net Kâr Marjı", "category": "financial", "current_value": pct, "unit": "%",
            "threshold_amber": 5.0, "threshold_red": 0.0, "higher_is_worse": False,
            "status": st, "source": "CFO kâr-zarar",
            "evidence": f"Net marj %{pct}",
            "cascade_trigger": "revenue_drop" if pct < 0 else None,
            "cascade_params": {"drop_pct": abs(margin)} if margin < 0 else {},
        })
    opex = _num(pnl.get("total_opex"))
    if revenue and opex is not None:
        ratio = round(opex / revenue * 100, 1)
        st = _status(ratio, 90.0, 110.0, higher_is_worse=True)
        out.append({
            "name": "Gider / Gelir", "category": "financial", "current_value": ratio, "unit": "%",
            "threshold_amber": 90.0, "threshold_red": 110.0, "higher_is_worse": True,
            "status": st, "source": "CFO kâr-zarar",
            "evidence": f"Faaliyet gideri gelirin %{ratio}'i",
            "cascade_trigger": "cash_crisis" if ratio > 100 else None,
            "cascade_params": {"runway_months": runway} if runway is not None else {},
        })
    return out


def yuklenen_kri(risk_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    kris = (risk_result or {}).get("kris") or {}
    out: list[dict[str, Any]] = []
    for status, key in (("red", "breached_red"), ("amber", "breached_amber")):
        for k in kris.get(key) or []:
            if not isinstance(k, dict):
                continue
            cat = str(k.get("category") or "").lower()
            out.append({
                "name": k.get("name") or "KRI", "category": cat or "diğer",
                "current_value": _num(k.get("value")), "unit": k.get("unit") or "",
                "threshold_amber": _num(k.get("threshold_amber")), "threshold_red": _num(k.get("threshold_red")),
                "higher_is_worse": not bool(k.get("lower_is_worse")),
                "status": status, "source": "yüklenen KRI dosyası",
                "evidence": f"{k.get('name')}: {k.get('value')} {k.get('unit') or ''} (sahibi: {k.get('owner') or '-'})",
                "cascade_trigger": _KATEGORI_TETIK.get(cat),
                "cascade_params": {},
            })
    return out


def durus(kris: list[dict[str, Any]]) -> dict[str, Any]:
    red = [k for k in kris if k["status"] == "red"]
    amber = [k for k in kris if k["status"] == "amber"]
    green = [k for k in kris if k["status"] == "green"]
    if not kris:
        score = None
        posture, tr = "no_data", "VERİ YOK"
    else:
        score = round((len(red) * 3 + len(amber)) / (len(kris) * 3) * 10, 1)
        posture, tr = (("critical", "KRİTİK") if red else ("elevated", "YÜKSELMİŞ") if amber
                       else ("stable", "İSTİKRARLI"))
    by_category: dict[str, list[dict[str, Any]]] = {}
    for k in kris:
        by_category.setdefault(k["category"], []).append(k)
    return {
        "counts": {"red": len(red), "amber": len(amber), "green": len(green), "total": len(kris)},
        "red_kris": red, "amber_kris": amber, "all_kris": kris, "by_category": by_category,
        # Time-to-red needs a trend, which one period does not give.
        "upcoming_red": [],
        "cascade_ready": [k for k in red + amber if k.get("cascade_trigger")],
        "kri_score": score, "posture": posture, "posture_tr": tr,
        "sources": sorted({k["source"] for k in kris}),
    }


def gercek_kri(pnl: dict[str, Any] | None, forecast: dict[str, Any] | None,
               risk_result: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kris = [{**k, **_OLCULMEDI} for k in cfo_kri(pnl, forecast) + yuklenen_kri(risk_result)]
    return kris, durus(kris)
