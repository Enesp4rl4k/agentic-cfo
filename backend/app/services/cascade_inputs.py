"""The measured baseline a cascade simulation may start from: the company's one source of cash and burn.

Cash is the proven balance (`bank_accounts.proven_balances`) and runway/burn are `runway.compute_runway`'s
(both through `company_runway`). Nothing is derived from a net change times a runway, and nothing here is
filled in: what the books cannot prove is absent from the result, and the simulator then names it as
missing instead of running on a constant.

The runway's BASIS travels with its figures (`RunwayBasis`): whether the balance is known or assumed, its date,
the months used, the assumption sentence, the account-identity question. Whatever is built on the figures
(an alert, an API answer, a trigger result) carries it and may not claim more than it says: only a `known`
basis may be called proven, and only a proven one may raise a critical alert.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.company_runway import company_runway
from app.services.runway import COMPUTED, NOT_BURNING


@dataclass
class RunwayBasis:
    status: str
    basis: str | None                 # "known" | "assumed" | None (no runway measured)
    balance_basis: str | None         # "known" | "assumed" | None (no balance)
    as_of: str | None
    months_used: int
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    identity_uncertain: bool = False
    identity_note: str | None = None
    message: str = ""                 # the runway's own sentence, with every assumption it states
    cash_known: bool = False

    @property
    def proven(self) -> bool:
        """True only when the cash and the burn are measured with nothing assumed and no open identity question."""
        return (
            self.status in (COMPUTED, NOT_BURNING)
            and self.basis == "known"
            and self.balance_basis == "known"
            and not self.identity_uncertain
        )

    def sentence(self) -> str:
        """What a text built on these figures may say about their basis. "kanıtlı" only when proven."""
        if self.proven:
            return f"Dayanak: kanıtlı kasa bakiyesi ({self.as_of})."
        if self.cash_known:
            return f"Dayanak: kasa bakiyesi kanıtlanmış sayılmaz. {self.message}"
        return "Dayanak: kasa bakiyesi bilinmiyor."

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "proven": self.proven}


def basis_of(block: dict[str, Any]) -> RunwayBasis:
    """The basis of a `compute_runway` block, every field kept."""
    return RunwayBasis(
        status=str(block.get("status")),
        basis=block.get("basis"),
        balance_basis=block.get("balance_basis"),
        as_of=block.get("as_of"),
        months_used=int(block.get("months_used") or 0),
        assumptions=list(block.get("assumptions") or []),
        identity_uncertain=bool(block.get("identity_uncertain")),
        identity_note=block.get("identity_note"),
        message=str(block.get("message") or ""),
        cash_known=block.get("opening_cash_cents") is not None,
    )


def baseline_from(block: dict[str, Any]) -> tuple[dict[str, Any], RunwayBasis]:
    """Keyword arguments (kuruş) for `get_cascade_simulator` and the basis they rest on.

    Only keys the company's data proves are present.
    """
    out: dict[str, Any] = {}
    if block.get("opening_cash_cents") is not None:
        out["cash_balance"] = int(block["opening_cash_cents"])
    if block["status"] == COMPUTED and block.get("runway_months") is not None:
        out["runway_months"] = float(block["runway_months"])
    if block["status"] in (COMPUTED, NOT_BURNING) and block.get("avg_monthly_net_cents") is not None:
        out["monthly_burn"] = max(0, -int(block["avg_monthly_net_cents"]))
    return out, basis_of(block)


async def measured_baseline_with_basis(db: AsyncSession, org_id: str) -> tuple[dict[str, Any], RunwayBasis]:
    return baseline_from(await company_runway(db, org_id))


async def measured_baseline(db: AsyncSession, org_id: str) -> dict[str, Any]:
    """The simulator keyword arguments only (see `measured_baseline_with_basis` for the basis)."""
    return (await measured_baseline_with_basis(db, org_id))[0]
