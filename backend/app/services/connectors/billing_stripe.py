"""
Stripe billing connector — paid invoices → canonical transaction CSV.

Uses org.stripe_customer_id when STRIPE_SECRET_KEY is configured.
Graceful no-op in dev when Stripe is unavailable.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.connectors.csv_utils import transactions_to_csv

logger = logging.getLogger(__name__)


async def pull_stripe_revenue_csv(
    org_id: str,
    db: AsyncSession,
    *,
    days: int = 90,
) -> tuple[bytes, str]:
    """Return (csv_bytes, filename) for Stripe paid invoices."""
    try:
        from app.config import get_settings
        from app.models.organization import Organization

        settings = get_settings()
        secret = getattr(settings, "stripe_secret_key", None) or ""
        if not secret:
            logger.debug("Stripe revenue pull skipped: no STRIPE_SECRET_KEY")
            return b"", ""

        org = await db.get(Organization, str(org_id))
        if org is None or not getattr(org, "stripe_customer_id", None):
            logger.debug("Stripe revenue pull skipped: org %s has no stripe_customer_id", org_id)
            return b"", ""

        import stripe

        stripe.api_key = secret
        customer_id = str(org.stripe_customer_id)

        invoices = stripe.Invoice.list(
            customer=customer_id,
            status="paid",
            limit=100,
        )

        transactions: list[dict[str, Any]] = []
        for inv in invoices.data or []:
            amount_paid = getattr(inv, "amount_paid", 0) or 0
            amount = float(amount_paid) / 100.0
            if amount <= 0:
                continue
            paid_at = None
            transitions = getattr(inv, "status_transitions", None)
            if transitions is not None:
                paid_at = getattr(transitions, "paid_at", None)
            ts = paid_at or getattr(inv, "created", None)
            if ts:
                date_str = datetime.fromtimestamp(int(ts), tz=UTC).strftime("%Y-%m-%d")
            else:
                date_str = datetime.now(UTC).strftime("%Y-%m-%d")
            inv_id = getattr(inv, "id", "") or ""
            number = getattr(inv, "number", None) or inv_id
            transactions.append(
                {
                    "date": date_str,
                    "amount": amount,
                    "description": f"Stripe invoice {number}",
                    "category": "revenue",
                    "reference": inv_id,
                }
            )

        if not transactions:
            return b"", ""

        today = datetime.now(UTC).strftime("%Y%m%d")
        return transactions_to_csv(transactions), f"stripe_revenue_{today}.csv"
    except Exception as exc:
        logger.warning("Stripe revenue pull failed org=%s: %s", org_id, exc)
        return b"", ""
