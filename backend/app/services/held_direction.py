"""One question for a statement file whose direction cannot be placed, and the answer remembered.

`app.parsers.direction` holds a file whole when nothing in it says which way the money went
(`no_signal`) or when its running balance contradicts what its columns said
(`balance_contradicts`). Asking per row would be an approval pile; the file is asked once:

  no_signal            all_income | all_expense | mixed (rows stay held, one by one)
  balance_contradicts  as_read (the columns are right) | balance (the balance is right) | mixed

The answer applies to every row of the file in one transaction, each row's change recorded as a
decision, and the file's answer is a decision of its own. It is remembered for the same
organisation, header signature and reason (`DirectionMapping`) so that bank's format is not asked
again; the mapping is listed and revocable, and its use is applied to the rows exactly as a
person's answer would be (`apply_remembered`).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision import DecidedVia, DecisionKind
from app.models.direction_mapping import DirectionMapping
from app.models.held_transaction import HeldTransaction
from app.parsers.direction import BALANCE_CONTRADICTS, NO_SIGNAL
from app.services import held_rows
from app.services.decisions import record_decision
from app.services.ingest.hold import row_reasons

MIXED = "mixed"
ANSWERS: dict[str, frozenset[str]] = {
    NO_SIGNAL: frozenset({"all_income", "all_expense", MIXED}),
    BALANCE_CONTRADICTS: frozenset({"as_read", "balance", MIXED}),
}
_FIXED = {"all_income": "income", "all_expense": "expense"}


class AnswerError(ValueError):
    """The answer is not one of the file's options."""


def _type_for(payload: dict[str, Any], answer: str) -> str | None:
    mark = payload.get("direction_file") or {}
    if answer in _FIXED:
        return _FIXED[answer]
    return mark.get("read") if answer == "as_read" else mark.get("balance") if answer == "balance" else None


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

    Returns how many rows were settled. Same organisation, same header signature, same reason.
    """
    if not org_id or not any(r.get("direction_file") for r in rows):
        return 0
    known = {(m.signature, m.reason): m.answer for m in await active_mappings(db, org_id)}
    settled = 0
    for row in rows:
        mark = row.get("direction_file")
        if not mark:
            continue
        answer = known.get((mark["signature"], mark["reason"]))
        if answer and answer in ANSWERS.get(mark["reason"], frozenset()):
            apply_to_rows([row], answer)
            row["direction_remembered"] = answer
            settled += 1
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
            "signature": mark["signature"], "rows": 0, "question": None,
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
    await record_decision(
        db, org_id=org_id, kind=DecisionKind.FILE_DIRECTION_ANSWER, target_type="statement_file",
        target_id=file_key, outcome=answer, decided_via=DecidedVia.HUMAN, decided_by=user_id, reason=note,
        evidence_refs=[{"type": "analysis_job", "id": job_id}],
        before={"reason": mark["reason"], "rows": len(rows), "signature": mark["signature"]},
        after={"answer": answer, "released": result["resolved"], "still_waiting_rows": len(waiting),
               "remembered": bool(remember and answer != MIXED)},
    )
    remembered = None
    if remember and answer != MIXED:
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
