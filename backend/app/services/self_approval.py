"""When the person who proposed is also the person who decides.

The product's rule is that the system proposes and a human decides, and managers stay in the loop.
In a company with one owner the proposer and the only decider are the same person; making them
"approve" their own proposal as if a second pair of eyes existed would be a ritual that protects
nothing, and forbidding it would make the company unable to act. So (`docs/payment-plan-approval.md`):

* the proposer is the ONLY decider of the company -> allowed, in one honest step: the person confirms
  a sentence that says proposer and approver are the same person (`SELF_DECISION_ACK`), and the
  decision record carries `self_decided: true` with that sentence;
* ANOTHER decider (an active owner or admin) exists and the amount is above the company's materiality
  threshold (`services/materiality`) -> not allowed: the other decider decides, and the proposal waits;
* another decider exists and the amount is at or below the threshold -> allowed, the same one-step
  confirmation, recorded the same way (a trivial amount must not need a colleague).

This is the one rule for every approve-type decision that has a separate proposer. Today that is the
payment-plan change. The others carry no proposer: category rules and month close are decided by the one
person who acts (`require_decider_or_smmm`, `require_smmm`), held entries have the system as proposer and
the authority matrix as the decider, and a held row or document is an answer to a question, not a proposal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency_totals import fmt_money
from app.models.decision import Decision, DecisionKind
from app.services import materiality
from app.services.accountant import active_member_ids

DECIDER_ROLES = ("owner", "admin")

# One month: the cycle a company's payments and reports repeat on, so splitting one payment into pieces
# across a few days or weeks is still seen as one decision.
SELF_APPROVAL_WINDOW_DAYS = 30

# What the person confirms. The server compares it exactly, so a client cannot pass a placeholder.
SELF_DECISION_ACK = (
    "Öneren ve onaylayan aynı kişi: bu öneriyi ben veriyorum ve ben onaylıyorum. "
    "Karar bu notla kaydedilir."
)

NOT_SELF = "not_self"
ACKNOWLEDGE = "acknowledge"  # may decide their own proposal, after confirming the sentence
BLOCKED = "blocked"  # another decider exists and the amount is above the threshold


@dataclass(frozen=True)
class SelfDecision:
    state: str
    message: str | None = None


async def other_decider_exists(db: AsyncSession, org_id: str, user_id: str) -> bool:
    """Is there an active owner or admin of the organisation other than this person?"""
    return bool(await active_member_ids(db, org_id, DECIDER_ROLES, excluding=user_id))


async def self_approved_total(
    db: AsyncSession, org_id: str, user_id: str, currency: str | None, *, now: datetime | None = None
) -> int:
    """What this person approved of their own proposals in the last SELF_APPROVAL_WINDOW_DAYS, in `currency`.

    Read from the decision records (`after.amount_cents` / `after.currency`, written for a self-decided
    approval), so it is the same trail an auditor reads.
    """
    since = (now or datetime.now(UTC)) - timedelta(days=SELF_APPROVAL_WINDOW_DAYS)
    rows = (
        await db.execute(
            select(Decision.after).where(
                Decision.org_id == org_id, Decision.kind == DecisionKind.PLAN_CHANGE.value,
                Decision.outcome == "approved", Decision.decided_by == user_id, Decision.decided_at >= since,
            )
        )
    ).scalars().all()
    cur = (currency or "").strip().upper()
    return sum(
        int(a.get("amount_cents") or 0)
        for a in rows
        if a and a.get("self_decided") and str(a.get("currency") or "").strip().upper() == cur
    )


def assess(
    *, proposer_id: str, user_id: str, others: bool, amount_cents: int | None, currency: str | None,
    threshold: int, threshold_currency: str, prior_cents: int = 0,
) -> SelfDecision:
    """Pure: may this decider decide this proposal, and does it need the acknowledgement?

    `threshold` is the one stored on the proposal; `prior_cents` is what the same person approved for
    themselves in the window (`self_approved_total`).
    """
    if proposer_id != user_id:
        return SelfDecision(NOT_SELF)
    if not others or not materiality.is_material(threshold, threshold_currency, amount_cents, currency, prior_cents):
        return SelfDecision(ACKNOWLEDGE)
    limit = fmt_money(threshold, threshold_currency)
    tail = (
        "Şirkette başka bir sahip ya da yönetici var: öneren kişi kendi önerisini onaylayamaz, "
        "diğer yöneticinin onayı gerekir."
    )
    if amount_cents is None:
        why = "Tutar bilinmiyor (kalem bulunamadı), bu yüzden eşiğin üstünde sayıldı."
    elif not currency or currency.strip().upper() != threshold_currency.upper():
        why = f"Tutar ({fmt_money(amount_cents, currency)}) eşiğin para biriminden farklı, karşılaştırılamadı; eşiğin üstünde sayıldı."
    elif amount_cents > threshold:
        why = f"Bu tutar ({fmt_money(amount_cents, currency)}) eşiğin ({limit}) üstünde."
    else:
        why = (
            f"Bu tutar ({fmt_money(amount_cents, currency)}) tek başına eşiğin ({limit}) altında, ama son "
            f"{SELF_APPROVAL_WINDOW_DAYS} günde kendi onayladığınız değişikliklerin toplamı "
            f"eşiği aşıyor ({fmt_money(prior_cents + amount_cents, currency)})."
        )
    return SelfDecision(BLOCKED, f"{why} {tail}")
