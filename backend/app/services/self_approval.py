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

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency_totals import fmt_money
from app.models.organization import Organization
from app.services import materiality
from app.services.accountant import active_member_ids

DECIDER_ROLES = ("owner", "admin")

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


def assess(
    *, org: Organization | None, proposer_id: str, user_id: str, others: bool, amount_cents: int, currency: str | None
) -> SelfDecision:
    """Pure: may this decider decide this proposal, and does it need the acknowledgement?"""
    if proposer_id != user_id:
        return SelfDecision(NOT_SELF)
    if others and materiality.is_material(org, amount_cents, currency):
        applied = org.materiality_applied if org is not None else None
        return SelfDecision(
            BLOCKED,
            f"Bu tutar ({fmt_money(amount_cents, currency)}) eşiğin üstünde ve şirkette başka bir sahip ya da "
            "yönetici var: öneren kişi kendi önerisini onaylayamaz, diğer yöneticinin onayı gerekir. "
            f"Eşik: {materiality.basis_text(applied)}",
        )
    return SelfDecision(ACKNOWLEDGE)
