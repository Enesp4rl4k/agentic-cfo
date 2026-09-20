"""Çapraz alan analizi — yalnızca gerçekten analiz edilmiş alanlardan.

This hub used to run seven kernels and correlate their outputs. The kernels
produced every domain's numbers from CFO figures and constants, and wherever a
value was still missing the hub supplied its own: tech health 7, ROAS 2.5, SLA
95%, runway 12 months. It then averaged those into an "overall health score"
and raised insights such as "tech + ops strength — scaling opportunity" for a
company that had given it no technology or operations data at all. Financial
impacts multiplied `revenue / 12` — a month's statement divided by twelve — by
arbitrary factors.

It also never saw real data from the organisation's context: it read
`ctx.agent_results`, a field CompanyContext does not have, so every
organisation-level run fell through to the estimates.

Now:
- The inputs are the domain orchestrators' own results, read from the fields
  CompanyContext really stores (`last_<domain>_result`).
- A metric exists only if the result contains it. Nothing has a default.
- An insight is raised only when every metric it rests on exists, and its
  evidence names the domain result each came from.
- The health score is the mean of the real component scores and lists them;
  with fewer than two there is no score.
- No financial impact is invented. None is computed.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

ALANLAR = ("cto", "cmo", "coo", "chro", "risk", "audit", "compliance")


def _get(d: Any, *path: str) -> Any:
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _ayrilma(r: dict[str, Any]) -> float | None:
    dep = _num(_get(r, "attrition", "total_departures"))
    hc = _num(_get(r, "headcount", "total_headcount"))
    return round(dep / hc, 4) if dep is not None and hc else None


def _sla_uyumu(r: dict[str, Any]) -> float | None:
    breach = _num(_get(r, "sla", "sla_breach_rate"))
    return round(1 - breach, 4) if breach is not None else None


# metric → (domain, reader, what it is). Keys and scales read from the
# orchestrators' real output, not from the kernels' vocabulary.
METRIKLER: dict[str, tuple[str, Callable[[dict[str, Any]], float | None], str]] = {
    "ayrilma_orani": ("chro", _ayrilma, "Ayrılan çalışan / toplam personel"),
    "teknik_borc": ("cto", lambda r: _num(_get(r, "tech_debt", "debt_score")), "Teknik borç skoru (0-10)"),
    "roas": ("cmo", lambda r: _num(_get(r, "campaigns", "overall_roas")), "Reklam getirisi (ROAS)"),
    "churn": ("cmo", lambda r: _num(_get(r, "cohorts", "churn_rate")), "Müşteri kaybı oranı"),
    "sla_uyumu": ("coo", _sla_uyumu, "SLA'ya uyan talep oranı"),
    "denetim_kritik": ("audit", lambda r: _num(_get(r, "findings", "open_critical")), "Açık kritik denetim bulgusu"),
    "uyum_kritik": ("compliance", lambda r: _num(_get(r, "violations", "critical_open")), "Açık kritik uyumsuzluk"),
}

# Component health scores the orchestrators publish, normalised to 0-100.
SAGLIK_BILESENLERI: dict[str, tuple[Callable[[dict[str, Any]], float | None], str]] = {
    "cmo": (lambda r: (v * 10 if (v := _num(_get(r, "cmo_summary", "overall_marketing_score"))) is not None else None), "Pazarlama skoru"),
    "coo": (lambda r: (v * 10 if (v := _num(_get(r, "coo_summary", "overall_ops_score"))) is not None else None), "Operasyon skoru"),
    "chro": (lambda r: (v * 10 if (v := _num(_get(r, "chro_summary", "chro_health_score"))) is not None else None), "İK sağlık skoru"),
    "audit": (lambda r: _num(_get(r, "audit_summary", "audit_health_score")), "Denetim sağlık skoru"),
    "compliance": (lambda r: _num(_get(r, "compliance_summary", "overall_health_score")), "Uyum sağlık skoru"),
    "risk": (lambda r: (100 - v * 10 if (v := _num(_get(r, "risk_summary", "enterprise_risk_score"))) is not None else None), "100 − kurumsal risk skoru×10"),
}


@dataclass
class CrossDomainInsight:
    id: str
    title: str
    domains: list[str]
    severity: str           # critical | high | medium | low
    insight_type: str       # risk | opportunity | correlation | warning
    description: str
    evidence: list[str]
    actions: list[str]
    financial_impact_try: float | None = None   # never estimated here


@dataclass
class CrossDomainReport:
    analyzed_domains: list[str]
    missing_domains: list[str]
    metrics: dict[str, float]
    insights: list[CrossDomainInsight]
    critical_count: int
    high_count: int
    overall_health_score: float | None
    health_label: str | None
    health_components: list[dict[str, Any]] = field(default_factory=list)
    executive_summary: str = ""
    top_priorities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _label(score: float) -> str:
    if score >= 80:
        return "excellent"
    if score >= 65:
        return "good"
    if score >= 50:
        return "fair"
    if score >= 35:
        return "at_risk"
    return "critical"


class CrossDomainHub:
    def __init__(
        self,
        *,
        domain_results: dict[str, dict[str, Any] | None] | None = None,
        pnl: dict[str, Any] | None = None,
        forecast: dict[str, Any] | None = None,
    ) -> None:
        self.results = {k: v for k, v in (domain_results or {}).items() if k in ALANLAR and v}
        self.pnl = pnl or {}
        runway = _get(forecast or {}, "scenarios", "base", "runway_months")
        self.runway_months = _num(runway)   # unknown stays unknown

    def metrics(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for name, (domain, read, _desc) in METRIKLER.items():
            r = self.results.get(domain)
            if r is None:
                continue
            try:
                v = read(r)
            except Exception:
                v = None
            if v is not None:
                out[name] = v
        return out

    def _insights(self, m: dict[str, float]) -> list[CrossDomainInsight]:
        out: list[CrossDomainInsight] = []

        def has(*names: str) -> bool:
            return all(n in m for n in names)

        if self.runway_months is not None and has("ayrilma_orani") \
                and self.runway_months < 4 and m["ayrilma_orani"] > 0.20:
            out.append(CrossDomainInsight(
                id="talent_cash_cascade", title="Nakit sıkışıyor, çalışanlar ayrılıyor",
                domains=["cfo", "chro"], severity="critical", insight_type="risk",
                description=(f"Nakit ömrü {self.runway_months:.1f} ay ve personelin "
                             f"%{m['ayrilma_orani']*100:.0f}'i ayrılmış."),
                evidence=[f"CFO tahmini: nakit ömrü {self.runway_months:.1f} ay",
                          f"İK dosyası: ayrılma oranı %{m['ayrilma_orani']*100:.0f}"],
                actions=["Kritik ekip üyeleri için tutma planı", "Nakit durumunu ekiple açıkça paylaşın"],
            ))
        if has("teknik_borc", "roas") and m["teknik_borc"] > 6 and m["roas"] > 2.5:
            out.append(CrossDomainInsight(
                id="delivery_risk_revenue", title="Teknik borç büyümeyi taşıyamayabilir",
                domains=["cto", "cmo"], severity="high", insight_type="risk",
                description=f"Teknik borç {m['teknik_borc']:.1f}/10 iken reklamlar {m['roas']:.1f}x getiriyor.",
                evidence=[f"Kod geçmişi: teknik borç {m['teknik_borc']:.1f}/10",
                          f"Kampanya verisi: ROAS {m['roas']:.1f}x"],
                actions=["Sprint kapasitesinin bir kısmını borç azaltmaya ayırın",
                         "Pazarlama vaatlerini ürün yol haritasıyla hizalayın"],
            ))
        if has("sla_uyumu", "ayrilma_orani") and m["sla_uyumu"] < 0.90 and m["ayrilma_orani"] > 0.22:
            out.append(CrossDomainInsight(
                id="ops_degradation_spiral", title="Operasyonel bozulma sarmalı",
                domains=["coo", "chro"], severity="high", insight_type="risk",
                description=(f"Taleplerin %{m['sla_uyumu']*100:.0f}'i SLA içinde ve personelin "
                             f"%{m['ayrilma_orani']*100:.0f}'i ayrılmış."),
                evidence=[f"SLA raporu: uyum %{m['sla_uyumu']*100:.0f}",
                          f"İK dosyası: ayrılma oranı %{m['ayrilma_orani']*100:.0f}"],
                actions=["Kritik süreçleri belgeleyin", "SLA ihlallerinin kök nedenini analiz edin"],
            ))
        if (has("uyum_kritik") and m["uyum_kritik"] >= 1) or (has("denetim_kritik") and m["denetim_kritik"] >= 1):
            uyum = int(m.get("uyum_kritik", 0))
            denetim = int(m.get("denetim_kritik", 0))
            ev = []
            if "uyum_kritik" in m:
                ev.append(f"Uyumsuzluk listesi: {uyum} açık kritik")
            if "denetim_kritik" in m:
                ev.append(f"Denetim bulguları: {denetim} açık kritik")
            out.append(CrossDomainInsight(
                id="regulatory_exposure", title="Açık kritik uyum ve denetim bulguları",
                domains=[d for d, k in (("compliance", "uyum_kritik"), ("audit", "denetim_kritik")) if k in m],
                severity="critical" if uyum >= 1 else "high", insight_type="warning",
                description=f"{uyum} kritik uyumsuzluk ve {denetim} kritik denetim bulgusu açık.",
                evidence=ev,
                actions=["Hukuk danışmanını devreye alın", "Kritik bulguları 7 gün içinde kapatma planı yapın"],
            ))
        if has("churn", "roas") and m["churn"] > 0.05 and m["roas"] > 2.0:
            out.append(CrossDomainInsight(
                id="growth_churn_imbalance", title="Kazanılan müşteri, kaybedileni karşılamıyor",
                domains=["cmo"], severity="medium", insight_type="correlation",
                description=f"Reklamlar {m['roas']:.1f}x getiriyor ama müşteri kaybı %{m['churn']*100:.0f}.",
                evidence=[f"Müşteri tutma verisi: kayıp %{m['churn']*100:.0f}",
                          f"Kampanya verisi: ROAS {m['roas']:.1f}x"],
                actions=["En çok kaybedilen müşteri grubunu inceleyin", "Müşteri başarı programı başlatın"],
            ))
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        out.sort(key=lambda i: order.get(i.severity, 4))
        return out

    def _health(self) -> tuple[float | None, list[dict[str, Any]]]:
        comps: list[dict[str, Any]] = []
        for domain, (read, label) in SAGLIK_BILESENLERI.items():
            r = self.results.get(domain)
            if r is None:
                continue
            v = read(r)
            if v is not None:
                comps.append({"alan": domain, "etiket": label, "skor": round(max(0.0, min(100.0, v)), 1)})
        margin = _num(self.pnl.get("net_margin")) if self.pnl.get("revenue") else None
        if margin is not None:
            comps.append({"alan": "cfo", "etiket": "Net kâr marjı (50 + marj×200)",
                          "skor": round(max(0.0, min(100.0, 50 + margin * 200)), 1)})
        if len(comps) < 2:
            return None, comps
        return round(sum(c["skor"] for c in comps) / len(comps), 1), comps

    def run(self) -> CrossDomainReport:
        m = self.metrics()
        insights = self._insights(m)
        score, comps = self._health()
        analyzed = sorted(self.results)
        missing = [d for d in ALANLAR if d not in self.results]
        critical = sum(1 for i in insights if i.severity == "critical")
        high = sum(1 for i in insights if i.severity == "high")
        if not analyzed:
            summary = "Henüz hiçbir alan gerçek veriyle analiz edilmedi; çapraz bulgu üretilemez."
        else:
            summary = (f"{len(analyzed)} alan gerçek veriyle analiz edildi ({', '.join(analyzed)}). "
                       f"{len(insights)} çapraz bulgu ({critical} kritik, {high} yüksek).")
            summary += (f" Genel sağlık {score:.0f}/100, {len(comps)} bileşenden." if score is not None
                        else " Sağlık skoru için en az iki alanın skoru gerekir.")
        return CrossDomainReport(
            analyzed_domains=analyzed, missing_domains=missing, metrics=m,
            insights=insights, critical_count=critical, high_count=high,
            overall_health_score=score, health_label=_label(score) if score is not None else None,
            health_components=comps, executive_summary=summary,
            top_priorities=[f"[{i.severity.upper()}] {i.actions[0]}" for i in insights[:3] if i.actions],
        )


async def load_org_inputs(org_id: str, db: Any = None) -> dict[str, Any]:
    """The organisation's latest real results, from the fields CompanyContext stores."""
    from app.services.company_context import get_company_context

    ctx = await get_company_context(org_id, db)
    cfo = getattr(ctx, "last_cfo_result", None) or {}
    return {
        "pnl": cfo.get("pnl") or {},
        "forecast": cfo.get("forecast") or {},
        "domain_results": {d: getattr(ctx, f"last_{d}_result", None) for d in ALANLAR},
    }


async def run_cross_domain_analysis(
    *,
    domain_results: dict[str, dict[str, Any] | None] | None = None,
    pnl: dict[str, Any] | None = None,
    forecast: dict[str, Any] | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """Cross-domain report over real domain results. Unknown inputs are ignored."""
    return CrossDomainHub(domain_results=domain_results, pnl=pnl, forecast=forecast).run().to_dict()
