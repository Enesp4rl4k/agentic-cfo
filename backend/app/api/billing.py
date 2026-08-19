"""
Stripe Billing API — subscription management endpoints.

Endpoints
---------
GET  /billing/plans                        → list all plans with features + prices
GET  /billing/subscription                 → current org subscription status
POST /billing/checkout                     → create Stripe Checkout session
POST /billing/portal                       → create Stripe Customer Portal session
POST /billing/cancel                       → cancel subscription (at period end)
POST /billing/webhook                      → Stripe webhook handler (no auth)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.services.stripe_billing import PLANS, get_stripe_service

router = APIRouter(tags=["billing"])


# ── Request models ────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str              # "starter" | "pro" | "enterprise"
    interval: str = "month"  # "month" | "year"
    success_url: str
    cancel_url: str


class CancelRequest(BaseModel):
    at_period_end: bool = True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/billing/plans")
async def list_plans() -> dict[str, Any]:
    """
    List all available subscription plans with features and pricing.
    Public endpoint — no authentication required.
    """
    plans_out = []
    for plan_id, cfg in PLANS.items():
        plans_out.append({
            "id": cfg.id,
            "name": cfg.name,
            "price_monthly_try": cfg.price_monthly_try,
            "price_yearly_try": cfg.price_yearly_try,
            "yearly_savings_pct": round(
                (1 - cfg.price_yearly_try / (cfg.price_monthly_try * 12)) * 100
            ),
            "max_orgs": cfg.max_orgs if cfg.max_orgs > 0 else None,
            "max_uploads_per_month": cfg.max_uploads_per_month if cfg.max_uploads_per_month > 0 else None,
            "max_users": cfg.max_users if cfg.max_users > 0 else None,
            "features": cfg.features,
        })

    return {"data": {"plans": plans_out}, "error": None}


@router.get("/billing/subscription")
async def get_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the current organization's subscription status."""
    org_id = str(user.org_id) if user.org_id else None
    if not org_id:
        return {
            "data": {
                "plan": "free",
                "status": "inactive",
                "stripe_customer_id": None,
                "stripe_subscription_id": None,
                "period_end": None,
                "limits": None,
            },
            "error": None,
        }

    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    plan_id = org.subscription_plan or "free"
    plan_cfg = PLANS.get(plan_id)

    return {
        "data": {
            "plan": plan_id,
            "plan_name": plan_cfg.name if plan_cfg else plan_id.title(),
            "status": org.subscription_status or "inactive",
            "stripe_customer_id": org.stripe_customer_id,
            "stripe_subscription_id": org.stripe_subscription_id,
            "period_end": org.subscription_period_end.isoformat() if org.subscription_period_end else None,
            "limits": {
                "max_orgs": plan_cfg.max_orgs if plan_cfg else 1,
                "max_uploads_per_month": plan_cfg.max_uploads_per_month if plan_cfg else 5,
                "max_users": plan_cfg.max_users if plan_cfg else 2,
            } if plan_cfg else None,
            "features": plan_cfg.features if plan_cfg else [],
        },
        "error": None,
    }


