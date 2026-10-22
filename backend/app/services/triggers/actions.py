"""The trigger action registry — what a trigger does once its condition holds.

Each ``ActionKind`` from ``contracts.py`` maps to an async handler:

    handler(db, org_id, definition, payload) -> dict

Handlers validate their own ``action_params`` (deliberate layering — the
envelope stays free-form in the contract) and persist their side effects.
P4-1 landed ``alert.dispatch``; P4-2 added ``webhook.call``, ``analysis.start``,
``cascade.simulate`` and ``report.generate``, so every ``ActionKind`` in the
contract now has a handler; a kind missing from the registry (a partial
deployment, say) is reported as an ``error`` run rather than silently doing
nothing.

A handler raises ``ValueError`` on malformed ``action_params``; the engine turns
that into an ``error`` run. Validation happens before any write, so there is no
partial state to roll back.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert_rule import AlertHistory
from app.models.analysis_job import AnalysisJob
from app.models.report import Report, ReportFormat, ReportType
from app.services.triggers.contracts import TriggerDefinition

logger = logging.getLogger(__name__)

# db, org_id, definition, event payload -> JSON-serialisable action result
ActionHandler = Callable[
    [AsyncSession, str, TriggerDefinition, dict[str, Any]], Awaitable[dict[str, Any]]
]


async def _alert_dispatch(
    db: AsyncSession,
    org_id: str,
    definition: TriggerDefinition,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Write a durable alert (``alert_history``) and optionally fan it out.

    The alert is always recorded so the trigger's effect is auditable. If the
    params carry a ``webhook_url`` the alert is also delivered best-effort via
    the existing ``AlertDispatcher``; delivery failure is reported in the result
    but never fails the run (the alert is already persisted).
    """
    params = definition.action_params
    message = str(
        params.get("message")
        or payload.get("message")
        or f"Trigger '{definition.name}' fired"
    )
    severity = str(params.get("severity") or "warning")
    channels = params.get("channels") or []

    alert = AlertHistory(
        org_id=org_id,
        message=message,
        severity=severity,
        source=f"trigger:{definition.name}",
        channels_sent=json.dumps(channels) if channels else None,
    )
    db.add(alert)
    await db.flush()

    result: dict[str, Any] = {
        "alert_id": alert.id,
        "severity": severity,
        "message": message,
        "channels": channels,
        "delivered": False,
    }

    webhook_url = params.get("webhook_url")
    if webhook_url:
        try:
            from app.services.alert_dispatcher import AlertDispatcher

            dispatched = await AlertDispatcher.dispatch_webhook(
                webhook_url,
                event_type="trigger.alert",
                data={"alert_id": alert.id, "message": message, "severity": severity},
            )
            result["delivered"] = bool(dispatched.delivered)
            result["delivery_status"] = dispatched.status_code
        except Exception as exc:  # pragma: no cover - network best-effort
            logger.warning("trigger alert webhook delivery failed: %s", exc)
            result["delivered"] = False
            result["delivery_error"] = str(exc)

    return result


# ``cascade.simulate`` action_params keys that map onto CascadeSimulator.simulate.
_SIMULATE_KWARGS = ("runway_months", "drop_pct", "role", "usd_try_increase_pct", "inflation_pct")


