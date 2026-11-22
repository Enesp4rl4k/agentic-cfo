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

A SIGN memory (`sign_unconfirmed`: "minus = out, plus = in") is stricter, because generic header words ("Tarih;
Açıklama;Tutar") are shared by unrelated sources: it is applied silently only to the SAME SOURCE, i.e. the same header
signature AND the same account identity the header states (`services/statement_account`). A file with the same
headers but no identity, or another one, is asked again with the earlier answer and its source shown, pre-selected:
one click to confirm, recorded as a decision. Only an explicit "standing" choice (never inferred) lets identity-less
files of that signature through silently. A verifying balance chain always wins over a memory; the override is a
recorded decision and the memory is flagged where remembered answers are listed.
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
from app.services.statement_account import mask

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


def _previous_hint(m: DirectionMapping, mark: dict[str, Any]) -> dict[str, Any]:
    from app.services.statement_account import mask

    return {"answer": m.answer, "columns": m.columns, "account": mask(m.identity or None),
            "same_account": bool(mark.get("identity")) and (m.identity or "") == mark.get("account"),
            "created_at": m.created_at.isoformat() if m.created_at else None}


def _sign_memory(maps: list[DirectionMapping], mark: dict[str, Any]) -> tuple[str | None, DirectionMapping | None]:
    """(answer to apply silently, the earlier answer to show instead) for a sign question."""
    sig = mark["signature"]
    exact = next((m for m in maps if m.signature == sig), None)
    if exact is not None and not mark.get("uniform"):
        if mark.get("identity"):
            return exact.answer, None             # the same source: its account was stated and is part of the signature
        if exact.standing:
            return exact.answer, None             # an explicit, recorded standing rule for identity-less files
    hsig = mark.get("header_signature") or sig
    return None, exact or next((m for m in maps if (m.header_signature or m.signature) == hsig), None)


async def _override(db: AsyncSession, org_id: str, m: DirectionMapping, why: str) -> None:
    """A verifying balance chain won over a memory: recorded, and the memory is flagged where it is listed."""
    m.flagged_at, m.flagged_note = datetime.now(UTC), why[:300]
    await record_decision(
        db, org_id=org_id, kind=DecisionKind.DIRECTION_MAPPING, target_type="direction_mapping",
        target_id=m.id, outcome="overridden", decided_via=DecidedVia.SYSTEM, reason=why,
    )


async def apply_remembered(db: AsyncSession, org_id: str | None, rows: list[dict[str, Any]]) -> int:
    """Rows of a file held for its direction, whose format this organisation already answered: answer them.

    Same organisation, header signature (which includes the bank account when the file names it) and
    reason. Returns how many rows were settled. Never applied blindly:
    - a convention answer is used only when the file names its account; without that it is asked again;
    - an "as read" memory never overrides a balance that contradicts the columns: it is ignored, and
      the override is recorded.
    """
    chains = {c["signature"] for r in rows if (c := r.pop("sign_chain", None))}   # the file booked on a verifying chain
    if not org_id or not (chains or any(r.get("direction_file") for r in rows)):
        return 0
    mappings = await active_mappings(db, org_id)
    known = {(m.signature, m.reason): m for m in mappings}
    sign_maps = [m for m in mappings if m.reason == SIGN_UNCONFIRMED]
    settled = 0
    overridden: dict[str, tuple[DirectionMapping, str]] = {}
    for sig in chains:
        m = known.get((sig, SIGN_UNCONFIRMED))
        if m is not None and m.answer == "sign_inverted":
            overridden[m.id] = (m, "the balance chain verifies minus = out; the remembered 'inverted' answer was not applied")
    for row in rows:
        mark = row.get("direction_file")
        if not mark:
            continue
        sig, reason = mark["signature"], mark["reason"]
        answer: str | None = None
        if reason == SIGN_UNCONFIRMED:
            # Silent only for the same source (see the module doc); otherwise the earlier answer is shown, pre-selected.
            answer, earlier = _sign_memory(sign_maps, mark)
            if earlier is not None:
                hint = _previous_hint(earlier, mark)
                mark["previous"] = hint
                if isinstance(row.get("direction_question"), dict):
                    row["direction_question"]["previous"] = hint
        elif reason in NEEDS_IDENTITY and mark.get("identity"):
            m = known.get((sig, reason))
            answer = m.answer if m else None
        elif reason == BALANCE_CONTRADICTS:
            direct, convention = known.get((sig, BALANCE_CONTRADICTS)), known.get((sig, CONVENTION_UNVERIFIED))
            if convention is not None and convention.answer == "as_read":
                overridden[convention.id] = (convention, "the new file's balance contradicts the remembered reading")
            sign = known.get((sig, SIGN_UNCONFIRMED))
            if sign is not None and not (mark.get("identity") or sign.standing):
                sign = None                         # not evidenced as the same source: it would not have applied anyway
            if sign is not None and sign.answer == "sign_correct":
                overridden[sign.id] = (sign, "the new file's balance contradicts the remembered 'signs are right'")
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
    for mapping, why in sorted(overridden.values(), key=lambda t: t[0].id):
        await _override(db, org_id, mapping, f"{why}; the memory was not applied")
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
            "previous": mark.get("previous"),
            "options": sorted(ANSWERS.get(mark["reason"], frozenset())),
        })
        entry["rows"] += 1
        if row.payload.get("direction_question"):
            entry["question"] = row.payload["direction_question"]
    return list(out.values())


