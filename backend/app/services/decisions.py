"""Write and read the decision record (`decisions`, Plan v11 C4 / A1.6).

`record_decision` writes in the CALLER's transaction: it adds the row and flushes,
and never commits. The decision and the change it records therefore commit or roll
back together; it must not be called from a background task. There is no update or
delete function here, on purpose; the model refuses them too (`AppendOnlyError`).

Not to be confused with `app.services.decision_log`, which tracks management
recommendations and their measured outcomes (`DecisionLog`).
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision import DecidedVia, Decision, DecisionKind

MAX_SNAPSHOT_BYTES = 4000
MAX_EVIDENCE_REFS = 50
_MONEY_SUFFIXES = ("_cents", "_kurus")


class DecisionError(ValueError):
    """The decision is inconsistent; nothing was written."""


def _check_money(value: Any, path: str) -> None:
    """Amounts in a snapshot are integer cents (CLAUDE.md): never a float, never a string."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            where = f"{path}.{key}"
            if str(key).endswith(_MONEY_SUFFIXES) and item is not None and (
                isinstance(item, bool) or not isinstance(item, int)
            ):
                raise DecisionError(f"{where}: money must be integer cents, got {item!r}")
            _check_money(item, where)
    elif isinstance(value, list | tuple):
        for i, item in enumerate(value):
            _check_money(item, f"{path}[{i}]")


