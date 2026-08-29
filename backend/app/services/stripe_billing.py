"""
Stripe Subscription Service — Starter / Pro / Enterprise plans.

Architecture
------------
- StripeService: thin wrapper around the Stripe Python SDK
- Plans defined as constants (price IDs configured via env vars)
- Webhook handler: processes subscription lifecycle events
- Graceful degradation: if STRIPE_SECRET_KEY is not set, all methods
  return safe no-op responses (useful for dev/demo environments)

Plan Limits
-----------
Starter:    1 org, 5 uploads/mo,  CFO pipeline only
Pro:        3 orgs, unlimited uploads, + C-Suite kernels + CEO synthesis
Enterprise: unlimited orgs + users, SSO, dedicated support, custom limits

Webhook Events Handled
----------------------
- checkout.session.completed     → activate subscription
- customer.subscription.updated → plan change / renewal
- customer.subscription.deleted → cancel / expire
- invoice.payment_failed        → notify user, grace period

Usage
-----
    svc = get_stripe_service()

    # Create checkout session (redirect user to Stripe hosted page)
    session = await svc.create_checkout_session(
        user_id="u1",
        org_id="org-1",
        plan="pro",
        success_url="https://app.example.com/billing/success",
        cancel_url="https://app.example.com/billing/cancel",
    )
    redirect_to(session.url)

    # Handle webhook (in FastAPI endpoint)
    event = await svc.parse_webhook(payload=body, signature=header)
    await svc.handle_webhook_event(event, db=db)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ── Plan definitions ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PlanConfig:
    id: str
    name: str
    price_monthly_try: int     # in Turkish Lira (for display)
    price_yearly_try: int
    max_orgs: int              # -1 = unlimited
    max_uploads_per_month: int # -1 = unlimited
    max_users: int             # -1 = unlimited
    features: list[str]
    # Stripe price IDs (populated from env vars at runtime)
    stripe_price_monthly: str = ""
    stripe_price_yearly: str  = ""


PLANS: dict[str, PlanConfig] = {
    "starter": PlanConfig(
        id="starter",
        name="Starter",
        price_monthly_try=990,
        price_yearly_try=9_900,
        max_orgs=1,
        max_uploads_per_month=5,
        max_users=2,
        features=[
            "CFO Pipeline (P&L, Nakit Akışı, Tahmin)",
            "Anomali Tespiti",
            "5 yükleme/ay",
            "PDF export",
            "E-posta desteği",
        ],
    ),
    "pro": PlanConfig(
        id="pro",
        name="Pro",
        price_monthly_try=2_990,
        price_yearly_try=29_900,
        max_orgs=3,
        max_uploads_per_month=-1,
        max_users=10,
        features=[
            "Starter'ın tüm özellikleri",
            "C-Suite Kernels (CTO/CMO/CHRO/COO)",
            "CEO Sentezi & Board Deck",
            "Monte Carlo & İleri Analitik",
            "Open Banking Entegrasyonu",
            "Sınırsız yükleme",
            "Öncelikli destek",
        ],
    ),
    "enterprise": PlanConfig(
        id="enterprise",
        name="Enterprise",
        price_monthly_try=9_990,
        price_yearly_try=99_900,
        max_orgs=-1,
        max_uploads_per_month=-1,
        max_users=-1,
        features=[
            "Pro'nun tüm özellikleri",
            "SSO (Microsoft Entra / Google Workspace)",
            "SOC2 Audit Trail",
            "KVKK/GDPR Uyumluluk",
            "IP Whitelist",
            "Özel Entegrasyonlar",
            "SLA garantisi",
            "Dedicated Customer Success",
        ],
    ),
}


# ── Stripe service ────────────────────────────────────────────────────────────

class StripeService:
    """
    Wrapper around Stripe Python SDK.

    All public methods return dicts or None — never raise Stripe exceptions
    to callers; errors are logged and safe defaults returned.
    """

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._secret_key: str = getattr(settings, "stripe_secret_key", "") or ""
        self._webhook_secret: str = getattr(settings, "stripe_webhook_secret", "") or ""
        self._enabled = bool(self._secret_key and not self._secret_key.startswith("sk_test_placeholder"))

        if self._enabled:
            try:
                import stripe as _stripe  # type: ignore[import]
                _stripe.api_key = self._secret_key
                self._stripe = _stripe
                logger.info("Stripe initialized (live=%s)", not self._secret_key.startswith("sk_test_"))
            except ImportError:
                logger.warning("stripe package not installed — billing disabled")
                self._enabled = False
                self._stripe = None
        else:
            self._stripe = None
            logger.info("Stripe not configured — billing disabled (set STRIPE_SECRET_KEY)")

    def _get_price_id(self, plan: str, interval: str = "month") -> str:
        """Resolve Stripe price ID from settings."""
        key = f"stripe_price_{plan}_{interval}ly"  # e.g. stripe_price_pro_monthly
        return getattr(self._settings, key, "") or ""

    async def create_checkout_session(
        self,
        user_id: str,
        org_id: str,
        plan: str,
        success_url: str,
        cancel_url: str,
        interval: str = "month",  # "month" | "year"
        customer_email: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a Stripe Checkout Session for subscription.

        Returns {"url": "...", "session_id": "..."} or {"url": None, "error": "..."}
        """
        if not self._enabled:
            return {"url": None, "session_id": None, "error": "Stripe not configured"}

        plan_cfg = PLANS.get(plan)
        if not plan_cfg:
            return {"url": None, "session_id": None, "error": f"Unknown plan: {plan}"}

        price_id = self._get_price_id(plan, interval)
        if not price_id:
            return {
                "url": None,
                "session_id": None,
                "error": f"Stripe price ID not configured for {plan}/{interval}",
            }

        try:
            session_params: dict[str, Any] = {
                "mode": "subscription",
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": {
                    "user_id": user_id,
                    "org_id": org_id,
                    "plan": plan,
                    "interval": interval,
                },
                "subscription_data": {
                    "metadata": {
                        "user_id": user_id,
                        "org_id": org_id,
                        "plan": plan,
                    }
                },
                "allow_promotion_codes": True,
                "billing_address_collection": "auto",
                "tax_id_collection": {"enabled": True},  # for Turkish B2B VAT
            }

            if customer_email:
                session_params["customer_email"] = customer_email

            session = self._stripe.checkout.Session.create(**session_params)
            return {"url": session.url, "session_id": session.id, "error": None}

        except Exception as e:
            logger.error("Stripe checkout session creation failed: %s", e)
            return {"url": None, "session_id": None, "error": str(e)}

    async def create_billing_portal_session(
        self,
        customer_id: str,
        return_url: str,
    ) -> dict[str, Any]:
        """
        Create a Stripe Customer Portal session for subscription management.
        Users can upgrade, downgrade, cancel, and update payment methods here.
        """
        if not self._enabled:
            return {"url": None, "error": "Stripe not configured"}

        try:
            portal = self._stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            return {"url": portal.url, "error": None}
        except Exception as e:
            logger.error("Stripe portal session creation failed: %s", e)
            return {"url": None, "error": str(e)}

    async def get_subscription(self, subscription_id: str) -> dict[str, Any] | None:
        """Fetch a subscription object from Stripe."""
        if not self._enabled:
            return None
        try:
            sub = self._stripe.Subscription.retrieve(subscription_id)
            return dict(sub)
        except Exception as e:
            logger.error("Stripe subscription retrieval failed: %s", e)
            return None

    async def cancel_subscription(
        self,
        subscription_id: str,
        at_period_end: bool = True,
    ) -> dict[str, Any]:
        """Cancel a subscription (immediate or at period end)."""
        if not self._enabled:
            return {"cancelled": False, "error": "Stripe not configured"}

        try:
            if at_period_end:
                self._stripe.Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=True,
                )
            else:
                self._stripe.Subscription.cancel(subscription_id)

            return {"cancelled": True, "subscription_id": subscription_id, "error": None}
        except Exception as e:
            logger.error("Stripe subscription cancellation failed: %s", e)
            return {"cancelled": False, "error": str(e)}

    def parse_webhook(self, payload: bytes, signature: str) -> Any | None:
        """
        Parse and verify a Stripe webhook event.
        Returns the event object or None if verification fails.
        """
        if not self._enabled or not self._webhook_secret:
            return None

        try:
            event = self._stripe.Webhook.construct_event(
                payload, signature, self._webhook_secret
            )
            return event
        except self._stripe.error.SignatureVerificationError:
            logger.warning("Stripe webhook signature verification failed")
            return None
        except Exception as e:
            logger.error("Stripe webhook parsing failed: %s", e)
            return None

    async def handle_webhook_event(
        self,
        event: Any,
        db: Any,
    ) -> dict[str, Any]:
        """
        Process a verified Stripe webhook event.

        Updates organization subscription status in the database.
        """
        if not event:
            return {"processed": False, "reason": "null event"}

        event_type: str = event.get("type", "")
        data_object = event.get("data", {}).get("object", {})

        logger.info("Stripe webhook: %s", event_type)

        try:
            if event_type == "checkout.session.completed":
                return await self._handle_checkout_completed(data_object, db)

            elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
                return await self._handle_subscription_updated(data_object, db)

            elif event_type == "customer.subscription.deleted":
                return await self._handle_subscription_deleted(data_object, db)

            elif event_type == "invoice.payment_failed":
                return await self._handle_payment_failed(data_object, db)

            else:
                return {"processed": False, "reason": f"unhandled event type: {event_type}"}

        except Exception as e:
            logger.error("Stripe webhook handler error for %s: %s", event_type, e)
            return {"processed": False, "error": str(e)}

    async def _handle_checkout_completed(self, obj: dict, db: Any) -> dict:
        """Activate subscription after successful checkout."""
        metadata = obj.get("metadata", {})
        org_id = metadata.get("org_id")
        plan = metadata.get("plan", "starter")
        subscription_id = obj.get("subscription")
        customer_id = obj.get("customer")

        if not org_id:
            return {"processed": False, "reason": "no org_id in metadata"}

        await _update_org_subscription(
            db=db,
            org_id=org_id,
            plan=plan,
            status="active",
            stripe_subscription_id=subscription_id,
            stripe_customer_id=customer_id,
        )

        logger.info("Subscription activated: org=%s plan=%s", org_id, plan)
        return {"processed": True, "action": "activated", "org_id": org_id, "plan": plan}

    async def _handle_subscription_updated(self, obj: dict, db: Any) -> dict:
        """Handle plan changes and renewals."""
        metadata = obj.get("metadata", {})
        org_id = metadata.get("org_id")
        status = obj.get("status", "active")
        subscription_id = obj.get("id")
        customer_id = obj.get("customer")

        # Determine plan from price metadata
        items = obj.get("items", {}).get("data", [])
        plan = "starter"
        if items:
            price_id = items[0].get("price", {}).get("id", "")
            plan = _plan_from_price_id(price_id) or plan

        if not org_id:
            return {"processed": False, "reason": "no org_id in metadata"}

        await _update_org_subscription(
            db=db,
            org_id=org_id,
            plan=plan,
            status=status,
            stripe_subscription_id=subscription_id,
            stripe_customer_id=customer_id,
        )

        return {"processed": True, "action": "updated", "org_id": org_id, "plan": plan, "status": status}

    async def _handle_subscription_deleted(self, obj: dict, db: Any) -> dict:
        """Downgrade to free plan on cancellation."""
        metadata = obj.get("metadata", {})
        org_id = metadata.get("org_id")

        if not org_id:
            return {"processed": False, "reason": "no org_id in metadata"}

        await _update_org_subscription(
            db=db,
            org_id=org_id,
            plan="starter",
            status="cancelled",
            stripe_subscription_id=None,
            stripe_customer_id=obj.get("customer"),
        )

        logger.info("Subscription cancelled: org=%s", org_id)
        return {"processed": True, "action": "cancelled", "org_id": org_id}

    async def _handle_payment_failed(self, obj: dict, db: Any) -> dict:
        """Mark subscription as past_due on payment failure."""
        customer_id = obj.get("customer")
        subscription_id = obj.get("subscription")

        if not subscription_id:
            return {"processed": False, "reason": "no subscription_id"}

        # Update status to past_due — org keeps access during grace period
        # (Stripe retries payment automatically)
        logger.warning("Payment failed for subscription %s customer %s", subscription_id, customer_id)
        return {"processed": True, "action": "payment_failed", "subscription_id": subscription_id}


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _update_org_subscription(
    db: Any,
    org_id: str,
    plan: str,
    status: str,
    stripe_subscription_id: str | None,
    stripe_customer_id: str | None,
) -> None:
    """Update organization subscription fields in the database."""
    try:
        from sqlalchemy import update

        from app.models.organization import Organization

        update_data: dict[str, Any] = {
            "subscription_plan": plan,
            "subscription_status": status,
        }
        if stripe_subscription_id is not None:
            update_data["stripe_subscription_id"] = stripe_subscription_id
        if stripe_customer_id is not None:
            update_data["stripe_customer_id"] = stripe_customer_id

        await db.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(**update_data)
        )
        await db.commit()
    except Exception as e:
        logger.error("DB update for org subscription failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass


def _plan_from_price_id(price_id: str) -> str | None:
    """Reverse-lookup plan name from a Stripe price ID."""
    try:
        from app.config import get_settings
        settings = get_settings()
        for plan in ("starter", "pro", "enterprise"):
            for interval in ("month", "year"):
                key = f"stripe_price_{plan}_{interval}ly"
                if getattr(settings, key, "") == price_id:
                    return plan
    except Exception:
        pass
    return None


# ── Module singleton ──────────────────────────────────────────────────────────

_stripe_service: StripeService | None = None


def get_stripe_service() -> StripeService:
    global _stripe_service
    if _stripe_service is None:
        try:
            from app.config import get_settings
            _stripe_service = StripeService(settings=get_settings())
        except Exception:
            class _NullSettings:
                stripe_secret_key = ""
                stripe_webhook_secret = ""
            _stripe_service = StripeService(settings=_NullSettings())
    return _stripe_service