async def answer_file(
    db: AsyncSession, org_id: str, user_id: str, job_id: str, file_key: str, answer: str,
    *, remember: bool = True, note: str | None = None, standing: bool = False,
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
    ) if releasable else ({"resolved": 0, "blocked": [], "already_resolved": 0, "balance_proof": []}, set())
    can_store = (mark["reason"], answer) in REMEMBERABLE and (
        mark["reason"] not in NEEDS_IDENTITY or bool(mark.get("identity"))
    )
    # An identity-less sign answer becomes a standing rule only when the person says so, here, explicitly.
    standing = bool(standing and remember and can_store and mark["reason"] == SIGN_UNCONFIRMED and not mark.get("identity"))
    confirmed_previous = (mark.get("previous") or {}).get("answer") == answer
    await record_decision(
        db, org_id=org_id, kind=DecisionKind.FILE_DIRECTION_ANSWER, target_type="statement_file",
        target_id=file_key, outcome=answer, decided_via=DecidedVia.HUMAN, decided_by=user_id, reason=note,
        evidence_refs=[{"type": "analysis_job", "id": job_id}],
        before={"reason": mark["reason"], "rows": len(rows), "signature": mark["signature"]},
        after={"answer": answer, "released": result["resolved"], "still_waiting_rows": len(waiting),
               "remembered": bool(remember and can_store), "standing": standing,
               "confirmed_previous": confirmed_previous,
               # The statement's balance chain was read again from these answers (a decision of its own).
               "balance_reverifications": [p["decision_id"] for p in result["balance_proof"]]},
    )
    remembered = None
    if remember and can_store:
        asked = next((r.payload["direction_question"] for r in rows if r.payload.get("direction_question")), {})
        remembered = await _remember(db, org_id, user_id, mark, answer, asked, standing)
    await db.commit()
    result["still_waiting"] = await held_rows.pending_count(db, org_id)
    result["ledger"] = await held_rows.append_released(db, jobs)
    result["remembered"] = remembered
    return result


# ── remembered mappings ──────────────────────────────────────────────────────

async def _remember(
    db: AsyncSession, org_id: str, user_id: str, mark: dict[str, Any], answer: str, asked: dict[str, Any],
    standing: bool = False,
) -> str:
    """Store the answer for this format (replacing a previous one), as a decision. No commit."""
    now = datetime.now(UTC)
    for old in await active_mappings(db, org_id):
        if (old.signature, old.reason) == (mark["signature"], mark["reason"]):
            old.revoked_at, old.revoked_by = now, user_id
    names = ", ".join(str(c.get("name")) for c in asked.get("columns", []))
    mapping = DirectionMapping(
        org_id=org_id, signature=mark["signature"], reason=mark["reason"], answer=answer,
        columns=names[:500], created_by=user_id, header_signature=mark.get("header_signature"),
        identity=str(mark.get("account") or ""), standing=standing,
    )
    db.add(mapping)
    await db.flush()
    await record_decision(
        db, org_id=org_id, kind=DecisionKind.DIRECTION_MAPPING, target_type="direction_mapping",
        target_id=mapping.id, outcome="remembered", decided_via=DecidedVia.HUMAN, decided_by=user_id,
        before=None, after={"signature": mark["signature"], "reason": mark["reason"], "answer": answer, "standing": standing,
                            "identity": bool(mark.get("identity"))},
    )
    return mapping.id


def describe_mapping(m: DirectionMapping) -> dict[str, Any]:
    return {
        "id": m.id, "signature": m.signature, "reason": m.reason, "answer": m.answer,
        "columns": m.columns, "created_at": m.created_at.isoformat() if m.created_at else None,
        "account": mask(m.identity or None), "standing": bool(m.standing),
        "flagged_at": m.flagged_at.isoformat() if m.flagged_at else None, "flagged_note": m.flagged_note,
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
