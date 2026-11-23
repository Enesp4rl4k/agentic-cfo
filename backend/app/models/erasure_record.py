"""Organisation erasure bookkeeping (KVKK Md. 7 / GDPR Art. 17).

Two tables, neither of which holds personal data once an erasure has run:

* `OrgErasureRequest` — the handshake. An owner/admin *requests*, the owner *confirms*; the erasure is then
  *scheduled* and runs after a cooling-off window (cancellable) — see `app.services.privacy.erasure_flow`.
  The same table carries member-scope requests (one person's account, `scope="member"`). While pending it names the target organisation; on execution
  `target_org_id` and `requested_by_user_id` are nulled and only hashes remain.
* `OrgErasureRecord` — the append-only, hash-chained proof that an erasure
  happened: who (hash), when, which org (hash), how many rows per table.
  `record_hash` covers the content plus the previous record's hash, so a row
  edited or removed afterwards breaks verification (`verify_chain`).

Neither table has an `org_id` column on purpose: erasing an organisation must not
erase the evidence of its erasure. They are listed in
`app.services.org_erasure.BOOKKEEPING_TABLES`.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OrgErasureRequest(Base):
    __tablename__ = "org_erasure_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Nulled when the erasure executes. Not named `org_id` — see module docstring.
    target_org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    org_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)  # anonymise | hard_delete
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    requested_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    requested_by_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_by_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # "org": erase a whole organisation. "member": pseudonymise one person's account (the company stays).
    scope: Mapped[str] = mapped_column(String(10), nullable=False, default="org", server_default="org")
    # Who set it going: "owner" (a member of the organisation), "self" (a member, for their own account) or
    # "operator" (the platform operator on a verified request: `verification_ref` names the ticket, never a person).
    initiated_by: Mapped[str] = mapped_column(String(10), nullable=False, default="owner", server_default="owner")
    verification_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # The person a member-scope request is about; nulled when it executes (the hash remains in `org_hash`).
    target_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Cooling-off: after confirmation nothing is destroyed until this moment, and the owner can cancel before it.
    execute_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Why a scheduled erasure did not run (a fixed code, never free text): e.g. "sole_owner".
    blocked_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Executor bookkeeping: when it claimed the request, why the last attempt failed (a fixed code, never free text),
    # and the counts of what ran after the commit (the Redis sweep; the hash-chained record cannot hold them).
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    post_commit_counts: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Executions and cleanups attempted (capped by the executor, then `blocked: retries_exhausted` + operator alert).
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Written in the SAME transaction that deletes the rows: the files, ids and caches still to clear (UUIDs and
    # storage-relative paths of the erased company only). Cleared when the cleanup is done. See `erasure_cleanup`.
    cleanup_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class OrgErasureRecord(Base):
    __tablename__ = "org_erasure_records"
    __table_args__ = (UniqueConstraint("seq", name="uq_org_erasure_records_seq"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    org_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_by_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_by_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
