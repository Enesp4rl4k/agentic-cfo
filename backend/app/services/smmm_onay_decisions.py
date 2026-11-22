"""The decision records of the accountant's approval queue, month close and learned rules.

Kept out of `app/api/smmm_onay.py` (already near the module line ceiling). Every function writes in
the caller's transaction and never commits (`app.services.decisions.record_decision`).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision import DecidedVia, DecisionKind
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.services.decisions import record_decision


async def record_onay(
    db: AsyncSession, user: Any, kayit: SMMMOnayKaydi, outcome: str, *, reason: str | None = None, bulk: bool = False,
) -> None:
    """The accountant's (or, in a company without one, the owner's) answer to one queue entry.

    Call it after the entry's own fields are set: the record's `after` reads them. The queue row keeps the
    answer itself; this record is the company-wide log entry that points at it.
    """
    org_id = kayit.org_id or user.org_id
    if not org_id:
        return
    after: dict[str, Any] = {"durum": str(kayit.durum)}
    if kayit.duzeltilmis_hesap_kodu:
        after["hesap_kodu"] = kayit.duzeltilmis_hesap_kodu
    if bulk:
        after["via"] = "bulk"
    await record_decision(
        db, org_id=str(org_id), kind=DecisionKind.SMMM_ONAY, target_type="smmm_onay_kaydi", target_id=str(kayit.id),
        outcome=outcome, decided_via=DecidedVia.HUMAN, decided_by=str(user.id), reason=reason,
        evidence_refs=[{"type": "analysis_job", "id": str(kayit.job_id)}],
        before={"durum": str(OnayDurumu.BEKLIYOR), "hesap_kodu": kayit.otomatik_hesap_kodu}, after=after,
    )


async def record_month_close(db: AsyncSession, user: Any, kilit: Any) -> None:
    await record_decision(
        db, org_id=str(user.org_id), kind=DecisionKind.MONTH_CLOSE, target_type="accounting_period",
        target_id=kilit.donem, outcome="closed", decided_via=DecidedVia.HUMAN, decided_by=str(user.id),
        evidence_refs=[{"type": "period_lock", "id": str(kilit.id)}], after={"period": kilit.donem},
    )


async def record_rule_revoked(db: AsyncSession, user: Any, kural: Any) -> None:
    await record_decision(
        db, org_id=str(kural.org_id), kind=DecisionKind.AUTOMATION_RULE_CHANGE, target_type="smmm_hesap_kurali",
        target_id=str(kural.id), outcome="revoked", decided_via=DecidedVia.HUMAN, decided_by=str(user.id),
        before={"hesap_kodu": kural.hesap_kodu, "onay_sayisi": kural.onay_sayisi}, after=None,
    )


async def require_authority(db: AsyncSession, user: Any, kayit: SMMMOnayKaydi) -> None:
    """403 unless the user's role may decide this entry (services/approval_authority)."""
    from fastapi import HTTPException

    from app.services.approval_authority import check

    v = await check(db, user, kayit)
    if not v.allowed:
        raise HTTPException(status_code=403, detail=v.reason)