async def _webhook_call(
    db: AsyncSession,
    org_id: str,
    definition: TriggerDefinition,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """POST the event to an arbitrary URL (``action_params.url``).

    Uses the existing ``AlertDispatcher.dispatch_webhook`` (bounded timeout,
    best-effort). A ``https://dummy…`` target is treated as delivered without a
    network call — the same escape hatch the alert tests rely on.
    """
    url = str(definition.action_params.get("url") or "").strip()
    if not url:
        raise ValueError("webhook.call requires action_params.url")

    from app.services.alert_dispatcher import AlertDispatcher

    event_type = str(definition.action_params.get("event_type") or f"trigger.{definition.name}")
    data = {"org_id": org_id, "trigger": definition.name, "payload": payload}
    dispatched = await AlertDispatcher.dispatch_webhook(url, event_type, data)
    return {
        "delivered": bool(dispatched.delivered),
        "status_code": dispatched.status_code,
        "target": dispatched.target,
    }


async def _analysis_start(
    db: AsyncSession,
    org_id: str,
    definition: TriggerDefinition,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Enqueue a CFO analysis job (fire-and-forget) for ``job_id``.

    The id comes from ``action_params.job_id`` or, failing that, the event's
    ``payload.job_id`` (a ``job.completed`` trigger naturally carries the job it
    just saw). Enqueue returns how it was dispatched (``queued`` / ``inline``),
    which is reported rather than flattened to a boolean.
    """
    job_id = str(
        definition.action_params.get("job_id") or payload.get("job_id") or ""
    ).strip()
    if not job_id:
        raise ValueError("analysis.start requires a job_id (action_params or payload)")

    from app.worker import enqueue_analysis

    budget_input = definition.action_params.get("budget_input")
    dispatch = await enqueue_analysis(job_id, budget_input)
    return {"job_id": job_id, "dispatch": dispatch}


async def _cascade_simulate(
    db: AsyncSession,
    org_id: str,
    definition: TriggerDefinition,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Run a what-if cascade simulation and return its scenario summary.

    Loads the org's CompanyContext (pnl / cashflow / forecast + domain data),
    builds a ``CascadeSimulator`` and simulates the trigger named in
    ``action_params.trigger``. Trigger-specific params (``runway_months``,
    ``drop_pct``, ``role``, …) are passed through to the simulator.
    """
    from app.services.cascade_simulator import TriggerType, get_cascade_simulator
    from app.services.company_context import get_company_context

    raw_trigger = str(definition.action_params.get("trigger") or "").strip()
    if not raw_trigger:
        raise ValueError("cascade.simulate requires action_params.trigger")
    try:
        trigger = TriggerType(raw_trigger)
    except ValueError as exc:
        raise ValueError(
            f"unknown cascade trigger {raw_trigger!r}; "
            f"expected one of {[t.value for t in TriggerType]}"
        ) from exc

    ctx_obj = await get_company_context(org_id, db)
    cfo = (ctx_obj.last_cfo_result or {}) if ctx_obj else {}
    dash = cfo.get("dashboard") or cfo
    ctx = {
        "pnl": dash.get("pnl") or {},
        "cashflow": dash.get("cashflow") or {},
        "forecast": dash.get("forecast") or {},
        "chro_data": (ctx_obj.last_chro_result or {}) if ctx_obj else {},
        "cto_data": (ctx_obj.last_cto_result or {}) if ctx_obj else {},
        "cmo_data": (ctx_obj.last_cmo_result or {}) if ctx_obj else {},
        "coo_data": (ctx_obj.last_coo_result or {}) if ctx_obj else {},
    }
    sim = get_cascade_simulator(**ctx)
    kwargs = {k: definition.action_params[k] for k in _SIMULATE_KWARGS if k in definition.action_params}
    result = sim.simulate(trigger, **kwargs)
    return {"trigger": trigger.value, "result": result.to_dict()}


async def _report_generate(
    db: AsyncSession,
    org_id: str,
    definition: TriggerDefinition,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Generate a board-ready executive PDF for a job's dashboard and store it.

    The job id comes from ``action_params.job_id`` or the event payload (a
    ``job.completed`` trigger naturally carries the job it just saw). The
    dashboard JSON the analysis already persisted for that job feeds
    ``generate_executive_report``; weasyprint runs in a worker thread so a
    multi-second render never blocks the event loop. The PDF lands under
    ``reports/<job_id>/`` next to the xlsx the report agent writes, and a
    ``Report`` row records the path so the existing report API can serve it.

    The job must belong to the trigger's org — an action_params override is
    caller-supplied, never trusted on faith.
    """
    job_id = str(
        definition.action_params.get("job_id") or payload.get("job_id") or ""
    ).strip()
    if not job_id:
        raise ValueError("report.generate requires a job_id (action_params or payload)")

    job = await db.get(AnalysisJob, job_id)
    if job is None or (job.org_id is not None and job.org_id != org_id):
        raise ValueError(f"report.generate: no analysis job {job_id} for this org")

    latest = (
        await db.execute(
            select(Report)
            .where(
                Report.job_id == job_id,
                Report.report_format == ReportFormat.JSON,
            )
            .order_by(Report.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if latest is None or not latest.data:
        raise ValueError(
            f"report.generate: job {job_id} has no dashboard JSON yet "
            "(analysis incomplete)"
        )

    company_name = str(definition.action_params.get("company_name") or "Şirket")
    raw_period = definition.action_params.get("period")
    period = str(raw_period) if raw_period else None

    from app.services.executive_report_pdf import generate_executive_report

    pdf_bytes = await asyncio.to_thread(
        generate_executive_report, latest.data, company_name, period
    )

    from app.config import get_settings

    output_dir = Path(get_settings().storage_local_path) / "reports" / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / "executive_report.pdf"
    file_path.write_bytes(pdf_bytes)

    report = Report(
        job_id=job_id,
        report_type=ReportType.FULL,
        report_format=ReportFormat.PDF,
        file_path=str(file_path),
    )
    db.add(report)
    await db.flush()
    return {
        "job_id": job_id,
        "report_id": report.id,
        "file_path": str(file_path),
        "bytes": len(pdf_bytes),
    }


ACTION_REGISTRY: dict[str, ActionHandler] = {
    "alert.dispatch": _alert_dispatch,
    "analysis.start": _analysis_start,
    "cascade.simulate": _cascade_simulate,
    "report.generate": _report_generate,
    "webhook.call": _webhook_call,
}
