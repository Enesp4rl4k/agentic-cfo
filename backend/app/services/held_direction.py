"""One question for a statement file whose direction cannot be placed, and the answer remembered.

`app.parsers.direction` holds a file whole when it cannot say which way the money went:

  no_signal             nothing in the file says                          only_income | only_expense | mixed
  balance_contradicts   the balance shows the opposite of the columns     as_read | balance | mixed
  convention_unverified a Borç/Alacak (B/A, D/C, Debit/Credit) reading    as_read | inverted | mixed
                        that no balance column can verify
  balance_inconclusive  the balance reconciles only part of the rows      as_read | mixed
  sign_unconfirmed      one signed amount column, no verifying balance    sign_correct | sign_inverted | mixed
                        chain: "minus = out, plus = in?" (mixed, all-positive and all-negative files alike)

Asking per row would be an approval pile; the file is asked once. The answer applies to every row in
one transaction, each row's change a decision, the file's answer a decision of its own. `mixed` leaves
the rows held one by one (the honest answer for a statement the system cannot split: correct them, or
upload a file with a direction or balance column). `only_income` / `only_expense` are the user stating
the file contains one kind only.

An answer that fixes a CONVENTION or a balance contradiction can be remembered, for the same
organisation, header signature and bank/account identity (`DirectionMapping`); creating or revoking one
needs a decider or the accountant, because it changes how every later statement of that format is
booked. A memory is applied only when it can still be checked: a file whose identity is unknown is asked
again, and a memory that says "as read" never overrides a balance that contradicts the columns (the
override is recorded).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision import DecidedVia, DecisionKind
from app.models.direction_mapping import DirectionMapping
from app.models.held_transaction import HeldTransaction
from app.parsers.direction import (
    BALANCE_CONTRADICTS,
    BALANCE_INCONCLUSIVE,
    CONVENTION_UNVERIFIED,
    NO_SIGNAL,
    SIGN_UNCONFIRMED,
)
from app.services import held_rows
from app.services.decisions import record_decision
from app.services.ingest.hold import row_reasons

MIXED = "mixed"
ANSWERS: dict[str, frozenset[str]] = {
    NO_SIGNAL: frozenset({"only_income", "only_expense", MIXED}),
    BALANCE_CONTRADICTS: frozenset({"as_read", "balance", MIXED}),
    CONVENTION_UNVERIFIED: frozenset({"as_read", "inverted", MIXED}),
    BALANCE_INCONCLUSIVE: frozenset({"as_read", MIXED}),
    SIGN_UNCONFIRMED: frozenset({"sign_correct", "sign_inverted", MIXED}),
}
_FIXED = {"only_income": "income", "only_expense": "expense"}
# (reason, answer) pairs worth remembering: a statement format's convention, not a statement about one file.
REMEMBERABLE = frozenset({(CONVENTION_UNVERIFIED, "as_read"), (CONVENTION_UNVERIFIED, "inverted"),
                          (BALANCE_CONTRADICTS, "balance"), (SIGN_UNCONFIRMED, "sign_correct"),
                          (SIGN_UNCONFIRMED, "sign_inverted")})
# These need to know WHICH account the file is from, or the memory could never be checked. The sign of an
# export is a fact about the export's format (organisation + header signature), not about the account.
NEEDS_IDENTITY = frozenset({CONVENTION_UNVERIFIED})


class AnswerError(ValueError):
    """The answer is not one of the file's options."""


def _type_for(payload: dict[str, Any], answer: str) -> str | None:
    mark = payload.get("direction_file") or {}
    if answer in _FIXED:
        return _FIXED[answer]
    if answer in ("as_read", "sign_correct"):
        return mark.get("read")
    return mark.get("balance") if answer in ("balance", "inverted", "sign_inverted") else None


def _individual(payload: dict[str, Any]) -> dict[str, Any]:
    """The row leaves the file question and waits on its own (nothing could be said for it)."""
    out = {k: v for k, v in payload.items() if k not in ("direction_file", "direction_question")}
    out["hold_reasons"] = row_reasons(out)
    return out


def apply_to_rows(rows: list[dict[str, Any]], answer: str) -> None:
    """Apply a file's answer to extracted rows that are not stored yet (a remembered mapping). In place."""
    for row in rows:
        if not row.get("direction_file"):
            continue
        direction = _type_for(row, answer)
        if direction is None:
            continue
        row["type"] = direction
        row.pop("direction_file", None)
        row.pop("direction_question", None)
        if row.get("category") is None:
            from app.services.ingest.rows import _yukleyenin_kategorisi

            row["category"] = _yukleyenin_kategorisi(
                str(row.get("category_hint") or ""), str(row.get("description") or ""), direction
            )


