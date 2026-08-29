"""Deterministic projectors: agent blobs / canonical txs → MetricPoint[]."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services.semantic.types import EvidenceRef, MetricPoint, MetricUnit


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _point(
    metric_id: str,
    value: Any,
    unit: MetricUnit,
    *,
    confidence: float = 0.9,
    currency: str | None = None,
    source_agent: str | None = None,
    source_job_id: str | None = None,
    data_source: str = "agent",
    evidence: list[EvidenceRef] | None = None,
) -> MetricPoint | None:
    if value is None:
        return None
    return MetricPoint(
        metric_id=metric_id,
        value=value,
        unit=unit,
        confidence=confidence,
        currency=currency,
        as_of=_now(),
        source_agent=source_agent,
        source_job_id=source_job_id,
        evidence_refs=evidence or [],
        data_source=data_source,
    )


def _cfo_dashboard(cfo: dict[str, Any]) -> dict[str, Any]:
    return cfo.get("dashboard") or cfo


def project_from_cfo(
    last_cfo: dict[str, Any] | None,
    *,
    currency: str = "USD",
    job_id: str | None = None,
) -> list[MetricPoint]:
    if not last_cfo:
        return []
    dash = _cfo_dashboard(last_cfo)
    pnl = dash.get("pnl") or {}
    cashflow = dash.get("cashflow") or {}
    forecast = dash.get("forecast") or {}
    anomalies = last_cfo.get("anomalies") or dash.get("anomalies") or []

    runway = None
    scenarios = forecast.get("scenarios") or {}
    base = scenarios.get("base") or {}
    runway = base.get("runway_months")

    critical = sum(1 for a in anomalies if isinstance(a, dict) and a.get("severity") == "critical")

    # Revenue may be cents or float major units — prefer *_cents / amount fields
    revenue = pnl.get("revenue_cents")
    if revenue is None:
        revenue = pnl.get("revenue")
        # If looks like major units (small float), leave as-is; catalog unit is cents
        # Callers storing major units as "revenue" are common — treat < 1e6 as major→cents
        if isinstance(revenue, (int, float)) and abs(revenue) < 1_000_000 and revenue != int(revenue):
            revenue = round(float(revenue) * 100)
        elif isinstance(revenue, (int, float)) and abs(revenue) < 10_000_000:
            # Ambiguous; keep numeric as provided if integer-like large, else cents convert
            pass

    ebitda = pnl.get("ebitda_cents", pnl.get("ebitda"))
    op_cf = cashflow.get("operating_cents", cashflow.get("operating"))

    refs = [
        EvidenceRef(source_type="cfo_result", job_id=job_id, preview="last_cfo_result")
    ]
    out: list[MetricPoint] = []
    for p in (
        _point("finance.revenue", revenue, "cents", currency=currency, source_agent="cfo", source_job_id=job_id, evidence=refs),
        _point("finance.gross_margin", pnl.get("gross_margin"), "ratio", source_agent="cfo", source_job_id=job_id, evidence=refs),
        _point("finance.net_margin", pnl.get("net_margin"), "ratio", source_agent="cfo", source_job_id=job_id, evidence=refs),
        _point("finance.ebitda", ebitda, "cents", currency=currency, source_agent="cfo", source_job_id=job_id, evidence=refs),
        _point("finance.operating_cashflow", op_cf, "cents", currency=currency, source_agent="cfo", source_job_id=job_id, evidence=refs),
        _point("finance.runway_months", runway, "months", source_agent="cfo", source_job_id=job_id, evidence=refs),
        _point("finance.critical_anomalies", critical, "count", confidence=1.0, source_agent="cfo", source_job_id=job_id, evidence=refs),
    ):
        if p is not None:
            out.append(p)
    return out


def project_from_cmo(
    last_cmo: dict[str, Any] | None,
    *,
    currency: str = "USD",
    job_id: str | None = None,
) -> list[MetricPoint]:
    if not last_cmo:
        return []
    campaigns = last_cmo.get("campaigns") or {}
    summary = last_cmo.get("cmo_summary") or {}
    refs = [EvidenceRef(source_type="cmo_result", job_id=job_id)]
    cac = campaigns.get("blended_cac_cents") or campaigns.get("cac") or campaigns.get("overall_cac_cents")
    out: list[MetricPoint] = []
    for p in (
        _point("growth.overall_roas", campaigns.get("overall_roas") or summary.get("overall_roas"), "ratio", source_agent="cmo", source_job_id=job_id, evidence=refs),
        _point("growth.blended_cac", cac, "cents", currency=currency, source_agent="cmo", source_job_id=job_id, evidence=refs),
        _point("growth.conversions", campaigns.get("total_conversions"), "count", source_agent="cmo", source_job_id=job_id, evidence=refs),
    ):
        if p is not None:
            out.append(p)
    return out


def project_from_cto(
    last_cto: dict[str, Any] | None,
    *,
    job_id: str | None = None,
) -> list[MetricPoint]:
    if not last_cto:
        return []
    summary = last_cto.get("cto_summary") or {}
    velocity = last_cto.get("velocity") or {}
    debt = last_cto.get("tech_debt") or {}
    infra = last_cto.get("infra") or {}
    refs = [EvidenceRef(source_type="cto_result", job_id=job_id)]
    waste_pct = None
    total = infra.get("total_cost_cents")
    waste = infra.get("waste_estimate_cents")
    if total and waste and total > 0:
        waste_pct = round(waste / total * 100, 1)

    out: list[MetricPoint] = []
    for p in (
        _point("tech.health_score", summary.get("overall_health_score"), "score", source_agent="cto", source_job_id=job_id, evidence=refs),
        _point("tech.velocity_trend", velocity.get("velocity_trend") or velocity.get("trend"), "string", source_agent="cto", source_job_id=job_id, evidence=refs),
        _point("tech.debt_score", debt.get("debt_score"), "score", source_agent="cto", source_job_id=job_id, evidence=refs),
        _point("tech.infra_waste_pct", waste_pct, "percent", source_agent="cto", source_job_id=job_id, evidence=refs),
    ):
        if p is not None:
            out.append(p)
    return out


def project_from_chro(
    last_chro: dict[str, Any] | None,
    *,
    job_id: str | None = None,
) -> list[MetricPoint]:
    if not last_chro:
        return []
    headcount = last_chro.get("headcount") or {}
    attrition = last_chro.get("attrition") or {}
    workforce = last_chro.get("workforce") or {}
    refs = [EvidenceRef(source_type="chro_result", job_id=job_id)]
    hc = headcount.get("total_headcount") or workforce.get("total_headcount")
    attr = attrition.get("annualized_attrition_rate") or attrition.get("rate_pct")
    if isinstance(attr, (int, float)) and attr > 1:
        attr = attr / 100.0
    turnover = workforce.get("turnover_rate")
    out: list[MetricPoint] = []
    for p in (
        _point("people.headcount", hc, "count", source_agent="chro", source_job_id=job_id, evidence=refs),
        _point("people.attrition_rate", attr, "ratio", source_agent="chro", source_job_id=job_id, evidence=refs),
        _point("people.turnover_rate", turnover, "ratio", source_agent="chro", source_job_id=job_id, evidence=refs),
    ):
        if p is not None:
            out.append(p)
    return out


def project_from_coo(
    last_coo: dict[str, Any] | None,
    *,
    job_id: str | None = None,
) -> list[MetricPoint]:
    if not last_coo:
        return []
    summary = last_coo.get("coo_summary") or {}
    bottlenecks = last_coo.get("bottlenecks") or last_coo.get("processes") or []
    sla = last_coo.get("sla") or {}
    refs = [EvidenceRef(source_type="coo_result", job_id=job_id)]
    bn_count = len(bottlenecks) if isinstance(bottlenecks, list) else summary.get("bottleneck_count")
    breach = sla.get("breach_rate") or summary.get("sla_breach_rate")
    out: list[MetricPoint] = []
    for p in (
        _point("ops.bottleneck_count", bn_count, "count", source_agent="coo", source_job_id=job_id, evidence=refs),
        _point("ops.sla_breach_rate", breach, "ratio", source_agent="coo", source_job_id=job_id, evidence=refs),
    ):
        if p is not None:
            out.append(p)
    return out


def project_from_risk(
    last_risk: dict[str, Any] | None,
    *,
    job_id: str | None = None,
) -> list[MetricPoint]:
    if not last_risk:
        return []
    summary = last_risk.get("risk_summary") or last_risk.get("summary") or {}
    kris = last_risk.get("kris") or last_risk.get("kri") or []
    refs = [EvidenceRef(source_type="risk_result", job_id=job_id)]
    score = summary.get("overall_score") or summary.get("risk_score") or last_risk.get("overall_score")
    critical = 0
    if isinstance(kris, list):
        critical = sum(
            1
            for k in kris
            if isinstance(k, dict) and str(k.get("severity") or k.get("status") or "").lower() in {"critical", "red"}
        )
    out: list[MetricPoint] = []
    for p in (
        _point("risk.overall_score", score, "score", source_agent="risk", source_job_id=job_id, evidence=refs),
        _point("risk.critical_kri_count", critical, "count", confidence=1.0, source_agent="risk", source_job_id=job_id, evidence=refs),
    ):
        if p is not None:
            out.append(p)
    return out


def project_from_canonical_rows(
    rows: list[Any],
    *,
    currency: str = "USD",
    quality_score: float | None = None,
) -> list[MetricPoint]:
    """Aggregate CanonicalTransaction-like objects (amount_cents, direction)."""
    inflow = 0
    outflow = 0
    for r in rows:
        amt = int(getattr(r, "amount_cents", 0) or 0)
        direction = str(getattr(r, "direction", "") or "").lower()
        if direction in {"income", "inflow", "credit"}:
            inflow += abs(amt)
        else:
            outflow += abs(amt)
    refs = [EvidenceRef(source_type="canonical_transactions", preview=f"n={len(rows)}")]
    out: list[MetricPoint] = []
    if rows:
        for p in (
            _point(
                "finance.canonical_inflow",
                inflow,
                "cents",
                currency=currency,
                confidence=0.95,
                data_source="canonical",
                evidence=refs,
            ),
            _point(
                "finance.canonical_outflow",
                outflow,
                "cents",
                currency=currency,
                confidence=0.95,
                data_source="canonical",
                evidence=refs,
            ),
        ):
            if p is not None:
                out.append(p)
    if quality_score is not None:
        qp = _point(
            "finance.canonical_quality_score",
            quality_score,
            "score",
            confidence=1.0,
            data_source="canonical",
            evidence=refs,
        )
        if qp:
            out.append(qp)
    return out


def project_from_kernel(
    kernel: dict[str, Any] | None,
    *,
    agent: str,
) -> list[MetricPoint]:
    """Optional overlay from kernel cache — map known keys only."""
    if not kernel:
        return []
    conf = float(kernel.get("confidence") or 0.7)
    ds = str(kernel.get("data_source") or "kernel")
    out: list[MetricPoint] = []
    if agent == "cto":
        for mid, key, unit in (
            ("tech.health_score", "overall_health_score", "score"),
            ("tech.debt_score", "tech_debt_score", "score"),
            ("tech.infra_waste_pct", "infra_waste_pct", "percent"),
        ):
            if key in kernel:
                p = _point(mid, kernel[key], unit, confidence=conf, source_agent="cto", data_source=ds)  # type: ignore[arg-type]
                if p:
                    out.append(p)
        if "velocity_trend" in kernel:
            p = _point("tech.velocity_trend", kernel["velocity_trend"], "string", confidence=conf, source_agent="cto", data_source=ds)
            if p:
                out.append(p)
    return out


def merge_metrics(*groups: list[MetricPoint]) -> list[MetricPoint]:
    """Later groups override earlier on same metric_id (higher priority last)."""
    merged: dict[str, MetricPoint] = {}
    for group in groups:
        for m in group:
            merged[m.metric_id] = m
    return list(merged.values())
