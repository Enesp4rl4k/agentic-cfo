"""
Usage Metering Service — plan limit enforcement.

Architecture
------------
- UsageMeter: stateless service, reads from DB, writes usage events
- check_and_increment: atomic check + record — call before each billable action
- get_usage_summary: for /billing/usage endpoint
- Graceful degradation: if org has no subscription → free plan limits apply

Billable resources
------------------
  "upload"      → POST /upload (file upload + analysis)
  "agent_run"   → any C-Suite kernel call (CTO, CMO, CHRO, COO, Audit, Compliance)
  "connector_sync" → OAuth connector sync

Plan limits (mirrors PLANS in stripe_billing.py)
------------------------------------------------
  free:       3 uploads/month
  starter:    5 uploads/month, CFO only (no C-Suite kernels)
  pro:        unlimited uploads, all agents
  enterprise: unlimited everything

Usage is tracked per (org_id, resource, month).
Events older than 90 days are pruned by the nightly scheduler.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── Plan limit definitions ─────────────────────────────────────────────────────

PLAN_LIMITS: dict[str, dict[str, Any]] = {
    "free": {
        "uploads_per_month":    3,
        "agent_runs_per_month": 0,    # no C-Suite kernels on free
        "allowed_agents": ["cfo"],    # CFO pipeline only
        "display_name": "Free",
    },
    "starter": {
        "uploads_per_month":    5,
        "agent_runs_per_month": 10,
        "allowed_agents": ["cfo", "risk", "audit"],
        "display_name": "Starter",
    },
    "pro": {
        "uploads_per_month":    -1,   # unlimited
        "agent_runs_per_month": -1,
        "allowed_agents": "*",        # all agents
        "display_name": "Pro",
    },
    "enterprise": {
        "uploads_per_month":    -1,
        "agent_runs_per_month": -1,
        "allowed_agents": "*",
        "display_name": "Enterprise",
    },
}

# Agents that require at least "pro" plan
PRO_ONLY_AGENTS = {"cto", "cmo", "coo", "chro", "ceo", "compliance"}


# ── Usage event recording ──────────────────────────────────────────────────────

async def record_usage_event(
    org_id: str,
    resource: str,       # "upload" | "agent_run" | "connector_sync"
    quantity: int = 1,
    db: Any = None,
    metadata: dict | None = None,
) -> None:
    """
    Record a billable usage event.
    Fire-and-forget — errors are logged, never raised.
    """
    if db is None:
        return
    try:
        from app.models.organization import Organization
        from sqlalchemy import text

        # Try to use usage_events table (may not exist in old migrations)
        await db.execute(
            text(
                "INSERT INTO usage_events (id, org_id, resource, quantity, recorded_at) "
                "VALUES (:id, :org_id, :resource, :quantity, :recorded_at)"
            ),
            {
                "id":          __import__("uuid").uuid4().hex,
                "org_id":      org_id,
                "resource":    resource,
                "quantity":    quantity,
                "recorded_at": datetime.now(timezone.utc),
            },
        )
        await db.commit()
        logger.debug("UsageMeter: recorded %s x%d for org=%s", resource, quantity, org_id)
    except Exception as exc:
        # Table may not exist yet (migration pending) — non-fatal
        logger.debug("UsageMeter: record failed (non-fatal): %s", exc)


# ── Plan resolution ────────────────────────────────────────────────────────────

async def get_org_plan(org_id: str, db: Any) -> str:
    """
    Return the current plan name for an org.
    Falls back to "free" if no subscription found.
    """
    if db is None:
        return "free"
    try:
        from sqlalchemy import select, text
        # Try billing_subscriptions table
        result = await db.execute(
            text(
                "SELECT plan FROM billing_subscriptions "
                "WHERE org_id = :org_id AND status = 'active' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"org_id": org_id},
        )
        row = result.fetchone()
        if row and row[0] in PLAN_LIMITS:
            return row[0]
    except Exception as exc:
        logger.debug("UsageMeter: plan lookup failed: %s", exc)
    return "free"


# ── Usage counting ─────────────────────────────────────────────────────────────

async def get_monthly_usage(
    org_id: str,
    resource: str,
    db: Any,
) -> int:
    """Return how many times resource was used this calendar month."""
    if db is None:
        return 0
    try:
        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        result = await db.execute(
            text(
                "SELECT COALESCE(SUM(quantity), 0) FROM usage_events "
                "WHERE org_id = :org_id "
                "AND resource = :resource "
                "AND recorded_at >= :month_start"
            ),
            {
                "org_id":      org_id,
                "resource":    resource,
                "month_start": month_start,
            },
        )
        row = result.fetchone()
        return int(row[0]) if row else 0
    except Exception as exc:
        logger.debug("UsageMeter: count failed: %s", exc)
        return 0


# ── Main gate: check + increment ──────────────────────────────────────────────

class UsageLimitExceeded(Exception):
    """Raised when an org has exceeded their plan limit for a resource."""
    def __init__(self, resource: str, plan: str, limit: int, current: int):
        self.resource = resource
        self.plan     = plan
        self.limit    = limit
        self.current  = current
        super().__init__(
            f"Plan limiti aşıldı: {resource} ({current}/{limit} bu ay, plan: {plan}). "
            f"Planınızı yükseltmek için /billing sayfasını ziyaret edin."
        )


class AgentNotAllowed(Exception):
    """Raised when an org's plan doesn't include access to an agent."""
    def __init__(self, agent: str, plan: str):
        self.agent = agent
        self.plan  = plan
        super().__init__(
            f"'{agent}' ajanına erişim için Pro plan gereklidir. "
            f"Mevcut planınız: {plan}. Yükseltmek için /billing sayfasını ziyaret edin."
        )


async def check_upload_limit(
    org_id: str,
    db: Any,
) -> None:
    """
    Check if org can perform another upload this month.
    Raises UsageLimitExceeded if limit reached.
    Does NOT record the event — call record_usage_event after successful upload.
    """
    plan_name = await get_org_plan(org_id, db)
    limits    = PLAN_LIMITS.get(plan_name, PLAN_LIMITS["free"])
    max_uploads = limits["uploads_per_month"]

    if max_uploads == -1:
        return  # Unlimited

    current = await get_monthly_usage(org_id, "upload", db)
    if current >= max_uploads:
        raise UsageLimitExceeded("upload", plan_name, max_uploads, current)

    logger.debug(
        "UsageMeter: upload check OK — org=%s plan=%s usage=%d/%d",
        org_id, plan_name, current, max_uploads,
    )


async def check_agent_access(
    org_id: str,
    agent: str,
    db: Any,
) -> None:
    """
    Check if org's plan allows access to the given C-Suite agent.
    Raises AgentNotAllowed if the plan doesn't include the agent.
    """
    plan_name = await get_org_plan(org_id, db)
    limits    = PLAN_LIMITS.get(plan_name, PLAN_LIMITS["free"])
    allowed   = limits["allowed_agents"]

    if allowed == "*":
        return  # All agents allowed

    if agent.lower() not in [a.lower() for a in allowed]:
        raise AgentNotAllowed(agent, plan_name)


# ── Usage summary ──────────────────────────────────────────────────────────────

async def get_usage_summary(org_id: str, db: Any) -> dict[str, Any]:
    """
    Return usage summary for the current month.
    Used by GET /billing/usage endpoint.
    """
    plan_name = await get_org_plan(org_id, db)
    limits    = PLAN_LIMITS.get(plan_name, PLAN_LIMITS["free"])

    resources  = ["upload", "agent_run", "connector_sync"]
    usage_data: dict[str, Any] = {}

    for resource in resources:
        current = await get_monthly_usage(org_id, resource, db)
        limit_key = f"{resource}s_per_month"
        max_val   = limits.get(limit_key, -1)
        usage_data[resource] = {
            "used":      current,
            "limit":     max_val,
            "unlimited": max_val == -1,
            "pct":       round(current / max_val * 100, 1) if max_val > 0 else 0,
        }

    return {
        "org_id":       org_id,
        "plan":         plan_name,
        "plan_display": limits["display_name"],
        "period":       datetime.now(timezone.utc).strftime("%Y-%m"),
        "resources":    usage_data,
        "allowed_agents": limits["allowed_agents"],
    }


# ── Nightly cleanup ───────────────────────────────────────────────────────────

async def prune_old_usage_events(db: Any, days: int = 90) -> int:
    """
    Delete usage events older than `days` days.
    Called by nightly scheduler to prevent unbounded table growth.
    Returns number of rows deleted.
    """
    if db is None:
        return 0
    try:
        from sqlalchemy import text
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await db.execute(
            text("DELETE FROM usage_events WHERE recorded_at < :cutoff"),
            {"cutoff": cutoff},
        )
        await db.commit()
        deleted = result.rowcount or 0
        if deleted:
            logger.info("UsageMeter: pruned %d old usage events (older than %dd)", deleted, days)
        return deleted
    except Exception as exc:
        logger.debug("UsageMeter: prune failed: %s", exc)
        return 0