async def active_mappings(db: AsyncSession, org_id: str) -> list[DirectionMapping]:
    return list((await db.execute(
        select(DirectionMapping).where(DirectionMapping.org_id == org_id, DirectionMapping.revoked_at.is_(None))
        .order_by(DirectionMapping.created_at)
    )).scalars().all())


async def apply_remembered(db: AsyncSession, org_id: str | None, rows: list[dict[str, Any]]) -> int:
    """Rows of a file held for its direction, whose format this organisation already answered: answer them.

    Same organisation, header signature (which includes the bank account when the file names it) and
    reason. Returns how many rows were settled. Never applied blindly:
    - a convention answer is used only when the file names its account; without that it is asked again;
    - an "as read" memory never overrides a balance that contradicts the columns: it is ignored, and
      the override is recorded.
    """
    if not org_id or not any(r.get("direction_file") for r in rows):
        return 0
    known = {(m.signature, m.reason): m for m in await active_mappings(db, org_id)}
    settled = 0
    overridden: set[str] = set()
    for row in rows:
        mark = row.get("direction_file")
        if not mark:
            continue
        sig, reason = mark["signature"], mark["reason"]
        answer: str | None = None
        if reason == SIGN_UNCONFIRMED:
            # Applied only to a file in which BOTH signs occur: a memory about what minus means can be contradicted
            # (by a balance chain: it is held then) only by such a file. A one-signed file is asked.
            m = known.get((sig, reason))
            answer = m.answer if m and not mark.get("uniform") else None
        elif reason in NEEDS_IDENTITY and mark.get("identity"):
            m = known.get((sig, reason))
            answer = m.answer if m else None
        elif reason == BALANCE_CONTRADICTS:
            direct, convention = known.get((sig, BALANCE_CONTRADICTS)), known.get((sig, CONVENTION_UNVERIFIED))
            if convention is not None and convention.answer == "as_read":
                overridden.add(convention.id)       # this file's balance contradicts what was remembered
            sign = known.get((sig, SIGN_UNCONFIRMED))
            if sign is not None and sign.answer == "sign_correct":
                overridden.add(sign.id)             # "the signs are right" does not outrank a balance that says otherwise
            if direct is None and sign is not None and sign.answer == "sign_inverted":
                answer = "balance"                  # the balance shows the opposite of the signs: what was remembered
            if direct is not None:
                answer = "balance"
            elif convention is not None and convention.answer == "inverted":
                answer = "balance"                  # the bank-view reading is what this balance shows
        if answer and (reason, answer) in REMEMBERABLE:
            apply_to_rows([row], answer)
            row["direction_remembered"] = answer
            settled += 1
    for mapping_id in sorted(overridden):
        await record_decision(
            db, org_id=org_id, kind=DecisionKind.DIRECTION_MAPPING, target_type="direction_mapping",
            target_id=mapping_id, outcome="overridden", decided_via=DecidedVia.SYSTEM,
            reason="the new file's balance contradicts the remembered reading; the memory was not applied",
        )
    if overridden:
        await db.commit()
    return settled


# ── the file question ────────────────────────────────────────────────────────

async def _file_rows(db: AsyncSession, org_id: str, job_id: str, file_key: str) -> list[HeldTransaction]:
    rows = await held_rows.pending_rows(db, org_id, job_id=job_id)
    return [r for r in rows if (r.payload.get("direction_file") or {}).get("key") == file_key]


