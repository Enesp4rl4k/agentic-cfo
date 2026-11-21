"""The Monday briefing by e-mail, through the outbox (plan v10 S1.3, plan v11 A0.5).

Who receives it: the company's owner, admins and CFO (from memberships, and from
`users.org_id` for organisations older than memberships). One message per recipient
per briefing; the outbox key makes a second dispatch a no-op.

Owner decision K10, recommended default applied: when the company has an accountant
(an `smmm` membership), the message is held until the accountant releases it. The
screen does not wait; only the e-mail does.

A held e-mail is frozen text, and the release can come days later. So the facts the body
was built from are recorded when it is held (a system decision whose `after` is the facts),
and at release they are read again: unchanged, the held text goes out; changed, nothing is
sent until the releaser has seen what changed and confirmed the refreshed text. Every
release is a decision record written in the same transaction as the release.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.decision import DecidedVia, Decision, DecisionKind
from app.models.organization import OrgMembership
from app.models.outbox_message import OutboxMessage
from app.models.user import User, UserRole
from app.services import decisions, outbox
from app.services.cash_radar import _fmt, compute_cash_radar
from app.services.monday_briefing import MondayBriefing, _tr_date, assemble_monday_briefing

SOURCE = "monday_briefing"
RECIPIENT_ROLES = (UserRole.OWNER.value, UserRole.ADMIN.value, UserRole.CFO.value)
HELD_FOR_ACCOUNTANT = "awaiting_accountant_release"


async def recipients(db: AsyncSession, org_id: str) -> list[str]:
    """E-mail addresses of the people the briefing is for, each once, in a stable order."""
    member_ids = select(OrgMembership.user_id).where(
        OrgMembership.org_id == org_id, OrgMembership.role.in_(RECIPIENT_ROLES)
    )
    users = (
        await db.execute(
            select(User.email).where(
                User.is_active.is_(True),
                or_(
                    User.id.in_(member_ids),
                    (User.org_id == org_id) & User.role.in_(RECIPIENT_ROLES),
                ),
            )
        )
    ).scalars().all()
    return sorted(set(users))


async def has_accountant(db: AsyncSession, org_id: str) -> bool:
    found = await db.execute(
        select(OrgMembership.id)
        .where(OrgMembership.org_id == org_id, OrgMembership.role == UserRole.SMMM.value)
        .limit(1)
    )
    return found.scalar_one_or_none() is not None


def _message(briefing: MondayBriefing, data_date: date) -> tuple[str, str]:
    subject = f"Pazartesi bülteni — {briefing.week_start}"
    link = f"{get_settings().frontend_url.rstrip('/')}/bulten"
    body = "\n\n".join(
        [
            f"Hafta: {briefing.week_start} – {briefing.week_end}",
            briefing.sentence_radar,
            briefing.sentence_obligation,
            briefing.sentence_action,
            f"{_tr_date(data_date.isoformat())} tarihli verilere göre hazırlanmıştır.",
            f"Ayrıntılar ve yanıt: {link}",
        ]
    )
    return subject, body


class BriefingReleaseBlocked(Exception):
    """The held e-mail cannot be refreshed (the company no longer has data for it)."""


def _sha(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


async def collect_facts(
    db: AsyncSession, org_id: str, briefing: MondayBriefing, *, anchor_date: date, data_date: date
) -> dict[str, Any]:
    """What the e-mail body was built from: the opening cash, the week's totals and items,
    and the headline answer. Small enough to store in a decision (item ids are a digest)."""
    radar = await compute_cash_radar(db, org_id, anchor_date=anchor_date)
    week = radar.weeks[0] if radar.weeks else None
    receivable_ids = sorted(str(r["id"]) for r in (week.receivables if week else []))
    payable_ids = sorted(str(p["id"]) for p in (week.payables if week else []))
    return {
        "anchor_date": anchor_date.isoformat(),
        "data_date": data_date.isoformat(),
        "currency": radar.currency,
        "opening_cash_cents": briefing.starting_cash_cents,
        "opening_as_of": briefing.balance_as_of,
        "week_start": briefing.week_start,
        "week_end": briefing.week_end,
        "inflow_cents": week.inflow_cents if week else 0,
        "outflow_cents": week.outflow_cents if week else 0,
        "net_change_cents": briefing.net_change_cents,
        "end_balance_cents": briefing.end_balance_cents,
        "receivable_count": len(receivable_ids),
        "payable_count": len(payable_ids),
        "items_sha": _sha([receivable_ids, payable_ids]),
        "headline": briefing.full_text[:600],
        "headline_sha": _sha(briefing.full_text),
    }


# The fields that make two sets of facts "the same"; the dates of reading are not among them.
_COMPARED = (
    "opening_cash_cents", "opening_as_of", "week_start", "week_end", "inflow_cents",
    "outflow_cents", "net_change_cents", "end_balance_cents", "items_sha", "headline_sha",
)
_LABELS = {
    "opening_cash_cents": "Açılış bakiyesi", "opening_as_of": "Bakiye tarihi",
    "week_start": "Hafta başı", "week_end": "Hafta sonu",
    "inflow_cents": "Haftalık giriş", "outflow_cents": "Haftalık çıkış",
    "net_change_cents": "Net değişim", "end_balance_cents": "Hafta sonu bakiyesi",
    "items_sha": "Haftanın kalemleri", "headline_sha": "Özet cümleler",
}


def facts_fingerprint(facts: dict[str, Any]) -> str:
    return _sha({k: facts.get(k) for k in _COMPARED})


def _show(field: str, facts: dict[str, Any]) -> str:
    if field.endswith("_cents"):
        value = facts.get(field)
        # Facts stored before the currency was kept have none: shown as unknown, not as lira.
        return "bilinmiyor" if value is None else _fmt(int(value), facts.get("currency"))
    if field == "items_sha":
        return f"{facts.get('receivable_count', 0)} alacak, {facts.get('payable_count', 0)} ödeme kalemi"
    if field == "headline_sha":
        return str(facts.get("headline") or "")
    value = facts.get(field)
    return "yok" if value is None else str(value)


def diff_facts(old: dict[str, Any] | None, new: dict[str, Any]) -> list[dict[str, str]]:
    """What changed, old -> new, in words the releaser reads."""
    if old is None:
        return [{
            "field": "unknown", "label": "Bekletilen e-postanın rakamları kayıtlı değil",
            "old": "bilinmiyor", "new": "güncel bülten",
        }]
    return [
        {"field": f, "label": _LABELS[f], "old": _show(f, old), "new": _show(f, new)}
        for f in _COMPARED
        if old.get(f) != new.get(f)
    ]


async def _held_decision(db: AsyncSession, org_id: str, briefing_id: str) -> Decision | None:
    rows, _ = await decisions.list_decisions(
        db, org_id, kind=DecisionKind.BRIEFING_RELEASE.value, target_type="briefing",
        target_id=briefing_id, limit=20,
    )
    return next((d for d in rows if d.outcome == "held"), None)


async def _record_hold(
    db: AsyncSession, org_id: str, briefing: MondayBriefing, facts: dict[str, Any]
) -> None:
    """The system held the e-mail: one system decision per briefing, carrying the facts."""
    if await _held_decision(db, org_id, briefing.briefing_id) is not None:
        return
    await decisions.record_decision(
        db, org_id=org_id, kind=DecisionKind.BRIEFING_RELEASE, target_type="briefing",
        target_id=briefing.briefing_id, outcome="held", decided_via=DecidedVia.SYSTEM,
        reason=HELD_FOR_ACCOUNTANT,
        evidence_refs=[
            {"type": "briefing", "id": briefing.briefing_id},
            {"type": "fingerprint", "id": facts_fingerprint(facts)},
        ],
        after=facts,
    )


async def enqueue_briefing_emails(
    db: AsyncSession, org_id: str, briefing: MondayBriefing, *, anchor_date: date
) -> list[OutboxMessage]:
    """Write one outbox row per recipient. A briefing with nothing to say writes none.

    `anchor_date` is the date the briefing was assembled for; a release reads the facts
    again for the same week."""
    if not briefing.has_data:
        return []
    subject, body = _message(briefing, anchor_date)
    held = HELD_FOR_ACCOUNTANT if await has_accountant(db, org_id) else None
    rows = []
    for address in await recipients(db, org_id):
        rows.append(
            await outbox.enqueue(
                db,
                key=f"{SOURCE}:{org_id}:{briefing.briefing_id}:{address}",
                org_id=org_id,
                channel="email",
                recipient=address,
                subject=subject,
                body=body,
                source=SOURCE,
                source_ref=briefing.briefing_id,
                held_reason=held,
            )
        )
    if held and rows:
        facts = await collect_facts(
            db, org_id, briefing, anchor_date=anchor_date, data_date=anchor_date
        )
        await _record_hold(db, org_id, briefing, facts)
    return rows


async def release_briefing(
    db: AsyncSession,
    *,
    org_id: str,
    briefing_id: str,
    released_by: str | None,
    confirm_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Release the held e-mails of one briefing, or say what changed since they were written.

    `released_by` is the person's user id; None is the system (a hold that expired, a
    resend), recorded as `system` and never as a person. Unchanged facts release the held
    text. Changed facts release nothing until `confirm_fingerprint` equals the fingerprint
    of the refreshed facts the releaser was shown; then the refreshed text is sent, and the
    system can never confirm. The decision is written in the caller's transaction."""
    held = await outbox.held_rows(db, org_id=org_id, source=SOURCE, source_ref=briefing_id)
    if not held:
        return {"released": 0, "refreshed": False, "needs_confirmation": False, "changes": []}
    hold = await _held_decision(db, org_id, briefing_id)
    old = dict(hold.after) if hold is not None and hold.after else None
    today = datetime.now(UTC).date()
    anchor = date.fromisoformat(old["anchor_date"]) if old else today
    current = await assemble_monday_briefing(db, org_id, anchor_date=anchor)
    new = await collect_facts(db, org_id, current, anchor_date=anchor, data_date=today)
    new_fp = facts_fingerprint(new)
    via = DecidedVia.HUMAN if released_by else DecidedVia.SYSTEM
    evidence = [{"type": "briefing", "id": briefing_id}, {"type": "fingerprint", "id": new_fp}]

    if old is not None and facts_fingerprint(old) == new_fp:
        released = await outbox.release(db, org_id=org_id, source=SOURCE, source_ref=briefing_id)
        outcome, before, after, refreshed = "released", None, old, False
    else:
        if not current.has_data:
            raise BriefingReleaseBlocked("Bülten için artık veri yok; e-posta gönderilmedi.")
        if released_by is None or confirm_fingerprint != new_fp:
            return {
                "released": 0, "refreshed": False, "needs_confirmation": True,
                "changes": diff_facts(old, new), "fingerprint": new_fp,
            }
        subject, body = _message(current, today)
        released = await outbox.release(
            db, org_id=org_id, source=SOURCE, source_ref=briefing_id, refreshed=(subject, body)
        )
        outcome, before, after, refreshed = "released_refreshed", old, new, True
    await decisions.record_decision(
        db, org_id=org_id, kind=DecisionKind.BRIEFING_RELEASE, target_type="briefing",
        target_id=briefing_id, outcome=outcome, decided_via=via, decided_by=released_by,
        evidence_refs=evidence, before=before, after=after,
        supersedes_id=hold.id if hold is not None else None,
    )
    return {"released": released, "refreshed": refreshed, "needs_confirmation": False, "changes": []}


async def deliveries(db: AsyncSession, org_id: str, briefing_id: str) -> list[dict[str, object]]:
    """What happened to this briefing's e-mails, for the screen."""
    rows = (
        await db.execute(
            select(OutboxMessage)
            .where(
                OutboxMessage.org_id == org_id,
                OutboxMessage.source == SOURCE,
                OutboxMessage.source_ref == briefing_id,
            )
            .order_by(OutboxMessage.recipient)
        )
    ).scalars().all()
    return [
        {
            "recipient": r.recipient,
            "status": r.status,
            "reason": r.last_error,
            "attempts": r.attempts,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        }
        for r in rows
    ]
