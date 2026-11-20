"""Pilot Metrics & Ledger Grounded Backtesting.

Plan v10 §4 (O5) & Plan v11 Faz 4:
- 4.1: 4 Haftalık Tahmin Sapması (Radar Backtesting):
  4 hafta önceki radar projeksiyonunun, gerçekleşen banka bakiyesiyle karşılaştırılıp sapma yüzdesinin hesaplanması.
- 4.2: Recommendation response metrics from explicit owner responses in DecisionLog.
  Expected action amounts are not treated as realized financial impact.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.decision_log import DecisionLog
from app.services.cash_radar import _fmt
from app.services.cash_radar_snapshots import find_radar_snapshot_for_target


@dataclass(frozen=True)
class RadarBacktestResult:
    org_id: str
    target_date: str
    lookback_weeks: int
    projected_end_balance_cents: int | None
    actual_proven_balance_cents: int | None
    actual_proven_balance_as_of: str | None
    variance_cents: int | None
    variance_pct: float | None
    accuracy_tier: str  # HIGH | MODERATE | LOW | NO_ACTUAL | NO_FORECAST_SNAPSHOT | ZERO_ACTUAL
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionSuccessMetrics:
    org_id: str
    total_recommendations: int
    responded_count: int
    unresponded_count: int
    adopted_count: int  # 'done' / 'Yaptım'
    deferred_count: int  # 'deferred' / 'Ertele'
    dismissed_count: int  # 'dismissed' / 'Gerek Yok'
    open_count: int
    closed_count: int
    adoption_rate_pct: float
    correction_rate_pct: float
    dismissal_rate_pct: float
    response_rate_pct: float
    accepted_expected_amount_cents: int
    # Kept for API compatibility. This is an expected amount, not realized impact.
    total_impact_cents: int
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def compute_radar_backtesting(
    db: AsyncSession,
    org_id: str,
    *,
    anchor_date: date | None = None,
    lookback_weeks: int = 4,
) -> RadarBacktestResult:
    """Compare a saved forecast to a proven closing balance on the target date."""
    target = anchor_date or datetime.now(UTC).date()
    snapshot, projected_balance = await find_radar_snapshot_for_target(
        db, org_id, target_date=target, lookback_weeks=lookback_weeks
    )
    rows = await db.execute(
        select(AnalysisJob.result_metadata)
        .where(
            AnalysisJob.org_id == org_id,
            AnalysisJob.status == JobStatus.COMPLETED,
        )
        .order_by(AnalysisJob.created_at.desc())
    )
    actual_balance: int | None = None
    for (metadata,) in rows.all():
        closing = metadata.get("closing_balance") if isinstance(metadata, dict) else None
        if isinstance(closing, dict) and closing.get("date") == target.isoformat():
            try:
                # Contract written by bank_balance.closing_balance(): {"date", "balance_cents"}.
                actual_balance = int(closing["balance_cents"])
            except (KeyError, TypeError, ValueError):
                continue
            else:
                break

    variance_cents: int | None = None
    variance_pct: float | None = None
    if snapshot is None or projected_balance is None:
        tier = "NO_FORECAST_SNAPSHOT"
        summary = (
            f"{target.isoformat()} tarihinde bitecek {lookback_weeks} haftalık saklanmış "
            "radar tahmini bulunamadı; doğruluk hesaplanmadı."
        )
        projected_balance = None
    elif actual_balance is None:
        tier = "NO_ACTUAL"
        summary = (
            f"Saklanmış projeksiyon {_fmt(projected_balance)}; {target.isoformat()} tarihi için "
            "aynı gün kapanış bakiyesi bulunmadığından sapma hesaplanmadı."
        )
    else:
        variance_cents = projected_balance - actual_balance
        if actual_balance == 0:
            tier = "ZERO_ACTUAL"
            summary = (
                f"Projeksiyon {_fmt(projected_balance)}, gerçekleşen bakiye {_fmt(actual_balance)}. "
                "Gerçekleşen bakiye sıfır olduğu için yüzde sapma tanımsızdır."
            )
        else:
            variance_pct = abs(variance_cents) / abs(actual_balance) * 100.0
            if variance_pct <= 10.0:
                tier = "HIGH"
                tier_tr = "yüksek"
            elif variance_pct <= 25.0:
                tier = "MODERATE"
                tier_tr = "orta"
            else:
                tier = "LOW"
                tier_tr = "düşük"
            summary = (
                f"Projeksiyon {_fmt(projected_balance)}, gerçekleşen bakiye "
                f"{_fmt(actual_balance)}; mutlak sapma %{variance_pct:.1f} ({tier_tr})."
            )

    return RadarBacktestResult(
        org_id=org_id,
        target_date=target.isoformat(),
        lookback_weeks=lookback_weeks,
        projected_end_balance_cents=projected_balance,
        actual_proven_balance_cents=actual_balance,
        actual_proven_balance_as_of=target.isoformat() if actual_balance is not None else None,
        variance_cents=variance_cents,
        variance_pct=round(variance_pct, 2) if variance_pct is not None else None,
        accuracy_tier=tier,
        summary=summary,
    )


async def compute_decision_success_metrics(
    db: AsyncSession,
    org_id: str,
) -> DecisionSuccessMetrics:
    """Measure owner response rates and impact on recommendations recorded in DecisionLog."""
    result = await db.execute(
        select(DecisionLog).where(
            DecisionLog.org_id == org_id,
            DecisionLog.expected.isnot(None),
        )
    )
    decisions = [
        decision
        for decision in result.scalars().all()
        if isinstance(decision.expected, dict)
        and decision.expected.get("source") in {"cash_radar", "monday_briefing"}
    ]

    total = len(decisions)
    responded = 0
    adopted = 0
    deferred = 0
    dismissed = 0
    open_count = 0
    closed_count = 0
    total_impact = 0

    for d in decisions:
        if d.status == "open":
            open_count += 1
        else:
            closed_count += 1

        actual_resp = ""
        if isinstance(d.actual, dict):
            candidate = d.actual.get("owner_response", "")
            actual_resp = candidate if isinstance(candidate, str) else ""

        if actual_resp not in {"done", "deferred", "dismissed"}:
            continue
        responded += 1

        exp_amount = 0
        if isinstance(d.expected, dict):
            raw_amount = d.expected.get(
                "expected_amount_cents", d.expected.get("amount_cents", 0)
            )
            try:
                exp_amount = int(raw_amount or 0)
            except (TypeError, ValueError):
                exp_amount = 0

        if actual_resp == "done":
            adopted += 1
            total_impact += exp_amount
        elif actual_resp == "deferred":
            deferred += 1
        elif actual_resp == "dismissed":
            dismissed += 1

    unresponded = total - responded
    adopt_rate = (adopted / responded * 100.0) if responded > 0 else 0.0
    dismissal_rate = (dismissed / responded * 100.0) if responded > 0 else 0.0
    response_rate = (responded / total * 100.0) if total > 0 else 0.0

    summary = (
        f"Toplam {total} önerinin {responded} tanesine yanıt verildi "
        f"(yanıt oranı: %{response_rate:.1f}); yanıtlananlarda uygulama %{adopt_rate:.1f}, "
        f"ret %{dismissal_rate:.1f}. Uygulanan aksiyonların beklenen tutarı: "
        f"{_fmt(total_impact)}; gerçekleşmiş finansal etki bu ölçümde hesaplanmıyor."
    )

    return DecisionSuccessMetrics(
        org_id=org_id,
        total_recommendations=total,
        responded_count=responded,
        unresponded_count=unresponded,
        adopted_count=adopted,
        deferred_count=deferred,
        dismissed_count=dismissed,
        open_count=open_count,
        closed_count=closed_count,
        adoption_rate_pct=round(adopt_rate, 2),
        correction_rate_pct=round(dismissal_rate, 2),
        dismissal_rate_pct=round(dismissal_rate, 2),
        response_rate_pct=round(response_rate, 2),
        accepted_expected_amount_cents=total_impact,
        total_impact_cents=total_impact,
        summary=summary,
    )