async def list_questions(db: AsyncSession, org_id: str) -> list[dict[str, Any]]:
    """One entry per waiting file: what was detected, a few sample rows, the options."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in await held_rows.pending_rows(db, org_id):
        mark = row.payload.get("direction_file")
        if not mark:
            continue
        entry = out.setdefault((row.job_id, mark["key"]), {
            "job_id": row.job_id, "file_key": mark["key"], "reason": mark["reason"],
            "signature": mark["signature"], "identity": bool(mark.get("identity")), "rows": 0, "question": None,
            "options": sorted(ANSWERS.get(mark["reason"], frozenset())),
        })
        entry["rows"] += 1
        if row.payload.get("direction_question"):
            entry["question"] = row.payload["direction_question"]
    return list(out.values())


async def answer_file(
    db: AsyncSession, org_id: str, user_id: str, job_id: str, file_key: str, answer: str,
    *, remember: bool = True, note: str | None = None,
) -> dict[str, Any]:
    """Apply one answer to every row of a waiting file. One transaction; commits."""
    rows = await _file_rows(db, org_id, job_id, file_key)
    if not rows:
        raise held_rows.UnknownRows(file_key)
    mark = rows[0].payload["direction_file"]
    if answer not in ANSWERS.get(mark["reason"], frozenset()):
        raise AnswerError(f"{answer} is not an option for this file")
    releasable: list[str] = []
    fixes: dict[str, dict[str, Any]] = {}
    waiting: dict[str, dict[str, Any]] = {}
    for row in rows:
        direction = _type_for(row.payload, answer)
        if direction is None:
            waiting[row.id] = _individual(row.payload)
            continue
        fix = {"type": direction}
        after = held_rows.apply_corrections(row.payload, fix)
        if row_reasons(after):
            waiting[row.id] = after
        else:
            releasable.append(row.id)
            fixes[row.id] = fix
    await held_rows.update_waiting(db, org_id, user_id, waiting, f"file direction: {answer}")
    result, jobs = await held_rows.resolve_uncommitted(
        db, org_id, user_id=user_id, release=True, ids=releasable, corrections=fixes,
        note=note or f"file direction: {answer}",
    ) if releasable else ({"resolved": 0, "blocked": [], "already_resolved": 0}, set())
    can_store = (mark["reason"], answer) in REMEMBERABLE and (
        mark["reason"] not in NEEDS_IDENTITY or bool(mark.get("identity"))
    )
    await record_decision(
        db, org_id=org_id, kind=DecisionKind.FILE_DIRECTION_ANSWER, target_type="statement_file",
        target_id=file_key, outcome=answer, decided_via=DecidedVia.HUMAN, decided_by=user_id, reason=note,
        evidence_refs=[{"type": "analysis_job", "id": job_id}],
        before={"reason": mark["reason"], "rows": len(rows), "signature": mark["signature"]},
        after={"answer": answer, "released": result["resolved"], "still_waiting_rows": len(waiting),
               "remembered": bool(remember and can_store)},
    )
    remembered = None
    if remember and can_store:
        asked = next((r.payload["direction_question"] for r in rows if r.payload.get("direction_question")), {})
        remembered = await _remember(db, org_id, user_id, mark, answer, asked)
    await db.commit()
    result["still_waiting"] = await held_rows.pending_count(db, org_id)
    result["ledger"] = await held_rows.append_released(db, jobs)
    result["remembered"] = remembered
    return result


# ── remembered mappings ──────────────────────────────────────────────────────

async def _remember(
    db: AsyncSession, org_id: str, user_id: str, mark: dict[str, Any], answer: str, asked: dict[str, Any],
) -> str:
    """Store the answer for this format (replacing a previous one), as a decision. No commit."""
    now = datetime.now(UTC)
    for old in await active_mappings(db, org_id):
        if (old.signature, old.reason) == (mark["signature"], mark["reason"]):
            old.revoked_at, old.revoked_by = now, user_id
    names = ", ".join(str(c.get("name")) for c in asked.get("columns", []))
    mapping = DirectionMapping(
        org_id=org_id, signature=mark["signature"], reason=mark["reason"], answer=answer,
        columns=names[:500], created_by=user_id,
    )
    db.add(mapping)
    await db.flush()
    await record_decision(
        db, org_id=org_id, kind=DecisionKind.DIRECTION_MAPPING, target_type="direction_mapping",
        target_id=mapping.id, outcome="remembered", decided_via=DecidedVia.HUMAN, decided_by=user_id,
        before=None, after={"signature": mark["signature"], "reason": mark["reason"], "answer": answer},
    )
    return mapping.id


def describe_mapping(m: DirectionMapping) -> dict[str, Any]:
    return {
        "id": m.id, "signature": m.signature, "reason": m.reason, "answer": m.answer,
        "columns": m.columns, "created_at": m.created_at.isoformat() if m.created_at else None,
    }


async def revoke_mapping(db: AsyncSession, org_id: str, user_id: str, mapping_id: str) -> None:
    """The next upload of that format is asked again. The mapping row stays, marked revoked. Commits."""
    mapping = await db.get(DirectionMapping, mapping_id)
    if mapping is None or mapping.org_id != org_id:
        raise held_rows.UnknownRows(mapping_id)
    if mapping.revoked_at is None:
        mapping.revoked_at, mapping.revoked_by = datetime.now(UTC), user_id
        await record_decision(
            db, org_id=org_id, kind=DecisionKind.DIRECTION_MAPPING, target_type="direction_mapping",
            target_id=mapping.id, outcome="revoked", decided_via=DecidedVia.HUMAN, decided_by=user_id,
            before={"signature": mapping.signature, "reason": mapping.reason, "answer": mapping.answer},
        )
    await db.commit()
