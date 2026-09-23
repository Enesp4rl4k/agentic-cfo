"""Karar Defteri — record once, measure honestly. (P2 · Sonuç döngüsü)

A decision enters this ledger at the moment it is made:

 - `expected` is filled SERVER-SIDE from the packet's own numbers, so
   nobody can rewrite what they claimed to have expected afterwards;
 - `actual` is measured later from data that arrived AFTER the decision
   (business dates > decided_at, newest finished analysis in scope), and
   `variance` carries only what the two snapshots honestly support —
   runway movement and the realised net — never a forced comparison
   between numbers that mean different things.

Deterministic: no LLM in the path.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.decision_log import DecisionLog
from app.models.transaction import Transaction

logger = logging.getLogger(__name__)

# Statuses whose pipeline finished — their reports and transactions are
# the latest state of the world for measuring an outcome.
_MEASURABLE_STATUSES = (JobStatus.COMPLETED, JobStatus.AWAITING_REVIEW)


class DecisionError(Exception):
    """A precondition of the decision loop is not met (API maps → HTTP)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _norm(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:  # SQLite round-trip drops tzinfo
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


async def record_decision(
    db: AsyncSession,
    *,
    job: AnalysisJob,
    user_id: str,
    option_id: str,
    topic: str | None = None,
    rationale: str | None = None,
) -> DecisionLog:
    """Snapshot the packet's numbers into `expected` and open the row.

    Contract: mid-run job → `running`; a job with no report →
    `no_options`; an option this packet does not offer → `unknown_option`.
    """
    from app.services.decision_packet import RUNNING_STATUSES, build_decision_packet

    if str(job.status) in RUNNING_STATUSES:
        raise DecisionError(
            "running",
            "Analiz henüz tamamlanmadı — karar, sonuçlar hazır olduğunda kaydedilir.",
        )

    packet = await build_decision_packet(db, job)
    options = packet.get("options") or []
    if not options:
        raise DecisionError(
            "no_options",
            "Bu analiz için rapor yok — kaydedilecek bir seçenek sunulamıyor.",
        )
    option = next((o for o in options if o["id"] == option_id), None)
    if option is None:
        raise DecisionError("unknown_option", "Böyle bir seçenek bu pakette yok.")

    sit = packet.get("situation") or {}
    expected: dict[str, Any] = {
        # The situation the decision hangs on (report numbers, kuruş).
        "revenue_12m": sit.get("revenue_12m"),
        "net_change_12m": sit.get("net_change_12m"),
        "runway_months": sit.get("runway_months"),
        "forecast_12m_net": sit.get("forecast_12m_net"),
        # The chosen option's computed consequence.
        "option_id": option.get("id"),
        "option_label": option.get("label"),
        "option_net_impact": option.get("base_net_impact"),
        "option_runway_after": option.get("runway_after"),
        "generated_at": packet.get("generated_at"),
    }

    clean_topic = (topic or "").strip()
    decision = DecisionLog(
        org_id=job.org_id,
        job_id=job.id,
        topic=clean_topic or f"Karar: {option.get('label') or option_id}",
        chosen_option_id=str(option_id),
        chosen_option_label=str(option.get("label") or option_id),
        rationale=(rationale or "").strip() or None,
        expected=expected,
        status="open",
        created_by=user_id,
    )
    db.add(decision)
    return decision


async def measure_outcome(
    db: AsyncSession, *, decision: DecisionLog, note: str | None = None
) -> DecisionLog:
    """Close the loop: what actually happened after this decision.

    Realised figures come from the NEWEST finished analysis in scope
    (org-wide when the decision carries an org, else its own job) — the
    point of measuring is that new data arrived since the decision.
    """
    if decision.status != "open":
        raise DecisionError(
            "already_closed", "Bu kararın sonucu zaten ölçülmüş — ilk ölçüm geçerli."
        )

    decided_at = _norm(decision.created_at)

    q = select(AnalysisJob).where(AnalysisJob.status.in_(_MEASURABLE_STATUSES))
    if decision.org_id:
        q = q.where(AnalysisJob.org_id == decision.org_id)
    else:
        q = q.where(AnalysisJob.id == decision.job_id)
    data_job = (
        await db.execute(q.order_by(desc(AnalysisJob.created_at)).limit(1))
    ).scalar_one_or_none()
    if data_job is None:
        raise DecisionError(
            "no_data",
            "Ölçüm için tamamlanmış analiz yok — sonuç, veri geldiğinde ölçülebilir.",
        )

    # Realised since the decision, by business date (what happened after).
    income_kurus, expense_kurus, tx_count = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        case((Transaction.type == "income", Transaction.amount_kurus),
                             else_=0)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case((Transaction.type == "expense", Transaction.amount_kurus),
                             else_=0)
                    ),
                    0,
                ),
                func.count(Transaction.id),
            ).where(
                Transaction.job_id == data_job.id,
                Transaction.transaction_date > decided_at,
            )
        )
    ).one()
    income_kurus, expense_kurus = int(income_kurus), int(expense_kurus)
    realized_net = income_kurus - expense_kurus

    # Latest runway — the one number expectation and outcome genuinely share.
    from app.services.decision_packet import load_pnl_cashflow_forecast

    _pnl, _cashflow, forecast = await load_pnl_cashflow_forecast(db, data_job.id)
    base = (forecast.get("scenarios") or {}).get("base") or {}
    runway_latest = base.get("runway_months")

    expected = decision.expected or {}
    variance: dict[str, Any] = {"realized_net_kurus": realized_net}
    if runway_latest is not None and expected.get("runway_months") is not None:
        variance["runway_delta"] = round(
            float(runway_latest) - float(expected["runway_months"]), 2
        )

    now = datetime.now(UTC)
    decision.actual = {
        "realized_net_kurus": realized_net,
        "income_kurus": income_kurus,
        "expense_kurus": expense_kurus,
        "transactions_since": int(tx_count),
        "runway_months_latest": runway_latest,
        "data_job_id": data_job.id,
        "decided_at": decided_at.isoformat() if decided_at else None,
        "as_of": now.isoformat(),
    }
    decision.variance = variance
    decision.outcome_note = (note or "").strip() or None
    decision.status = "closed"
    decision.measured_at = now
    return decision
