"""The amount above which a decision needs a senior person, measured against the company itself.

A fixed lira amount means something different to a company that spends 2 million a year and one
that spends 200 million. The materiality threshold is therefore a share of the company's OWN
monthly outflow:

    threshold = RATIO x average monthly outflow of the last complete months in the ledger,
                rounded to two significant figures, kept between FLOOR_CENTS and CEILING_CENTS.

While the ledger holds too little (fewer than MIN_MONTHS complete months with outflow, or no single
confirmed currency) the basis is the monthly outflow the company DECLARED (`size_profile`); with
neither there is no proposal and the fixed amount the authority policy always carried
(LEGACY_CENTS) keeps applying.

Nothing here changes who is asked by itself:

* a computed value is only a PROPOSAL. It applies after an owner or admin acknowledges it
  (`acknowledge`), and until then `threshold_cents` answers with the legacy amount, so an existing
  company never finds its approvals moved under it;
* the owner may set their own amount (`override`); both steps leave a decision record with the
  basis, and the basis is stored with the value so every place that applies the threshold can say
  "aylık ortalama çıkışınızın %5'i = ..." instead of a bare number;
* it is MATERIALITY only. Gates that protect the integrity of the books (a row that cannot be read,
  a currency, a direction, an account's identity, a failed reconciliation) are questions about one
  upload, not about size, and never read this value.

The ratio, the months, the floor and the ceiling are PROVISIONAL product values, stated once here.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import floor, log10
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency_totals import DEFAULT_BASE, fmt_money
from app.models.decision import DecidedVia, DecisionKind
from app.models.organization import Organization
from app.models.user import User
from app.services import decisions
from app.services.size_profile import (
    DECLARED_MONTHLY_OUTFLOW_CENTS,
    OUTFLOW_BAND_LABELS,
    OutflowBand,
)

RATIO = 0.05
MIN_MONTHS = 3
MAX_MONTHS = 6
FLOOR_CENTS = 5_000 * 100
CEILING_CENTS = 1_000_000 * 100
# The amount `platform/authority_matrix.DEFAULT_POLICY_RULES` has always carried for "high value".
LEGACY_CENTS = 100_000 * 100

MEASURED = "measured"
DECLARED = "declared"
LEGACY = "legacy"
OWNER_OVERRIDE = "owner_override"


class MaterialityError(Exception):
    """A refusal the API turns into a status code and a plain sentence."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def round_two_figures(cents: int) -> int:
    """Whole lira, two significant figures: 8333 lira reads as 8300, not 8333."""
    lira = max(1, cents // 100)
    step = 10 ** max(0, floor(log10(lira)) - 1)
    return floor(lira / step + 0.5) * step * 100  # half up, as people round


def clamp(cents: int) -> tuple[int, str | None]:
    if cents < FLOOR_CENTS:
        return FLOOR_CENTS, "floor"
    if cents > CEILING_CENTS:
        return CEILING_CENTS, "ceiling"
    return cents, None


def compute(
    *, measured: dict[str, Any] | None, declared_band: str | None
) -> dict[str, Any] | None:
    """Pure: the proposal for a measured monthly outflow, else a declared band, else None.

    `measured` is `{"avg_cents", "months", "currency"}`.
    """
    if measured is not None:
        kind, monthly, currency = MEASURED, int(measured["avg_cents"]), str(measured["currency"])
        extra: dict[str, Any] = {"months": list(measured["months"])}
    else:
        try:
            band = OutflowBand(declared_band) if declared_band else None
        except ValueError:
            band = None
        if band is None:
            return None
        kind, monthly, currency = DECLARED, DECLARED_MONTHLY_OUTFLOW_CENTS[band], DEFAULT_BASE
        extra = {"band": band.value}
    amount, clamped = clamp(round_two_figures(int(monthly * RATIO)))
    return {
        "amount_cents": amount,
        "currency": currency,
        "source": kind,
        "basis": {
            "kind": kind, "ratio": RATIO, "monthly_outflow_cents": monthly, "clamped": clamped,
            "floor_cents": FLOOR_CENTS, "ceiling_cents": CEILING_CENTS, **extra,
        },
    }


def _whole(cents: int, currency: str | None) -> str:
    text = fmt_money(round(cents / 100) * 100, currency)
    return text.replace(",00", "")


def basis_text(applied: dict[str, Any] | None) -> str:
    """The sentence that says where a threshold comes from. `applied` is a stored or proposed value."""
    if not applied:
        return (
            f"Sabit tutar: {_whole(LEGACY_CENTS, DEFAULT_BASE)}. Şirketinizin büyüklüğüne göre henüz "
            "hesaplanıp onaylanmadı."
        )
    amount = _whole(int(applied["amount_cents"]), applied.get("currency"))
    source = applied.get("source")
    if source == OWNER_OVERRIDE:
        return f"{amount}: sahibin belirlediği tutar."
    basis = applied.get("basis") or {}
    currency = applied.get("currency")
    pct = f"%{round(float(basis.get('ratio', RATIO)) * 100)}"
    monthly = _whole(int(basis.get("monthly_outflow_cents", 0)), currency)
    if source == MEASURED:
        months = basis.get("months") or []
        span = f"son {len(months)} tam ayın" if months else "son tam ayların"
        text = f"{span} aylık ortalama çıkışı {monthly}'in {pct}'i = {amount}"
    else:
        try:
            label = OUTFLOW_BAND_LABELS[OutflowBand(str(basis.get("band")))]
        except ValueError:
            label = "beyan edilen band"
        text = f"beyan ettiğiniz aylık çıkış bandı ({label}) ortası {monthly}'in {pct}'i = {amount}"
    note = {"floor": " (alt sınır uygulandı)", "ceiling": " (üst sınır uygulandı)"}.get(str(basis.get("clamped")), "")
    return text[0].upper() + text[1:] + note + "."


async def measure_monthly_outflow(db: AsyncSession, org_id: str) -> dict[str, Any] | None:
    """The average monthly cash outflow over the last complete months of the ledger, or None.

    Complete = before the current month. A month with no outflow is no evidence of a size and is left out.
    Needs a single headline currency (the ledger's own `effective_base`): amounts in several currencies are
    never added. The months used are returned so the basis can show them.
    """
    from app.services.ledger import ledger_summary
    from app.services.ledger_period import current_month

    summary = await ledger_summary(db, org_id)
    currency = summary.get("currency")
    if not currency:
        return None
    today = current_month()
    months = [
        (str(m["month"]), int(m["cash_out_cents"]))
        for m in summary.get("months", [])
        if str(m["month"]) < today and int(m["cash_out_cents"]) > 0
    ][-MAX_MONTHS:]
    if len(months) < MIN_MONTHS:
        return None
    return {
        "avg_cents": sum(c for _, c in months) // len(months),
        "months": [m for m, _ in months],
        "currency": str(currency),
    }


async def propose(db: AsyncSession, org: Organization) -> dict[str, Any] | None:
    return compute(
        measured=await measure_monthly_outflow(db, str(org.id)), declared_band=org.monthly_outflow_band
    )


def threshold_cents(org: Organization | None) -> int:
    """What applies now: the acknowledged or owner-set amount, else the legacy fixed amount."""
    applied = org.materiality_applied if org is not None else None
    return int(applied["amount_cents"]) if applied else LEGACY_CENTS


def threshold_currency(org: Organization | None) -> str:
    applied = org.materiality_applied if org is not None else None
    return str(applied.get("currency") or DEFAULT_BASE) if applied else DEFAULT_BASE


def is_material(org: Organization | None, amount_cents: int, currency: str | None) -> bool:
    """Is an amount above the threshold? An amount in another currency than the threshold's cannot be
    compared (no rate is kept), so it counts as material rather than being waved through."""
    if currency and currency.strip().upper() != threshold_currency(org).upper():
        return True
    return amount_cents > threshold_cents(org)


def current(org: Organization | None) -> dict[str, Any]:
    applied = org.materiality_applied if org is not None else None
    return {
        "threshold_cents": threshold_cents(org),
        "currency": threshold_currency(org),
        "source": (applied or {}).get("source", LEGACY),
        "acknowledged": bool(applied),
        "acknowledged_at": (applied or {}).get("acknowledged_at"),
        "acknowledged_by": (applied or {}).get("acknowledged_by"),
        "basis": (applied or {}).get("basis"),
        "basis_text": basis_text(applied),
    }


def default_rules(org: Organization | None, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The default policy with its high-value rule at the org's acknowledged threshold, and saying why.

    Untouched when nobody acknowledged a threshold: the policy then reads as it always did.
    """
    applied = org.materiality_applied if org is not None else None
    if not applied:
        return rules
    out = []
    for rule in rules:
        if rule.get("id") == "high_value":
            rule = {
                **rule,
                "when": {"amount_kurus_gt": int(applied["amount_cents"])},
                "note": f"Yüksek tutarlı işlem: {basis_text(applied)}",
            }
        out.append(rule)
    return out


async def _apply(
    db: AsyncSession, org: Organization, user: User, value: dict[str, Any], *, outcome: str, reason: str | None
) -> None:
    before = {"amount_cents": threshold_cents(org), "source": (org.materiality_applied or {}).get("source", LEGACY)}
    stored = {
        **value,
        "acknowledged_by": str(user.id),
        "acknowledged_at": datetime.now(UTC).isoformat(),
    }
    org.materiality_applied = stored
    await decisions.record_decision(
        db, org_id=str(org.id), kind=DecisionKind.MATERIALITY, target_type="organization", target_id=str(org.id),
        outcome=outcome, decided_via=DecidedVia.HUMAN, decided_by=str(user.id), reason=reason,
        before=before,
        after={
            "amount_cents": int(value["amount_cents"]), "currency": value.get("currency"),
            "source": value["source"], "basis": value.get("basis"), "basis_text": basis_text(value),
        },
    )


async def acknowledge(db: AsyncSession, org: Organization, user: User, amount_cents: int) -> None:
    """An owner or admin accepts the proposal they were shown. The caller commits.

    The amount must be the one the proposal computes now: if the ledger moved while the person was
    reading, they are asked to look again rather than acknowledging a number they did not see.
    """
    proposal = await propose(db, org)
    if proposal is None:
        raise MaterialityError(422, "Henüz bir eşik önerilecek veri yok: aylık çıkış bandını belirtin ya da veri yükleyin.")
    if int(proposal["amount_cents"]) != int(amount_cents):
        raise MaterialityError(409, "Öneri siz bakarken değişti; yeni öneriyi görüp yeniden onaylayın.")
    await _apply(db, org, user, proposal, outcome="proposal_acknowledged", reason=None)


async def override(
    db: AsyncSession, org: Organization, user: User, amount_cents: int, reason: str | None
) -> None:
    """The owner sets their own amount. The caller commits. In the company's own currency."""
    if amount_cents <= 0:
        raise MaterialityError(422, "Eşik sıfırdan büyük olmalı.")
    proposal = await propose(db, org)
    currency = str((proposal or {}).get("currency") or threshold_currency(org))
    await _apply(
        db, org, user,
        {"amount_cents": int(amount_cents), "currency": currency, "source": OWNER_OVERRIDE, "basis": None},
        outcome="owner_override", reason=reason,
    )