@router.post("/billing/checkout")
async def create_checkout_session(
    body: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Create a Stripe Checkout session for the given plan.
    Returns a redirect URL — the client should redirect to this URL.
    """
    if body.plan not in PLANS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid plan '{body.plan}'. Valid plans: {list(PLANS.keys())}",
        )

    org_id = str(user.org_id) if user.org_id else str(user.id)

    svc = get_stripe_service()
    result = await svc.create_checkout_session(
        user_id=str(user.id),
        org_id=org_id,
        plan=body.plan,
        interval=body.interval,
        success_url=body.success_url,
        cancel_url=body.cancel_url,
        customer_email=user.email,
    )

    if result.get("error") and not result.get("url"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=result["error"],
        )

    return {"data": result, "error": None}


@router.post("/billing/portal")
async def create_billing_portal(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Create a Stripe Customer Portal session.
    Users can manage payment methods, cancel, or change plans.
    """
    org_id = str(user.org_id) if user.org_id else None
    if not org_id:
        raise HTTPException(status_code=400, detail="No organization associated with this user")

    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()

    if not org or not org.stripe_customer_id:
        raise HTTPException(
            status_code=404,
            detail="No Stripe customer found. Please create a subscription first.",
        )

    from app.config import get_settings
    settings = get_settings()
    frontend_url = getattr(settings, "frontend_url", "http://localhost:3000")
    return_url = f"{frontend_url}/billing"

    svc = get_stripe_service()
    portal = await svc.create_billing_portal_session(
        customer_id=org.stripe_customer_id,
        return_url=return_url,
    )

    if portal.get("error") and not portal.get("url"):
        raise HTTPException(status_code=503, detail=portal["error"])

    return {"data": portal, "error": None}


@router.post("/billing/cancel")
async def cancel_subscription(
    body: CancelRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Cancel the organization's current subscription."""
    org_id = str(user.org_id) if user.org_id else None
    if not org_id:
        raise HTTPException(status_code=400, detail="No organization found")

    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()

    if not org or not org.stripe_subscription_id:
        raise HTTPException(status_code=404, detail="No active subscription found")

    svc = get_stripe_service()
    cancel_result = await svc.cancel_subscription(
        subscription_id=org.stripe_subscription_id,
        at_period_end=body.at_period_end,
    )

    return {"data": cancel_result, "error": None}


@router.post("/billing/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(alias="stripe-signature", default=""),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Stripe webhook endpoint — no authentication required.
    Stripe signs every request with a signature header.

    Register this URL in Stripe Dashboard:
    https://dashboard.stripe.com/webhooks
    → Add endpoint: https://yourdomain.com/api/v1/billing/webhook
    → Events: checkout.session.completed, customer.subscription.*,
               invoice.payment_failed
    """
    payload = await request.body()

    svc = get_stripe_service()
    event = svc.parse_webhook(payload=payload, signature=stripe_signature)

    if event is None:
        # If Stripe is not configured, return 200 to avoid Stripe retries
        # (dev/test environment)
        return {"received": True, "processed": False, "reason": "stripe not configured"}

    result = await svc.handle_webhook_event(event=event, db=db)
    return {"received": True, "processed": True, **result}


# ── Usage metering endpoints ──────────────────────────────────────────────────

@router.get("/billing/usage")
async def get_usage(
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Return this month's usage summary for the current org.

    Response:
      {
        "org_id": "...",
        "plan": "pro",
        "plan_display": "Pro",
        "period": "2024-08",
        "resources": {
          "upload": {"used": 3, "limit": 5, "unlimited": false, "pct": 60.0},
          "agent_run": {...},
          "connector_sync": {...}
        },
        "allowed_agents": ["cfo", "risk", "audit"]
      }
    """
    from app.services.usage_meter import get_usage_summary

    org_id = str(user.org_id) if user.org_id else None
    if not org_id:
        raise HTTPException(status_code=400, detail="Organizasyona üye değilsiniz.")

    summary = await get_usage_summary(org_id, db)
    return {"data": summary, "error": None}


@router.get("/billing/check-limit/{resource}")
async def check_resource_limit(
    resource: str,
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Check if the org can perform another action for the given resource.

    resource: "upload" | "agent_run" | "connector_sync"

    Returns:
      {"allowed": true/false, "plan": "...", "used": N, "limit": M}

    Use this for frontend gates before showing upload/run buttons.
    """
    from app.services.usage_meter import (
        get_org_plan, get_monthly_usage, PLAN_LIMITS,
        check_upload_limit, UsageLimitExceeded,
    )

    valid_resources = {"upload", "agent_run", "connector_sync"}
    if resource not in valid_resources:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz kaynak. Geçerli değerler: {sorted(valid_resources)}",
        )

    org_id = str(user.org_id) if user.org_id else None
    if not org_id:
        raise HTTPException(status_code=400, detail="Organizasyona üye değilsiniz.")

    plan_name = await get_org_plan(org_id, db)
    limits    = PLAN_LIMITS.get(plan_name, PLAN_LIMITS["free"])
    limit_key = f"{resource}s_per_month"
    max_val   = limits.get(limit_key, -1)
    current   = await get_monthly_usage(org_id, resource, db)

    allowed = max_val == -1 or current < max_val

    return {
        "data": {
            "allowed":   allowed,
            "resource":  resource,
            "plan":      plan_name,
            "used":      current,
            "limit":     max_val,
            "unlimited": max_val == -1,
            "upgrade_url": "/billing" if not allowed else None,
        },
        "error": None,
    }

    return {"received": True, **result}