def _snapshot(value: Mapping[str, Any] | None, name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    _check_money(value, name)
    try:
        size = len(json.dumps(value, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise DecisionError(f"{name} is not JSON-serialisable") from exc
    if size > MAX_SNAPSHOT_BYTES:
        raise DecisionError(f"{name} is {size} bytes; snapshots are small (max {MAX_SNAPSHOT_BYTES})")
    return dict(value)


def _evidence(refs: Iterable[Mapping[str, str]] | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for ref in refs or ():
        if set(ref) != {"type", "id"} or not all(isinstance(v, str) and v for v in ref.values()):
            raise DecisionError(f"evidence_refs entries are {{type, id}} strings, got {dict(ref)!r}")
        out.append({"type": ref["type"], "id": ref["id"]})
    if len(out) > MAX_EVIDENCE_REFS:
        raise DecisionError(f"at most {MAX_EVIDENCE_REFS} evidence refs")
    return out


def _validate_actor(decided_via: str, decided_by: str | None, rule_id: str | None) -> None:
    if decided_via == DecidedVia.HUMAN:
        if not decided_by:
            raise DecisionError("a human decision needs decided_by")
        if rule_id:
            raise DecisionError("a human decision has no rule_id")
    elif decided_via == DecidedVia.RULE:
        if not rule_id:
            raise DecisionError("a rule decision needs rule_id")
        if decided_by:
            raise DecisionError("a rule decision has no decided_by; the rule is the decider")
    else:
        if decided_by or rule_id:
            raise DecisionError("a system decision has neither decided_by nor rule_id")


async def record_decision(
    db: AsyncSession,
    *,
    org_id: str,
    kind: DecisionKind | str,
    target_type: str,
    target_id: str,
    outcome: str,
    decided_via: DecidedVia | str,
    decided_by: str | None = None,
    rule_id: str | None = None,
    decided_at: datetime | None = None,
    reason: str | None = None,
    evidence_refs: Iterable[Mapping[str, str]] | None = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    supersedes_id: str | None = None,
) -> Decision:
    """Add one decision to the caller's transaction and flush it. Never commits.

    Raises `DecisionError` for an unknown kind, an inconsistent actor, a naive
    timestamp, a malformed snapshot or evidence list, or a `supersedes_id` that
    is not an unreplaced decision of the same organisation and target.
    """
    try:
        kind_value = DecisionKind(kind).value
        via = DecidedVia(decided_via).value
    except ValueError as exc:
        raise DecisionError(str(exc)) from exc
    if not org_id or not target_type or not target_id or not outcome:
        raise DecisionError("org_id, target_type, target_id and outcome are required")
    _validate_actor(via, decided_by, rule_id)
    if decided_at is not None and decided_at.tzinfo is None:
        raise DecisionError("decided_at must be timezone-aware")
    row = Decision(
        org_id=org_id, kind=kind_value, target_type=target_type, target_id=target_id,
        outcome=outcome, decided_by=decided_by, decided_via=via, rule_id=rule_id,
        reason=reason, evidence_refs=_evidence(evidence_refs),
        before=_snapshot(before, "before"), after=_snapshot(after, "after"),
        supersedes_id=supersedes_id,
    )
    if decided_at is not None:
        row.decided_at = decided_at

    if supersedes_id is not None:
        prior = await db.get(Decision, supersedes_id)
        if prior is None or prior.org_id != org_id:
            raise DecisionError("supersedes_id is not a decision of this organisation")
        if (prior.target_type, prior.target_id) != (target_type, target_id):
            raise DecisionError("a decision can only supersede one about the same target")
        taken = (await db.execute(
            select(Decision.id).where(Decision.supersedes_id == supersedes_id)
        )).first()
        if taken is not None:
            raise DecisionError("that decision is already superseded")

    db.add(row)
    await db.flush()
    return row


def _filters(
    org_id: str, kind: str | None, target_type: str | None, target_id: str | None
) -> list[Any]:
    clauses: list[Any] = [Decision.org_id == org_id]
    if kind is not None:
        clauses.append(Decision.kind == kind)
    if target_type is not None:
        clauses.append(Decision.target_type == target_type)
    if target_id is not None:
        clauses.append(Decision.target_id == target_id)
    return clauses


async def list_decisions(
    db: AsyncSession, org_id: str, *, kind: str | None = None, target_type: str | None = None,
    target_id: str | None = None, current_only: bool = False, limit: int = 50, offset: int = 0,
) -> tuple[list[Decision], int]:
    """One organisation's decisions, newest first, and the total before paging.

    `current_only` hides decisions that a later one supersedes, leaving the
    standing decision of each chain.
    """
    clauses = _filters(org_id, kind, target_type, target_id)
    if current_only:
        replaced = select(Decision.supersedes_id).where(
            Decision.org_id == org_id, Decision.supersedes_id.is_not(None)
        )
        clauses.append(Decision.id.not_in(replaced))
    total = (await db.execute(select(func.count()).select_from(Decision).where(*clauses))).scalar_one()
    rows = (await db.execute(
        select(Decision).where(*clauses)
        .order_by(Decision.decided_at.desc(), Decision.id.desc()).limit(limit).offset(offset)
    )).scalars().all()
    return list(rows), int(total)


async def decision_chain(db: AsyncSession, org_id: str, decision_id: str) -> list[Decision]:
    """The whole supersede chain `decision_id` belongs to, newest first. Empty if not found."""
    start = await db.get(Decision, decision_id)
    if start is None or start.org_id != org_id:
        return []
    chain = [start]
    seen = {start.id}
    cur = start
    while cur.supersedes_id and cur.supersedes_id not in seen:  # earlier decisions
        prior = await db.get(Decision, cur.supersedes_id)
        if prior is None or prior.org_id != org_id:
            break
        chain.insert(0, prior)
        seen.add(prior.id)
        cur = prior
    cur = start
    while True:  # later decisions
        nxt = (await db.execute(
            select(Decision).where(Decision.org_id == org_id, Decision.supersedes_id == cur.id)
        )).scalar_one_or_none()
        if nxt is None or nxt.id in seen:
            break
        chain.append(nxt)
        seen.add(nxt.id)
        cur = nxt
    return list(reversed(chain))


async def superseded_ids(db: AsyncSession, org_id: str, ids: Sequence[str]) -> dict[str, str]:
    """For each of `ids` that a later decision replaced: id -> the replacing decision's id."""
    if not ids:
        return {}
    rows = (await db.execute(
        select(Decision.supersedes_id, Decision.id)
        .where(Decision.org_id == org_id, Decision.supersedes_id.in_(list(ids)))
    )).all()
    return {r[0]: r[1] for r in rows}


__all__ = [
    "MAX_SNAPSHOT_BYTES", "DecidedVia", "Decision", "DecisionError", "DecisionKind",
    "decision_chain", "list_decisions", "record_decision", "superseded_ids",
]
