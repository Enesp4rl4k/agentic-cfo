"""
Multi-Period Comparison Engine — DQ-4

Compares financial data across 2 or 3 periods (YoY, QoQ, MoM).

Architecture
------------
- PeriodData: holds parsed metrics from one analysis job
- ComparisonEngine: computes absolute + relative changes
- Endpoint: POST /comparison/multi-period accepts job_ids list

Supported comparisons
---------------------
- Revenue:     absolute change, % change, CAGR (3-period)
- Net income:  absolute change, margin delta
- Cash flow:   operating CF change
- Burn rate:   monthly burn, runway change
- OpEx:        category-level breakdown
- Anomaly count: improvement/deterioration

Period detection
----------------
Periods are auto-detected from transaction date ranges inside each job.
Labels: "2024-Q1", "2024-H1", "Jan 2024", "2023", etc.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Data containers ───────────────────────────────────────────────────────────

@dataclass
class PeriodData:
    """Parsed financial metrics for one period."""
    job_id: str
    label: str                # human-readable period label
    date_from: str | None
    date_to: str | None

    # Financial metrics
    revenue: float
    gross_profit: float
    gross_margin: float        # 0-1
    net_income: float
    net_margin: float          # 0-1
    ebitda: float
    ebitda_margin: float

    # Cash flow
    operating_cf: float
    net_cf: float
    ending_cash: float
    runway_months: float | None

    # Cost structure
    opex_total: float
    opex_breakdown: dict[str, float] = field(default_factory=dict)

    # Quality signals
    anomaly_count: int = 0
    transaction_count: int = 0


@dataclass
class MetricChange:
    """Change between two periods for a single metric."""
    metric: str
    label: str
    period_a_value: float | None
    period_b_value: float | None
    absolute_change: float | None
    pct_change: float | None     # as decimal: 0.15 = 15%
    direction: str               # "up" | "down" | "flat" | "na"
    is_positive_good: bool = True  # for color coding: up = green or red?

    @property
    def formatted_pct(self) -> str:
        if self.pct_change is None:
            return "N/A"
        sign = "+" if self.pct_change >= 0 else ""
        return f"{sign}{self.pct_change * 100:.1f}%"

    @property
    def color_class(self) -> str:
        if self.direction == "na":
            return "neutral"
        if self.direction == "up":
            return "positive" if self.is_positive_good else "negative"
        if self.direction == "down":
            return "negative" if self.is_positive_good else "positive"
        return "neutral"


@dataclass
class ComparisonReport:
    """Full multi-period comparison report."""
    periods: list[PeriodData]
    changes: list[MetricChange]    # A vs B (most recent two)
    cagr: dict[str, float]         # compound annual growth rates (3+ periods)
    trend_labels: list[str]        # period labels in order
    trend_revenue: list[float | None]
    trend_net_income: list[float | None]
    trend_operating_cf: list[float | None]
    narrative: str
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "periods": [
                {
                    "job_id": p.job_id,
                    "label": p.label,
                    "date_from": p.date_from,
                    "date_to": p.date_to,
                    "revenue": p.revenue,
                    "gross_margin": round(p.gross_margin * 100, 1),
                    "net_income": p.net_income,
                    "net_margin": round(p.net_margin * 100, 1),
                    "ebitda": p.ebitda,
                    "ebitda_margin": round(p.ebitda_margin * 100, 1),
                    "operating_cf": p.operating_cf,
                    "net_cf": p.net_cf,
                    "ending_cash": p.ending_cash,
                    "runway_months": p.runway_months,
                    "opex_total": p.opex_total,
                    "anomaly_count": p.anomaly_count,
                    "transaction_count": p.transaction_count,
                }
                for p in self.periods
            ],
            "changes": [
                {
                    "metric": c.metric,
                    "label": c.label,
                    "period_a": c.period_a_value,
                    "period_b": c.period_b_value,
                    "absolute_change": c.absolute_change,
                    "pct_change": round(c.pct_change * 100, 1) if c.pct_change is not None else None,
                    "formatted_pct": c.formatted_pct,
                    "direction": c.direction,
                    "color_class": c.color_class,
                }
                for c in self.changes
            ],
            "cagr": {k: round(v * 100, 1) for k, v in self.cagr.items()},
            "trends": {
                "labels": self.trend_labels,
                "revenue": self.trend_revenue,
                "net_income": self.trend_net_income,
                "operating_cf": self.trend_operating_cf,
            },
            "narrative": self.narrative,
            "recommendations": self.recommendations,
        }


# ── Extraction helpers ────────────────────────────────────────────────────────

def _extract_period_data(job_id: str, job_result: dict[str, Any]) -> PeriodData:
    """
    Extract PeriodData from a stored analysis job result dict.
    Handles missing keys gracefully.
    """
    pnl = job_result.get("pnl") or {}
    cashflow = job_result.get("cashflow") or {}
    forecast = job_result.get("forecast") or {}
    anomalies = job_result.get("anomalies") or []

    # Date range from transactions or metadata
    meta = job_result.get("metadata") or {}
    date_from = meta.get("date_from") or pnl.get("period_start")
    date_to   = meta.get("date_to")   or pnl.get("period_end")

    # Period label
    label = _make_period_label(date_from, date_to, job_id)

    # Cash flow
    cf_operating = cashflow.get("operating", 0.0) or 0.0
    cf_net = cashflow.get("net", 0.0) or 0.0

    # Runway
    scenarios = (forecast.get("scenarios") or {})
    runway = None
    for scenario in ("base", "pessimist"):
        sc = scenarios.get(scenario) or {}
        if sc.get("runway_months"):
            runway = float(sc["runway_months"])
            break

    # OpEx breakdown
    opex_breakdown: dict[str, float] = {}
    for item in pnl.get("opex") or []:
        name = item.get("category") or item.get("name") or "Other"
        amount = float(item.get("amount") or item.get("total") or 0)
        opex_breakdown[name] = opex_breakdown.get(name, 0.0) + amount

    revenue = float(pnl.get("revenue", 0) or 0)
    gross_profit = float(pnl.get("gross_profit", 0) or 0)
    net_income = float(pnl.get("net_income", 0) or 0)
    ebitda = float(pnl.get("ebitda", 0) or 0)

    return PeriodData(
        job_id=job_id,
        label=label,
        date_from=date_from,
        date_to=date_to,
        revenue=revenue,
        gross_profit=gross_profit,
        gross_margin=float(pnl.get("gross_margin", 0) or 0),
        net_income=net_income,
        net_margin=float(pnl.get("net_margin", 0) or 0),
        ebitda=ebitda,
        ebitda_margin=float(pnl.get("ebitda_margin", 0) or 0),
        operating_cf=cf_operating,
        net_cf=cf_net,
        ending_cash=float(cashflow.get("ending_cash", 0) or cashflow.get("closing_balance", 0) or 0),
        runway_months=runway,
        opex_total=float(pnl.get("total_opex", 0) or sum(opex_breakdown.values())),
        opex_breakdown=opex_breakdown,
        anomaly_count=len([a for a in anomalies if isinstance(a, dict)]),
        transaction_count=int(meta.get("transaction_count", 0) or 0),
    )


def _make_period_label(date_from: str | None, date_to: str | None, job_id: str) -> str:
    """Generate a human-readable period label."""
    if not date_from or not date_to:
        return f"Job {job_id[:8]}"

    try:
        from datetime import datetime
        d_from = datetime.fromisoformat(date_from.replace("Z", "+00:00")).date()
        d_to   = datetime.fromisoformat(date_to.replace("Z", "+00:00")).date()

        days = (d_to - d_from).days
        year_from = d_from.year
        year_to = d_to.year

        if days <= 35:
            months = ["", "Oca", "Şub", "Mar", "Nis", "May", "Haz",
                      "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
            return f"{months[d_from.month]} {year_from}"
        elif days <= 95:  # quarter
            q = (d_from.month - 1) // 3 + 1
            return f"{year_from}-Q{q}"
        elif days <= 200:  # half year
            h = 1 if d_from.month <= 6 else 2
            return f"{year_from}-H{h}"
        elif days <= 380:
            return str(year_from)
        else:
            return f"{year_from}–{year_to}"
    except Exception:
        return f"{date_from[:7] if date_from else '?'}"


def _metric_change(
    metric: str,
    label: str,
    a: float | None,
    b: float | None,
    is_positive_good: bool = True,
) -> MetricChange:
    """Compute change between period A (older) and period B (newer)."""
    if a is None or b is None:
        return MetricChange(
            metric=metric, label=label,
            period_a_value=a, period_b_value=b,
            absolute_change=None, pct_change=None,
            direction="na", is_positive_good=is_positive_good,
        )

    abs_change = b - a
    pct_change = abs_change / abs(a) if a != 0 else None

    if pct_change is None or abs(pct_change) < 0.001:
        direction = "flat"
    elif abs_change > 0:
        direction = "up"
    else:
        direction = "down"

    return MetricChange(
        metric=metric, label=label,
        period_a_value=a, period_b_value=b,
        absolute_change=abs_change, pct_change=pct_change,
        direction=direction, is_positive_good=is_positive_good,
    )


def _cagr(start: float, end: float, periods: int) -> float | None:
    """Compound Annual Growth Rate."""
    if start <= 0 or end <= 0 or periods <= 1:
        return None
    try:
        return (end / start) ** (1 / (periods - 1)) - 1
    except Exception:
        return None


# ── ComparisonEngine ──────────────────────────────────────────────────────────

class MultiPeriodComparisonEngine:
    """
    Compares 2-3 analysis job results.
    Periods are sorted chronologically by date_from.
    """

    @staticmethod
    def compare(period_data_list: list[PeriodData]) -> ComparisonReport:
        """
        Generate a comparison report from a list of PeriodData.

        Parameters
        ----------
        period_data_list : list[PeriodData]
            2 or 3 periods, in any order (sorted internally by date).
        """
        if len(period_data_list) < 2:
            raise ValueError("En az 2 dönem gereklidir.")

        # Sort chronologically
        periods = sorted(
            period_data_list,
            key=lambda p: p.date_from or p.job_id,
        )

        # A = oldest, B = most recent (for pairwise change)
        a = periods[0]
        b = periods[-1]

        # Changes: A → B
        changes = [
            _metric_change("revenue",       "Gelir",             a.revenue,       b.revenue),
            _metric_change("gross_profit",   "Brüt Kâr",          a.gross_profit,  b.gross_profit),
            _metric_change("gross_margin",   "Brüt Marj",         a.gross_margin,  b.gross_margin),
            _metric_change("net_income",     "Net Kâr",           a.net_income,    b.net_income),
            _metric_change("net_margin",     "Net Marj",          a.net_margin,    b.net_margin),
            _metric_change("ebitda",         "FAVÖK",             a.ebitda,        b.ebitda),
            _metric_change("operating_cf",   "İşletme Nakit Akışı", a.operating_cf, b.operating_cf),
            _metric_change("opex_total",     "Toplam OpEx",       a.opex_total,    b.opex_total,
                           is_positive_good=False),
            _metric_change("anomaly_count",  "Anomali Sayısı",    float(a.anomaly_count),
                           float(b.anomaly_count), is_positive_good=False),
        ]

        # CAGR for 3 periods
        cagr: dict[str, float] = {}
        if len(periods) >= 3:
            n = len(periods)
            for metric_name, getter in [
                ("revenue", lambda p: p.revenue),
                ("net_income", lambda p: p.net_income),
                ("ebitda", lambda p: p.ebitda),
            ]:
                first = getter(periods[0])
                last = getter(periods[-1])
                result = _cagr(first, last, n)
                if result is not None:
                    cagr[metric_name] = result

        # Trend series
        trend_labels = [p.label for p in periods]
        trend_revenue = [p.revenue for p in periods]
        trend_net_income = [p.net_income for p in periods]
        trend_cf = [p.operating_cf for p in periods]

        # Auto-generate narrative
        narrative = MultiPeriodComparisonEngine._build_narrative(a, b, changes)
        recommendations = MultiPeriodComparisonEngine._build_recommendations(changes)

        return ComparisonReport(
            periods=periods,
            changes=changes,
            cagr=cagr,
            trend_labels=trend_labels,
            trend_revenue=trend_revenue,
            trend_net_income=trend_net_income,
            trend_operating_cf=trend_cf,
            narrative=narrative,
            recommendations=recommendations,
        )

    @staticmethod
    def _build_narrative(a: PeriodData, b: PeriodData, changes: list[MetricChange]) -> str:
        """Generate a plain-language comparison narrative."""
        rev_change = next((c for c in changes if c.metric == "revenue"), None)
        net_change = next((c for c in changes if c.metric == "net_income"), None)
        cf_change  = next((c for c in changes if c.metric == "operating_cf"), None)

        parts = [f"{a.label} ile {b.label} dönemleri karşılaştırılıyor."]

        if rev_change and rev_change.pct_change is not None:
            sign = "artış" if rev_change.pct_change >= 0 else "düşüş"
            parts.append(
                f"Gelir {abs(rev_change.pct_change * 100):.1f}% {sign} gösterdi "
                f"({a.revenue:,.0f} → {b.revenue:,.0f} TRY)."
            )

        if net_change and net_change.pct_change is not None:
            if net_change.direction == "up":
                parts.append(f"Net kâr %{net_change.pct_change * 100:.1f} iyileşti.")
            elif net_change.direction == "down":
                parts.append(f"Net kâr %{abs(net_change.pct_change * 100):.1f} geriledi.")

        if cf_change and cf_change.pct_change is not None:
            if cf_change.direction == "up":
                parts.append("İşletme nakit akışı güçlendi.")
            elif cf_change.direction == "down":
                parts.append("İşletme nakit akışı zayıfladı — dikkat edilmeli.")

        return " ".join(parts)

    @staticmethod
    def _build_recommendations(changes: list[MetricChange]) -> list[str]:
        """Generate actionable recommendations from change data."""
        recs = []
        for c in changes:
            if c.metric == "opex_total" and c.direction == "up" and c.pct_change and c.pct_change > 0.15:
                recs.append(f"OpEx %{c.pct_change * 100:.0f} arttı — maliyet kalemlerini gözden geçirin.")
            if c.metric == "net_margin" and c.direction == "down" and c.pct_change and abs(c.pct_change) > 0.05:
                recs.append(f"Net marj {abs(c.pct_change * 100):.1f} puan geriledi — fiyatlama stratejisini değerlendirin.")
            if c.metric == "operating_cf" and c.direction == "down":
                recs.append("Nakit akışı kötüleşiyor — alacak tahsilatını hızlandırın.")
            if c.metric == "anomaly_count" and c.direction == "up":
                recs.append("Anomali sayısı arttı — fraud ve hata riskini inceleyin.")

        if not recs:
            recs.append("Genel eğilim kararlı görünüyor. Detaylı CFO analizini incelemeye devam edin.")

        return recs


def get_comparison_engine() -> MultiPeriodComparisonEngine:
    return MultiPeriodComparisonEngine()
