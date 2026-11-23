"""Versioned acceptance of the privacy notice and the terms of use.

The text of both is the owner's documents (PR #68's drafts, once a lawyer has reviewed them), linked from
`PRIVACY_NOTICE_URL` / `TERMS_URL`; this product holds no legal text. What it holds is evidence: which version a person
accepted and when (`TermsAcceptance`). Changing `PRIVACY_NOTICE_VERSION` or `TERMS_VERSION` makes every person who accepted
an older one "must accept" again; the front end asks, and `accept` records the answer. A stale version is refused (409),
so a person cannot accept text they were not shown.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.privacy_records import TermsAcceptance

DOCUMENTS = ("privacy_notice", "terms")


def current() -> dict[str, dict[str, str]]:
    from app.config import get_settings

    s = get_settings()
    return {"privacy_notice": {"version": s.privacy_notice_version, "url": s.privacy_notice_url},
            "terms": {"version": s.terms_version, "url": s.terms_url}}


async def status(db: AsyncSession, user_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for doc, now in current().items():
        last = (await db.execute(
            select(TermsAcceptance).where(TermsAcceptance.user_id == user_id, TermsAcceptance.document == doc)
            .order_by(TermsAcceptance.accepted_at.desc()).limit(1)
        )).scalar_one_or_none()
        accepted = last is not None and last.version == now["version"]
        out[doc] = {"version": now["version"], "url": now["url"] or None,
                    "accepted_version": last.version if last else None,
                    "accepted_at": (last.accepted_at if last.accepted_at.tzinfo else last.accepted_at.replace(tzinfo=UTC)).isoformat() if last else None,
                    "must_accept": not accepted}
    out["must_accept"] = any(out[d]["must_accept"] for d in DOCUMENTS)
    return out


async def accept(db: AsyncSession, user_id: str, versions: dict[str, str], source: str = "in_app") -> list[str]:
    """Record acceptance of the CURRENT versions named in `versions`. Raises ValueError when one is not current."""
    now = current()
    unknown = [d for d in versions if d not in now]
    if unknown:
        raise ValueError(f"unknown document: {unknown}")
    stale = [d for d, v in versions.items() if v != now[d]["version"]]
    if stale:
        raise ValueError(f"stale version: {stale}")
    recorded = []
    for doc, version in versions.items():
        have = (await db.execute(
            select(TermsAcceptance.id).where(TermsAcceptance.user_id == user_id, TermsAcceptance.document == doc,
                                             TermsAcceptance.version == version).limit(1)
        )).first()
        if have is None:
            db.add(TermsAcceptance(user_id=user_id, document=doc, version=version, source=source,
                                   accepted_at=datetime.now(UTC)))
            recorded.append(doc)
    await db.commit()
    return recorded
