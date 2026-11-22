"""Erase ONE person while the company stays: pseudonymous retention of "who decided".

A member leaves, or asks for their data to go (KVKK Art. 7, 11/e). The company's books and its decision
record must keep saying that SOMEONE approved a payment, so the person's row is not deleted: it becomes a
tombstone under a stable pseudonym (`member-<12 hex>`) that carries no e-mail, name, password, key, SSO id,
membership or sign-in. Every record that names the person by id (`decisions.decided_by`, `open_item_matches`,
approvals, `analysis_jobs.user_id`) therefore still points at one consistent pseudonym and at nothing else.

What is removed or overwritten
------------------------------
* the user row: e-mail, name, password hash, API key, SSO ids, active organisation, sign-in (token version bumped);
* memberships in every organisation, reset / verification tokens, invitations to or by the address, pilot invites;
* the accountant profile and client list, when the person has one;
* their address in every alert-recipient list; outbox messages addressed to it lose recipient, subject and body
  (the row, key and status stay: the delivery metadata is the company's record that a message existed);
* audit-log rows keep action, resource, role and the pseudonymous id; e-mail, IP address, browser string, request
  body and reason are cleared;
* free text the person typed into feedback;
* their chat history (Redis and the in-process fallback).

What is kept, and the legal question (Q4 in `docs/kvkk/avukata-sorular.md`): the decision record, approvals and
ledger rows keep the pseudonymous id. Whether a stable pseudonym is enough, or the company's audit duty and the
person's erasure right need a different cut, is for a lawyer; `decisions.reason` is free text the person typed and is
kept by default (conservative: the audit trail stays whole).

A person who is the only owner of a company cannot be erased: the company would be left without anyone who may act
(`blockers`). They transfer ownership or erase the company (`org_erasure`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email_address import normalize_email
from app.database import Base
from app.models.erasure_record import OrgErasureRecord
from app.services import org_erasure
from app.services.org_erasure import hash_id

TOMBSTONE_DOMAIN = "erased.invalid"
MEMBER_MODE = "member_anonymise"


def pseudonym(user_id: str) -> str:
    """The stable pseudonym of a user id: the same id always yields the same handle, and it reveals nothing."""
    return "member-" + hash_id("user", user_id)[:12]


def is_tombstone(email: str | None) -> bool:
    return bool(email) and str(email).endswith("@" + TOMBSTONE_DOMAIN)


@dataclass
class MemberErasureResult:
    pseudonym: str
    already_erased: bool = False
    counts: dict[str, Any] = field(default_factory=dict)
    organisations: list[str] = field(default_factory=list)


async def blockers(db: AsyncSession, user_id: str) -> list[str]:
    """Organisations where this person is the only owner: erasing them would orphan the company."""
    m = Base.metadata.tables["org_memberships"]
    mine = (await db.execute(
        select(m.c.org_id).where(m.c.user_id == user_id, m.c.role == "owner")
    )).scalars().all()
    stuck = []
    for org_id in mine:
        others = (await db.execute(
            select(func.count()).select_from(m).where(m.c.org_id == org_id, m.c.role == "owner", m.c.user_id != user_id)
        )).scalar_one()
        if not others:
            stuck.append(org_id)
    return stuck


async def erase_member(
    db: AsyncSession, user_id: str, *, requested_by_hash: str | None = None, confirmed_by_hash: str | None = None,
) -> MemberErasureResult:
    """Pseudonymise one person in one transaction and commit. Idempotent; refuses a sole owner (ValueError)."""
    t = Base.metadata.tables
    users = t["users"]
    row = (await db.execute(select(users.c.id, users.c.email).where(users.c.id == user_id))).one_or_none()
    handle = pseudonym(user_id)
    if row is None or is_tombstone(row.email):
        return MemberErasureResult(pseudonym=handle, already_erased=True)
    if await blockers(db, user_id):
        raise ValueError("sole_owner")
    try:
        counts, orgs = await _erase(db, user_id, str(row.email), handle)
        await _write_record(db, hash_id("member", user_id), counts, requested_by_hash, confirmed_by_hash)
        await _record_decisions(db, orgs, handle)
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    from app.services.privacy.ephemeral import erase_user_ephemeral

    counts["_ephemeral"] = await erase_user_ephemeral(user_id)  # derived data: after the commit, never blocks it
    return MemberErasureResult(pseudonym=handle, counts=counts, organisations=orgs)


async def _erase(db: AsyncSession, user_id: str, email: str, handle: str) -> tuple[dict[str, Any], list[str]]:
    from app.services.auth import hash_password

    t = Base.metadata.tables
    counts: dict[str, Any] = {}
    norm = normalize_email(email)
    tomb = f"{handle}@{TOMBSTONE_DOMAIN}"

    def tally(name: str, kind: str, result: Any) -> None:
        if result.rowcount:
            counts.setdefault(name, {})[kind] = counts.get(name, {}).get(kind, 0) + result.rowcount

    members = t["org_memberships"]
    orgs = [str(o) for o in (await db.execute(select(members.c.org_id).where(members.c.user_id == user_id))).scalars()]
    users_org = (await db.execute(select(t["users"].c.org_id).where(t["users"].c.id == user_id))).scalar_one_or_none()
    if users_org and str(users_org) not in orgs:
        orgs.append(str(users_org))

    from sqlalchemy import delete

    for name, col in (("org_memberships", "user_id"), ("password_reset_tokens", "user_id"),
                      ("email_verification_tokens", "user_id")):
        tally(name, "deleted", await db.execute(delete(t[name]).where(t[name].c[col] == user_id)))
    invites = t["org_invites"]
    tally("org_invites", "deleted", await db.execute(delete(invites).where(func.lower(invites.c.email) == norm)))
    pilot = t["pilot_invites"]
    tally("pilot_invites", "deleted", await db.execute(
        delete(pilot).where((func.lower(pilot.c.email) == norm) | (pilot.c.used_by_user_id == user_id))))
    muh, client = t["smmm_muhasebeci"], t["smmm_musteri_kayit"]
    muh_ids = (await db.execute(select(muh.c.id).where(muh.c.user_id == user_id))).scalars().all()
    if muh_ids:
        tally("smmm_musteri_kayit", "deleted", await db.execute(delete(client).where(client.c.muhasebeci_id.in_(muh_ids))))
        tally("smmm_muhasebeci", "deleted", await db.execute(delete(muh).where(muh.c.id.in_(muh_ids))))

    await _drop_from_recipient_lists(db, norm, tomb, counts)

    mail = t["outbox_messages"]
    tally("outbox_messages", "anonymised", await db.execute(
        update(mail).where(func.lower(mail.c.recipient) == norm)
        .values(recipient=tomb, subject=org_erasure.ERASED, body=org_erasure.ERASED, last_error=None)))

    audit = t["audit_logs"]
    tally("audit_logs", "anonymised", await db.execute(
        update(audit).where(audit.c.user_id == user_id)
        .values(user_email=tomb, ip_address=None, user_agent=None, request_body=None, reason=None)))
    fb = t["user_feedback"]
    tally("user_feedback", "anonymised", await db.execute(
        update(fb).where(fb.c.user_id == user_id)
        .values(comment=None, biggest_benefit=None, biggest_gap=None, page_context=None)))

    u = t["users"]
    import secrets

    tally("users", "anonymised", await db.execute(
        update(u).where(u.c.id == user_id).values(
            email=tomb, full_name=handle, hashed_password=hash_password(secrets.token_urlsafe(32)),
            api_key=None, sso_provider=None, sso_id=None, org_id=None, is_active=False,
            token_version=u.c.token_version + 1, password_changed_at=None, last_login=None, last_login_at=None,
            email_verified_at=None)))
    return counts, orgs


async def _drop_from_recipient_lists(db: AsyncSession, norm: str, tomb: str, counts: dict[str, Any]) -> None:
    prefs = Base.metadata.tables["alert_preferences"]
    rows = (await db.execute(select(prefs.c.id, prefs.c.email_recipients, prefs.c.whatsapp_number)
                             .where(prefs.c.email_recipients.is_not(None)))).all()
    for r in rows:
        try:
            listed = json.loads(r.email_recipients)
        except (TypeError, ValueError):
            continue
        if not isinstance(listed, list):
            continue
        kept = [e for e in listed if normalize_email(str(e)) != norm]
        if len(kept) != len(listed):
            await db.execute(update(prefs).where(prefs.c.id == r.id).values(email_recipients=json.dumps(kept)))
            counts.setdefault("alert_preferences", {})["anonymised"] = counts.get("alert_preferences", {}).get("anonymised", 0) + 1


async def _write_record(
    db: AsyncSession, subject_hash: str, counts: dict[str, Any], requested_by_hash: str | None,
    confirmed_by_hash: str | None,
) -> OrgErasureRecord:
    last = (await db.execute(select(OrgErasureRecord).order_by(OrgErasureRecord.seq.desc()).limit(1))).scalar_one_or_none()
    rec = OrgErasureRecord(
        seq=(last.seq + 1) if last else 1, org_hash=subject_hash, mode=MEMBER_MODE,
        requested_by_hash=requested_by_hash, confirmed_by_hash=confirmed_by_hash,
        executed_at=datetime.now(UTC).replace(microsecond=0), counts=counts,
        prev_hash=last.record_hash if last else org_erasure.GENESIS_HASH, record_hash="",
    )
    rec.record_hash = org_erasure._chain_hash(rec.prev_hash, org_erasure.record_payload(rec))
    db.add(rec)
    await db.flush()
    return rec


async def _record_decisions(db: AsyncSession, orgs: list[str], handle: str) -> None:
    """One member-change decision per company the person belonged to: the pseudonym, never a name."""
    from app.models.decision import DecidedVia, DecisionKind
    from app.services.decisions import record_decision

    for org_id in orgs:
        await record_decision(
            db, org_id=org_id, kind=DecisionKind.MEMBER_CHANGE, target_type="member", target_id=handle,
            outcome="member_erased", decided_via=DecidedVia.SYSTEM, after={"pseudonym": handle},
        )
