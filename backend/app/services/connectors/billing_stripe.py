"""
Stripe billing connector — paid invoices and their credit notes → canonical transaction CSV.

Uses org.stripe_customer_id when STRIPE_SECRET_KEY is configured.
Graceful no-op in dev when Stripe is unavailable.

Two objects reach the ledger, each with the direction its OWN TYPE gives (never a sign, never a file rule):
paid invoices at `amount_paid` are income; credit notes (`stripe.CreditNote.list(customer=...)`) are expense rows
for the cash that went back to the customer (`refund_amount` + `out_of_band_amount`). A credit note that only
reduced the customer's balance moved no cash and is counted as ignored under a named rule; a void one likewise.
Stripe's amounts are integers in the currency's minor unit: they are converted through ONE table of ISO 4217
exponents (`ingest.currencies.minor_to_cents`), never by a flat "/ 100" (JPY has no minor unit, KWD has three),
and an amount that has no exact figure in the books is held, not rounded.

NOT reachable per customer, so NOT in this pull: refunds made directly on a charge (not through a credit note)
and disputes. Stripe lists `Refund` and `Dispute` by charge / payment intent, not by customer; they need an
account-level listing mapped back to this organisation's charges. Until then the bank statement is the cash truth.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.connectors.csv_utils import transactions_to_csv
from app.services.ingest.currencies import cents_text, is_currency_code, minor_to_cents
from app.services.ingest.feed import Feed, FeedFailed

logger = logging.getLogger(__name__)

# Where Stripe's API differs from ISO 4217: ISK and UGX are zero-decimal in ISO but two-decimal in the API.
# MGA is stated zero-decimal by Stripe and has two decimals in ISO 4217: the two disagree, so it is held, not scaled.
STRIPE_EXPONENT = {"ISK": 2, "UGX": 2}
STRIPE_UNSURE = frozenset({"MGA"})
CREDIT_NOTE_RULES = {"void": "credit_note_void", "balance": "credit_note_to_customer_balance"}


def stripe_amount(minor: Any, currency: Any) -> str | None:
    """A Stripe amount (integer, the currency's minor unit) as exact decimal text; None when it has none (held)."""
    code = str(currency or "").strip().upper()
    if minor is None or code in STRIPE_UNSURE or not is_currency_code(code):
        return None
    cents = minor_to_cents(minor, code, STRIPE_EXPONENT)
    return None if cents is None else cents_text(cents)


def _when(ts: Any) -> str | None:
    return datetime.fromtimestamp(int(ts), tz=UTC).strftime("%Y-%m-%d") if ts else None


def _credit_note_rows(feed: Feed, notes: list[Any]) -> None:
    """Each credit note as an expense row for the cash it sent back, or an ignored one with its named rule."""
    for cn in notes:
        currency = getattr(cn, "currency", None)
        refund, out_of_band = getattr(cn, "refund_amount", None), getattr(cn, "out_of_band_amount", None)
        if getattr(cn, "status", None) == "void":
            feed.ignore(CREDIT_NOTE_RULES["void"])
            continue
        if refund == 0 and not out_of_band and (getattr(cn, "credit_amount", None) or 0) > 0:
            feed.ignore(CREDIT_NOTE_RULES["balance"])     # reduced the customer's balance: no cash moved
            continue
        out = None if refund is None else refund + (out_of_band or 0)
        number = getattr(cn, "number", None) or getattr(cn, "id", "") or ""
        date = _when(getattr(cn, "created", None))
        feed.each([cn])
        feed.add(
            amount=stripe_amount(out, currency), direction="expense", date=date, currency=currency,
            description=f"Stripe credit note {number}", reference=getattr(cn, "id", "") or "",
            evidence={"refund_amount": refund, "out_of_band_amount": out_of_band, "date": date,
                      "currency": currency, "number": number},
            category="other_expense",
        )


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
    # Credit notes net the revenue. If they cannot be listed the pull is PARTIAL (gross revenue), never "complete".
    notes: list[Any] = []
    notes_more = False
    notes_failed: str | None = None
    try:
        notes_api = getattr(stripe, "CreditNote", None)
        if notes_api is None:
            notes_failed = "Stripe kredi notları bu sürümde listelenemiyor"
        else:
            listed = notes_api.list(customer=str(org.stripe_customer_id), limit=100)
            notes = list(listed.data or [])
            notes_more = bool(getattr(listed, "has_more", False))
    except Exception as exc:
        logger.warning("Stripe credit note pull failed org=%s: %s", org_id, type(exc).__name__)
        notes_failed = f"Stripe kredi notları alınamadı: {type(exc).__name__}"

    feed = Feed("billing_stripe")
    for inv in feed.each(data):
        paid = getattr(inv, "amount_paid", None)
        transitions = getattr(inv, "status_transitions", None)
        paid_at = getattr(transitions, "paid_at", None) if transitions is not None else None
        ts = paid_at or getattr(inv, "created", None)
        date = _when(ts)
        number = getattr(inv, "number", None) or getattr(inv, "id", "") or ""
        currency = getattr(inv, "currency", None)
        # Stripe's amounts are integers in the currency's minor unit: converted by that currency's exponent.
        feed.add(
            amount=stripe_amount(paid, currency), direction="income", date=date, currency=currency,
            description=f"Stripe invoice {number}", reference=getattr(inv, "id", "") or "",
            evidence={"amount_paid": paid, "date": date, "currency": currency, "number": number},
            category="revenue",
        )
    _credit_note_rows(feed, notes)
    why = [
        *(["Stripe'ın sonraki fatura sayfası çekilmedi (en fazla 100 fatura okunur)"] if more else []),
        *(["Stripe'ın sonraki kredi notu sayfası çekilmedi (en fazla 100 okunur)"] if notes_more else []),
        *([notes_failed] if notes_failed else []),
    ]
    feed.partial = "; ".join(why) or None
    rows = [
        {
            "date": r["date"] or "", "amount": "" if r["amount_cents"] is None else cents_text(r["amount_cents"]),
            "description": r["description"], "category": r["category"], "reference": r["reference"],
            "type": r["type"] or "?", "currency": r["currency"] or "",
        }
        for r in feed.rows
    ]
    if not rows:
        return b"", "", feed.partial
    today = datetime.now(UTC).strftime("%Y%m%d")
    return transactions_to_csv(rows), f"stripe_revenue_{today}.csv", feed.partial
