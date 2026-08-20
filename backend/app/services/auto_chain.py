"""
Auto-Chain Service — Agent tamamlanınca downstream agent'ları tetikle.

When a CFO analysis completes, Risk and Audit agents can auto-run
using the CFO result as input. When Risk completes, Compliance
can use it. CEO synthesis waits for CFO + any additional agents.

Chain map:
  cfo_complete    → [risk, audit, ceo_synthesis]
  risk_complete   → [compliance, ceo_synthesis]
  cto_complete    → [ceo_synthesis]
  cmo_complete    → [ceo_synthesis]

The chain is non-blocking: failures are logged, never raised.
CEO synthesis only runs if it hasn't already run in the current context.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Chain definition ──────────────────────────────────────────────────────────

# Maps "agent_complete" → list of agents to enqueue next
AGENT_CHAIN: dict[str, list[str]] = {
    "cfo":  ["risk", "audit"],
    "risk": ["compliance"],
}

# Agents that should trigger CEO synthesis when ANY of them complete
# (CEO synthesis runs if CFO has a result, regardless of others)
CEO_TRIGGER_AGENTS = {"cfo", "cto", "cmo", "coo", "chro"}

# ── Cross-agent feedback signal rules ─────────────────────────────────────────
# When agent A completes with a specific signal, it triggers inquiry in agent B.
# Format: agent → list of (signal_check_fn, target_agent, signal_label)

def _cfo_has_critical_anomalies(ctx: Any) -> bool:
    """CFO found critical financial anomalies — ask CTO if infra is the cause."""
    cfo = ctx.last_cfo_result or {}
    anomalies = cfo.get("anomalies") or []
    return any(a.get("severity") == "critical" for a in anomalies)


def _cfo_has_cash_crisis(ctx: Any) -> bool:
    """CFO runway < 6 months — ask CHRO about hiring/attrition risk."""
    cfo = ctx.last_cfo_result or {}
    forecast = cfo.get("forecast") or {}
    base = (forecast.get("scenarios") or {}).get("base") or {}
    runway = base.get("runway_months")
    return runway is not None and runway < 6


def _cto_has_low_velocity(ctx: Any) -> bool:
    """CTO velocity declining — ask CHRO if engineering headcount is the cause."""
    cto = ctx.last_cto_result or {}
    velocity = cto.get("velocity") or {}
    trend = velocity.get("trend", "")
    score = (cto.get("cto_summary") or {}).get("overall_health_score", 10)
    return trend == "declining" or score < 5


def _cmo_has_high_cac(ctx: Any) -> bool:
    """CMO CAC rising — ask CFO if marketing budget cuts are needed."""
    cmo = ctx.last_cmo_result or {}
    campaigns = cmo.get("campaigns") or {}
    roas = campaigns.get("overall_roas", 10)
    return roas < 1.5  # ROAS below 1.5x = CAC problem


# (signal_fn, target_agent, human_readable_label)
FEEDBACK_RULES: dict[str, list[tuple]] = {
    "cfo": [
        (_cfo_has_critical_anomalies, "cto",  "CFO kritik anomali → CTO altyapı kontrolü"),
        (_cfo_has_cash_crisis,        "chro", "CFO düşük runway → CHRO işe alım/attrition riski"),
    ],
    "cto": [
        (_cto_has_low_velocity, "chro", "CTO düşük velocity → CHRO mühendis kadrosu kontrolü"),
    ],
    "cmo": [
        (_cmo_has_high_cac, "cfo", "CMO yüksek CAC → CFO bütçe analizi"),
    ],
}


# ── Main hook ─────────────────────────────────────────────────────────────────

async def build_conductor_plan_dict(
    *,
    org_id: str,
    agent: str,
    db: Any = None,
) -> dict[str, Any] | None:
    """Build a serializable ManagementConductor plan for result_metadata."""
    try:
        from app.services.company_context import get_company_context
        from app.platform.conductor import ManagementConductor, signals_from_company_context

        ctx = await get_company_context(org_id, db)
        agent_lower = agent.lower()
        ctx_dict = {
            "active_cfo_job_id": ctx.active_cfo_job_id,
            "last_cfo_result": ctx.last_cfo_result,
            "last_risk_result": ctx.last_risk_result,
            "last_cto_result": ctx.last_cto_result,
            "last_cmo_result": ctx.last_cmo_result,
            "last_chro_result": ctx.last_chro_result,
            "last_coo_result": ctx.last_coo_result,
        }
        signals = signals_from_company_context(ctx_dict)
        signals.add(f"{agent_lower}_complete")
        plan = ManagementConductor().plan(
            org_id=org_id,
            trigger=f"{agent_lower}_complete",
            available_signals=signals,
        )
        return plan.to_dict()
    except Exception as exc:
        logger.debug("build_conductor_plan_dict failed (non-fatal): %s", exc)
        return None


async def on_agent_complete(
    agent: str,
    org_id: str,
    result: dict[str, Any],
    db: Any = None,
) -> dict[str, Any] | None:
    """
    Called after an agent completes. Triggers downstream agents if conditions met.

    This runs as a background task — all errors are caught and logged,
    never propagated to the caller.

    Returns the conductor plan dict when available (for result_metadata).
    """
    conductor_plan_dict: dict[str, Any] | None = None
    try:
        from app.services.company_context import get_company_context, save_company_context
        from app.platform.conductor import ManagementConductor, signals_from_company_context

        ctx = await get_company_context(org_id, db)
        agent_lower = agent.lower()

        # ── Step 0: Management conductor plan ────────────────────────────────
        conductor_plan = None
        try:
            ctx_dict = {
                "active_cfo_job_id": ctx.active_cfo_job_id,
                "last_cfo_result": ctx.last_cfo_result,
                "last_risk_result": ctx.last_risk_result,
                "last_cto_result": ctx.last_cto_result,
                "last_cmo_result": ctx.last_cmo_result,
                "last_chro_result": ctx.last_chro_result,
                "last_coo_result": ctx.last_coo_result,
            }
            signals = signals_from_company_context(ctx_dict)
            signals.add(f"{agent_lower}_complete")
            conductor = ManagementConductor()
            conductor_plan = conductor.plan(
                org_id=org_id,
                trigger=f"{agent_lower}_complete",
                available_signals=signals,
            )
            conductor_plan_dict = conductor_plan.to_dict()
            logger.info(
                "Conductor plan org=%s trigger=%s runnable=%s",
                org_id,
                agent_lower,
                [r.value for r in conductor_plan.runnable_roles()],
            )
        except Exception as exc:
            logger.debug("Conductor plan skipped (non-fatal): %s", exc)

        runnable_roles = {
            p.role.value for p in (conductor_plan.roles if conductor_plan else []) if p.should_run
        }

        # ── Step 1: Run chained agents ────────────────────────────────────────
        downstream = AGENT_CHAIN.get(agent_lower, [])
        for next_agent in downstream:
            if conductor_plan and next_agent not in runnable_roles:
                logger.debug(
                    "Auto-chain: conductor skipped %s for org=%s",
                    next_agent,
                    org_id,
                )
                continue
            if ctx.has_required_data(next_agent):
                logger.info(
                    "Auto-chain: %s completed → enqueueing %s for org=%s",
                    agent, next_agent, org_id,
                )
                await _run_chained_agent(next_agent, org_id, ctx, db)
            else:
                logger.debug(
                    "Auto-chain: %s skipped — missing required data for org=%s",
                    next_agent, org_id,
                )

        # ── Step 2: Trigger CEO synthesis if warranted ────────────────────────
        if agent_lower in CEO_TRIGGER_AGENTS:
            # Only if CFO has a result (minimum requirement for CEO synthesis)
            if ctx.last_cfo_result is not None:
                logger.info(
                    "Auto-chain: %s completed → triggering CEO synthesis for org=%s",
                    agent, org_id,
                )
                await _run_ceo_synthesis(org_id, ctx, db)

        # ── Step 3: Cross-agent feedback loop ─────────────────────────────────
        # When an agent's result triggers a signal, notify or run a related agent.
        # This creates a bidirectional intelligence loop between C-Suite agents.
        feedback_rules = FEEDBACK_RULES.get(agent_lower, [])
        for signal_fn, target_agent, label in feedback_rules:
            try:
                if signal_fn(ctx):
                    # Only trigger if target agent hasn't already run recently
                    target_result_attr = f"last_{target_agent}_result"
                    has_recent_result = getattr(ctx, target_result_attr, None) is not None

                    if not has_recent_result:
                        logger.info(
                            "Feedback loop: %s signal → enqueueing %s for org=%s (%s)",
                            agent, target_agent, org_id, label,
                        )
                        await _run_chained_agent(target_agent, org_id, ctx, db)
                    else:
                        # Target already has data — send a cross-agent notification instead
                        logger.info(
                            "Feedback loop: %s signal → %s already has data, sending insight for org=%s (%s)",
                            agent, target_agent, org_id, label,
                        )
                        await _send_feedback_notification(
                            org_id=org_id,
                            from_agent=agent,
                            to_agent=target_agent,
                            label=label,
                            db=db,
                        )
            except Exception as e:
                logger.debug("Feedback rule error (non-fatal): %s", e)

        # ── Step 4: If risk just finished (or both present), run consensus ────
        if agent_lower in ("risk", "cfo") and ctx.last_cfo_result and ctx.last_risk_result:
            await _run_auto_consensus(org_id=org_id, ctx=ctx, db=db)

    except Exception as exc:
        logger.warning(
            "Auto-chain on_agent_complete failed (non-fatal): agent=%s org=%s error=%s",
            agent, org_id, exc,
        )
        return conductor_plan_dict

    return conductor_plan_dict


# ── Internal runners ──────────────────────────────────────────────────────────

async def _run_chained_agent(
    agent: str,
    org_id: str,
    ctx: Any,
    db: Any,
) -> None:
    """
    Run a chained agent using data already in the context.
    Each agent extracts its own inputs from the context.
    """
    try:
        import uuid
        from app.services.company_context import save_company_context

        job_id = f"auto-{agent}-{uuid.uuid4().hex[:8]}"
        ctx.set_active_job(agent, job_id)
        await save_company_context(ctx, db)

        if agent == "risk":
            await _run_risk_from_context(job_id, ctx, org_id, db)
        elif agent == "audit":
            await _run_audit_from_context(job_id, ctx, org_id, db)
        elif agent == "compliance":
            await _run_compliance_from_context(job_id, ctx, org_id, db)

    except Exception as exc:
        logger.warning("Auto-chain agent=%s failed: %s", agent, exc)


async def _run_risk_from_context(
    job_id: str, ctx: Any, org_id: str, db: Any
) -> None:
    """Extract risk-relevant data from CFO result and run risk pipeline."""
    try:
        from app.agents.risk.orchestrator import run_risk_pipeline
        from app.services.company_context import get_company_context, save_company_context

        cfo = ctx.last_cfo_result or {}
        # Build KRI CSV from CFO financial data
        kri_csv = _build_kri_csv_from_cfo(cfo)
        risk_csv = _build_risk_csv_from_cfo(cfo)

        if not kri_csv and not risk_csv:
            logger.debug("Auto-chain risk: no CFO data to build KRIs, skipping")
            return

        result = await run_risk_pipeline(
            job_id=job_id,
            kri_csv=kri_csv,
            risk_register_csv=risk_csv,
            company_name=ctx.company_name,
        )

        # Save result back to context
        ctx_fresh = await get_company_context(org_id, db)
        ctx_fresh.update_agent_result("risk", {
            "risk_summary": getattr(result.get("risk_summary"), "__dict__", result.get("risk_summary")),
            "auto_generated": True,
            "source_job": job_id,
        })
        await save_company_context(ctx_fresh, db)
        logger.info("Auto-chain risk pipeline completed for org=%s", org_id)

        # Auto-run consensus on cash_risk / revenue_outlook after CFO+risk available
        await _run_auto_consensus(org_id=org_id, ctx=ctx_fresh, db=db)

    except Exception as exc:
        logger.warning("Auto-chain risk pipeline error: %s", exc)


async def _run_auto_consensus(*, org_id: str, ctx: Any, db: Any) -> None:
    """Run consensus topics when enough agent claims exist (non-fatal)."""
    try:
        from app.services.negotiation.consensus_engine import ConsensusEngine

        if not (ctx.last_cfo_result and ctx.last_risk_result):
            return
        engine = ConsensusEngine()
        for topic in ("cash_risk", "revenue_outlook"):
            try:
                result = await engine.run_consensus(
                    org_id=org_id,
                    topic=topic,
                    resolution_mode="weighted",
                    ctx=ctx,
                    db=db,
                )
                conflict_n = len(getattr(result, "conflicts", None) or [])
                logger.info(
                    "Auto-consensus topic=%s org=%s conflicts=%d agreement=%.2f",
                    topic,
                    org_id,
                    conflict_n,
                    float(getattr(result, "agreement_score", 0) or 0),
                )
            except Exception as topic_exc:
                logger.debug("Auto-consensus topic=%s failed: %s", topic, topic_exc)
    except Exception as exc:
        logger.debug("Auto-consensus skipped (non-fatal): %s", exc)


async def _run_audit_from_context(
    job_id: str, ctx: Any, org_id: str, db: Any
) -> None:
    """Extract audit-relevant data from CFO result and run audit pipeline."""
    try:
        from app.agents.audit.orchestrator import run_audit_pipeline
        from app.services.company_context import get_company_context, save_company_context

        cfo = ctx.last_cfo_result or {}
        findings_csv = _build_audit_findings_from_cfo(cfo)

        if not findings_csv:
            logger.debug("Auto-chain audit: no CFO data for findings, skipping")
            return

        result = await run_audit_pipeline(
            job_id=job_id,
            findings_csv=findings_csv,
            company_name=ctx.company_name,
        )

        ctx_fresh = await get_company_context(org_id, db)
        ctx_fresh.update_agent_result("audit", {
            "audit_summary": getattr(result.get("audit_summary"), "__dict__", result.get("audit_summary")),
            "auto_generated": True,
            "source_job": job_id,
        })
        await save_company_context(ctx_fresh, db)
        logger.info("Auto-chain audit pipeline completed for org=%s", org_id)

    except Exception as exc:
        logger.warning("Auto-chain audit pipeline error: %s", exc)


async def _run_compliance_from_context(
    job_id: str, ctx: Any, org_id: str, db: Any
) -> None:
    """Run compliance check using risk context."""
    try:
        from app.agents.compliance.orchestrator import run_compliance_pipeline
        from app.services.company_context import get_company_context, save_company_context

        result = await run_compliance_pipeline(
            job_id=job_id,
            company_name=ctx.company_name,
        )

        ctx_fresh = await get_company_context(org_id, db)
        ctx_fresh.update_agent_result("compliance", {
            "compliance_summary": getattr(
                result.get("compliance_summary"), "__dict__",
                result.get("compliance_summary")
            ),
            "auto_generated": True,
            "source_job": job_id,
        })
        await save_company_context(ctx_fresh, db)
        logger.info("Auto-chain compliance pipeline completed for org=%s", org_id)

    except Exception as exc:
        logger.warning("Auto-chain compliance pipeline error: %s", exc)


async def _run_ceo_synthesis(org_id: str, ctx: Any, db: Any) -> None:
    """
    Run CEO synthesis using the new context-aware endpoint.

    Uses /ceo/synthesize which reads CompanyContext directly —
    no need to re-run CFO/CTO pipelines. Much faster and uses ALL
    available agent results (CFO + CTO + CMO + COO + CHRO + Risk + Audit).
    """
    try:
        # Skip if CEO synthesis already ran recently (within last hour)
        if ctx.last_ceo_result:
            from datetime import datetime, timezone
            updated = datetime.fromisoformat(ctx.updated_at.replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - updated
            if age.total_seconds() < 3600:
                logger.debug("Auto-chain CEO synthesis: recent result exists, skipping")
                return

        from app.services.company_context import get_company_context, save_company_context
        from app.agents.ceo.orchestrator import (
            node_condense_summaries,
            node_synthesis,
            node_strategic_priorities,
            node_board_deck,
            DEFAULT_CEO_RUN_CONFIG,
        )
        import uuid

        job_id = f"auto-ceo-{uuid.uuid4().hex[:8]}"

        # Build CEOState from ALL available CompanyContext results
        initial_state = {
            "job_id": job_id,
            "company_name": ctx.company_name,
            "logs": [],
            "min_confidence": 1.0,
            "awaiting_review": False,
            "_cfo_result":        ctx.last_cfo_result        or {},
            "_cto_result":        ctx.last_cto_result        or {},
            "_cmo_result":        ctx.last_cmo_result        or {},
            "_coo_result":        ctx.last_coo_result        or {},
            "_chro_result":       ctx.last_chro_result       or {},
            "_risk_result":       ctx.last_risk_result       or {},
            "_audit_result":      ctx.last_audit_result      or {},
            "_compliance_result": ctx.last_compliance_result or {},
        }

        config = {"configurable": {"ceo_run_config": DEFAULT_CEO_RUN_CONFIG}}

        # Run synthesis chain (skip pipeline fan-out — use cached results)
        state = await node_condense_summaries(initial_state, config)  # type: ignore[arg-type]
        state = await node_synthesis(state, config)                    # type: ignore[arg-type]
        state = await node_strategic_priorities(state, config)         # type: ignore[arg-type]
        state = await node_board_deck(state, config)                   # type: ignore[arg-type]

        # Save enriched CEO result to CompanyContext
        ctx_fresh = await get_company_context(org_id, db)
        agents_used = [
            a for a in ["cfo", "cto", "cmo", "coo", "chro", "risk", "audit"]
            if getattr(ctx, f"last_{a}_result", None) is not None
        ]
        ctx_fresh.update_agent_result("ceo", {
            "financial_summary":    state.get("financial_summary"),
            "tech_summary":         state.get("tech_summary"),
            "marketing_summary":    state.get("marketing_summary"),
            "ops_summary":          state.get("ops_summary"),
            "hr_summary":           state.get("hr_summary"),
            "cross_risks":          state.get("cross_risks") or [],
            "strategic_priorities": state.get("strategic_priorities") or [],
            "board_deck":           state.get("board_deck"),
            "agents_used":          agents_used,
            "auto_generated":       True,
            "source_job":           job_id,
        })
        await save_company_context(ctx_fresh, db)
        logger.info(
            "Auto-chain CEO synthesis completed for org=%s using agents=%s",
            org_id, agents_used,
        )

    except Exception as exc:
        logger.warning("Auto-chain CEO synthesis error: %s", exc)


# ── CSV builders ──────────────────────────────────────────────────────────────

def _build_kri_csv_from_cfo(cfo: dict[str, Any]) -> str:
    """Build minimal KRI CSV from CFO financial metrics."""
    rows = ["kri_name,value,threshold,unit,trend"]
    pnl = cfo.get("pnl") or {}
    cashflow = cfo.get("cashflow") or {}

    if pnl.get("net_margin") is not None:
        rows.append(f"Net Profit Margin,{pnl['net_margin']:.1f},15,%,stable")
    if pnl.get("revenue") is not None:
        rows.append(f"Revenue,{pnl['revenue']:.0f},0,TRY,stable")
    if cashflow.get("operating_cash_flow") is not None:
        ocf = cashflow["operating_cash_flow"]
        rows.append(f"Operating Cash Flow,{ocf:.0f},0,TRY,stable")

    return "\n".join(rows) if len(rows) > 1 else ""


def _build_risk_csv_from_cfo(cfo: dict[str, Any]) -> str:
    """Build minimal risk register CSV from CFO anomalies and alerts."""
    rows = ["risk_id,description,likelihood,impact,category"]
    alerts = cfo.get("alerts") or []

    for i, alert in enumerate(alerts[:10], 1):
        desc = str(alert.get("message", "")).replace(",", ";")
        category = alert.get("category", "financial")
        rows.append(f"R{i:03d},{desc},3,3,{category}")

    return "\n".join(rows) if len(rows) > 1 else ""


def _build_audit_findings_from_cfo(cfo: dict[str, Any]) -> str:
    """Build audit findings CSV from CFO anomalies."""
    rows = ["finding_id,title,severity,status,category"]
    anomalies = cfo.get("anomalies") or []

    for i, anomaly in enumerate(anomalies[:10], 1):
        title = str(anomaly.get("description", "")).replace(",", ";")
        severity = anomaly.get("severity", "medium")
        rows.append(f"F{i:03d},{title},{severity},open,financial")

    return "\n".join(rows) if len(rows) > 1 else ""


# ── Feedback notification helper ──────────────────────────────────────────────

async def _send_feedback_notification(
    org_id: str,
    from_agent: str,
    to_agent: str,
    label: str,
    db: Any,
) -> None:
    """
    Send an in-app notification when a cross-agent feedback signal fires
    but the target agent already has recent data.

    This keeps the user informed about cross-domain correlations without
    re-running expensive pipelines.
    """
    try:
        from app.services.notification_service import NotificationService

        agent_labels = {
            "cfo":        "CFO",
            "cto":        "CTO",
            "cmo":        "CMO",
            "coo":        "COO",
            "chro":       "CHRO",
            "risk":       "Risk",
            "audit":      "İç Denetim",
            "compliance": "Uyumluluk",
        }

        from_label = agent_labels.get(from_agent.lower(), from_agent.upper())
        to_label   = agent_labels.get(to_agent.lower(), to_agent.upper())

        message = (
            f"{from_label} analizi, {to_label} alanında yeni bir sinyal tespit etti: "
            f"{label}. {to_label} verilerinizi güncellemek için ilgili sayfayı kontrol edin."
        )

        svc = NotificationService(db)
        await svc.create(
            org_id=org_id,
            level="warning",
            domain=from_agent,
            message=message,
            source=f"auto_chain.feedback_loop",
            priority_score=65,
        )
        logger.info(
            "Feedback notification sent: %s → %s for org=%s",
            from_agent, to_agent, org_id,
        )
    except Exception as exc:
        logger.debug("Feedback notification failed (non-fatal): %s", exc)
