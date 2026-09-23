"""Tahmin kalibrasyonu — eski iddialar bugün ne kadar tutuyor? (P3)

A forecast is a claim made on a date. This module checks each finished
analysis's stored forecast against what actually happened in the twelve
months after the claim, and answers honestly — including the honest
answer "yeterli veri yok" rather than a metric computed on one or two
pairs.

Deliberately no new table (approved scope): the claims already live in
`reports` (the JSON dashboard written per finished job) and the
realisations live in `transactions`.

Two rules keep the number honest:

  1. A pair only counts once its 365-day window has closed AND a later
     analysis ingested it (`data_job.created_at` past the window) —
     before that, "not enough data" is the truth, not a small sample.
  2. Realised net comes from the NEWEST finished job's rows only. Every
     job re-ingests the organisation's ledger, so summing across jobs
     would double-count the same real-world transactions.

Units — the trap in this codebase: `report_agent._build_dashboard_json`
stores money in LIRA (it divides the pipeline's cents by 100; pinned by
`tests/test_agents/test_report_agent.py::test_cashflow_net_change_converted`)
while `transactions.amount_kurus` is kuruş. Claims are converted to kuruş
once at the boundary; every `*_kurus` output is integer kuruş.

Deterministic and read-only: no LLM, safe to call while the manager
keeps thinking.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob, JobStatus

# The claim covers the next 12 months; a pair needs data past the window.
WINDOW_DAYS = 365
# Below this many pairs the "metric" would be noise wearing a number.
MIN_PAIRS = 3

_MEASURABLE_STATUSES = (JobStatus.COMPLETED, JobStatus.AWAITING_REVIEW)


def _insufficient(pairs: int) -> dict[str, Any]:
    return {"status": "yeterli veri yok", "pairs": pairs}


def _kurus(value: Any) -> int | None:
    """A stored lira figure → integer kuruş; None when it isn't a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(value * 100)


def _claim(report_data: dict[str, Any] | None) -> tuple[int, list[int]] | None:
    """(base kuruş, all-scenario band kuruş) — None when no usable forecast."""
    forecast = (report_data or {}).get("forecast") or {}
    scenarios = forecast.get("scenarios") or {}
    if not isinstance(scenarios, dict):
        return None
    nets: list[int] = []
    base: int | None = None
    for name, scenario in scenarios.items():
        if not isinstance(scenario, dict):
            continue
        net = _kurus(scenario.get("twelve_month_net"))
        if net is None:
            continue
        nets.append(net)
        if name == "base":
            base = net
    if base is None or not nets:
        return None
    return base, nets


async def build_backtest(db: AsyncSession, *, org_id: str | None) -> dict[str, Any]:
    """Org's forecast backtest: claims vs the twelve months that followed.

    Returns `{"status": "ok", "pairs", "mae_kurus", "smape_pct",
    "coverage_pct", "bias_kurus"}` once ≥ MIN_PAIRS pairs closed, else
    `{"status": "yeterli veri yok", "pairs"}`. `coverage_pct` is None
    when no pair had a multi-scenario band to fall inside.
    """
    from app.models.report import Report, ReportFormat
    from app.models.transaction import Transaction

    if not org_id:
        return _insufficient(0)

    data_job = (
        await db.execute(
            select(AnalysisJob)
            .where(
                AnalysisJob.org_id == org_id,
                AnalysisJob.status.in_(_MEASURABLE_STATUSES),
            )
            .order_by(desc(AnalysisJob.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if data_job is None:
        return _insufficient(0)

    rows = (
        await db.execute(
            select(Report.job_id, Report.created_at, Report.data)
            .join(AnalysisJob, AnalysisJob.id == Report.job_id)
            .where(
                AnalysisJob.org_id == org_id,
                AnalysisJob.status.in_(_MEASURABLE_STATUSES),
                Report.report_format == ReportFormat.JSON,
            )
            .order_by(desc(Report.created_at))
        )
    ).all()

    # One claim per job (newest JSON report wins); closed AND ingested.
    seen: set[str] = set()
    claims: list[tuple[datetime, int, list[int]]] = []
    for job_id, created_at, report_data in rows:
        if job_id in seen:
            continue
        seen.add(job_id)
        claim = _claim(report_data)
        if claim is None:
            continue
        base, band = claim
        if created_at + timedelta(days=WINDOW_DAYS) >= data_job.created_at:
            continue  # window still open — the pair is not fair yet
        claims.append((created_at, base, band))
    if not claims:
        return _insufficient(0)

    earliest = min(c[0] for c in claims)
    flows = (
        await db.execute(
            select(
                Transaction.transaction_date,
                Transaction.type,
                Transaction.amount_kurus,
            ).where(
                Transaction.job_id == data_job.id,
                Transaction.transaction_date > earliest,
            )
        )
    ).all()

    pairs: list[tuple[int, int, list[int]]] = []
    for claimed_at, base, band in claims:
        window_end = claimed_at + timedelta(days=WINDOW_DAYS)
        realized = 0
        for txn_date, txn_type, amount in flows:
            if claimed_at < txn_date <= window_end:
                realized += amount if txn_type == "income" else -amount
        pairs.append((base, realized, band))

    if len(pairs) < MIN_PAIRS:
        return _insufficient(len(pairs))

    n = len(pairs)
    mae = sum(abs(f - a) for f, a, _ in pairs) / n
    bias = sum(f - a for f, a, _ in pairs) / n
    smape_terms = [
        0.0 if (abs(f) + abs(a)) == 0 else abs(f - a) / ((abs(f) + abs(a)) / 2) * 100
        for f, a, _ in pairs
    ]
    banded = [(band, a) for _, a, band in pairs if len(band) >= 2]
    coverage: float | None = None
    if banded:
        covered = sum(1 for band, a in banded if min(band) <= a <= max(band))
        coverage = round(100 * covered / len(banded), 1)

    return {
        "status": "ok",
        "pairs": n,
        "mae_kurus": round(mae),
        "smape_pct": round(sum(smape_terms) / n, 1),
        "coverage_pct": coverage,
        "bias_kurus": round(bias),
    }
