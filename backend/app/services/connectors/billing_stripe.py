"""
Stripe billing connector — paid invoices → canonical transaction CSV.

Uses org.stripe_customer_id when STRIPE_SECRET_KEY is configured.
Graceful no-op in dev when Stripe is unavailable.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.connectors.csv_utils import transactions_to_csv
from app.services.ingest.feed import Feed, FeedFailed

logger = logging.getLogger(__name__)


async def pull_stripe_revenue_csv(
    org_id: str,
    db: AsyncSession,
    *,
    days: int = 90,
) -> tuple[bytes, str, str | None]:
    """Return (csv_bytes, filename, partial reason) for Stripe paid invoices.

    Not configured (no key, no customer): an empty file, nothing to pull. A Stripe error RAISES `FeedFailed`
    (it used to be an empty file, which looked like "no revenue"). Every invoice is counted; one whose amount or
    date Stripe did not state is written with an empty cell and held, not skipped and not 0; more pages than the
    one fetched is a PARTIAL pull.
    """
    from app.config import get_settings
    from app.models.organization import Organization

    settings = get_settings()
    secret = getattr(settings, "stripe_secret_key", None) or ""
    if not secret:
        logger.debug("Stripe revenue pull skipped: no STRIPE_SECRET_KEY")
        return b"", "", None

    org = await db.get(Organization, str(org_id))
    if org is None or not getattr(org, "stripe_customer_id", None):
        logger.debug("Stripe revenue pull skipped: org %s has no stripe_customer_id", org_id)
        return b"", "", None

    try:
        import stripe

        stripe.api_key = secret
        invoices = stripe.Invoice.list(
            customer=str(org.stripe_customer_id),
            status="paid",
            limit=100,
        )
        data = list(invoices.data or [])
        more = bool(getattr(invoices, "has_more", False))
    except Exception as exc:
        logger.warning("Stripe revenue pull failed org=%s: %s", org_id, type(exc).__name__)
        raise FeedFailed(f"Stripe faturaları alınamadı: {type(exc).__name__}") from exc

    feed = Feed("billing_stripe")
    for inv in feed.each(data):
        paid = getattr(inv, "amount_paid", None)
        transitions = getattr(inv, "status_transitions", None)
        paid_at = getattr(transitions, "paid_at", None) if transitions is not None else None
        ts = paid_at or getattr(inv, "created", None)
        date = datetime.fromtimestamp(int(ts), tz=UTC).strftime("%Y-%m-%d") if ts else None
        number = getattr(inv, "number", None) or getattr(inv, "id", "") or ""
        currency = getattr(inv, "currency", None)
        # Stripe's amounts are integers in the currency's minor unit: exact, never ambiguous.
        feed.add(
            amount=None if paid is None else paid / 100, direction="income", date=date, currency=currency,
            description=f"Stripe invoice {number}", reference=getattr(inv, "id", "") or "",
            evidence={"amount_paid": paid, "date": date, "currency": currency, "number": number},
            category="revenue",
        )
    if more:
        feed.partial = "Stripe'ın sonraki fatura sayfası çekilmedi (en fazla 100 fatura okunur)"
    rows = [
        {
            "date": r["date"] or "", "amount": "" if r["amount_cents"] is None else r["amount_cents"] / 100,
            "description": r["description"], "category": r["category"], "reference": r["reference"],
            "type": r["type"] or "?", "currency": r["currency"] or "",
        }
        for r in feed.rows
    ]
    if not rows:
        return b"", "", feed.partial
    today = datetime.now(UTC).strftime("%Y%m%d")
    return transactions_to_csv(rows), f"stripe_revenue_{today}.csv", feed.partial
