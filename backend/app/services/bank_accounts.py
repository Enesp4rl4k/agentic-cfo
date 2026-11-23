"""The cash a company's bank statements prove: per account, per currency, never summed across currencies.

Each completed statement whose running balances check out (`app.services.bank_balance`) proves the
balance of ONE account on its last day. Whether two statements are one account is EVIDENCE, never a
default. Absence of evidence that two statements are the same account is not evidence that they differ.

Two statements are the SAME account when:
- they state the same IBAN or account number in their header;
- they are the same statement (identical rows: a file uploaded twice);
- one opens on the balance the other closed on (consecutive statements, `coverage` joins them);
- on a day both show, they end on the same balance, and they never disagree on a common day;
- a person said so (`services/account_identity`, a recorded decision).

They are DIFFERENT accounts when they state different IBANs / account numbers, name different banks or
currencies, or a person said so. Different accounts add up (`known` when each is).

Anything else is "kimliği belirsiz": two proven statements with nothing linking or separating them. They
are never summed. Until a person answers, the opening cash is the single newest balance among them,
basis `assumed`, and `questions` lists the pair for the owner to answer ("Bu ekstreler aynı banka
hesabına mı ait?"). The runway built on it is capped at a warning: the cash is not measured.

The company's opening cash, in its effective base currency, is the sum over its accounts of each
account's newest proven balance. A balance is a fact about one day, so a missing statement between two
statements of one account does not change the account's balance; it is named (`gaps`) and the burn treats
its months as missing (`app.services.company_runway`). Other currencies are listed with their own totals,
never converted. An unproven statement is left out and named with the reason.
"""
from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.currency_totals import DEFAULT_BASE, normalise
from app.models.analysis_job import AnalysisJob, JobStatus
from app.services.bank_balance import aged_basis, basis_of, proof_reason
from app.services.statement_account import kind, mask

UNCERTAIN_NOTE = (
    "{n} ekstrenin aynı hesaba mı ait olduğu bilinmiyor; yalnızca en güncel bakiye ({date}) kullanıldı"
)


def _records(jobs: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(proven statements, statements with balances that are not proven) of the completed jobs."""
    proven: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for job_id, filename, meta in jobs:
        m = meta or {}
        closing = m.get("closing_balance")
        basis = basis_of(m)
        proof = m.get("balance_proof") or {}
        if closing and basis:
            proven.append({
                "job_id": job_id, "filename": filename, "basis": basis,
                "date": str(closing["date"])[:10], "balance_cents": int(closing["balance_cents"]),
                "extent": m.get("statement_extent"), "currency": proof.get("currency"),
                "identity": proof.get("identity"), "sha": proof.get("content_sha"),
                "points": proof.get("points") or {}, "day_sha": proof.get("day_sha") or {}, "reason": proof.get("reason") if basis == "assumed" else None,
            })
        elif proof.get("has_balances") or (closing and not basis):
            excluded.append({"job_id": job_id, "filename": filename, "reason": proof_reason(m)})
    return proven, excluded


def _stated(rec: dict[str, Any]) -> str | None:
    """An account number the file states (IBAN or account number), not just a bank's name."""
    ident = str(rec.get("identity") or "")
    return ident if ident.startswith(("iban:", "acct:")) else None


def _bank(rec: dict[str, Any]) -> str | None:
    ident = str(rec.get("identity") or "")
    return ident if ident.startswith("bank:") else None


def _meets(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    """One statement opens on the balance the other closed on, and starts where it ended."""
    if not a or not b:
        return False
    for first, second in ((a, b), (b, a)):
        if (
            first.get("closing_cents") is not None
            and second.get("opening_cents") == first["closing_cents"]
            and str(second["start"])[:10] >= str(first["end"])[:10]
        ):
            return True
    return False


def same_evidence(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Whether two proven statements are provably one account (or one statement)."""
    if _stated(a) and _stated(a) == _stated(b):
        return True
    if a.get("sha") and a.get("sha") == b.get("sha"):
        return True
    if _meets(a.get("extent"), b.get("extent")):
        return True
    common = set(a.get("points") or {}) & set(b.get("points") or {})
    if not common or any(a["points"][d] != b["points"][d] for d in common):
        return False
    # One coincident day proves nothing (two accounts can both stand at 0,00): two days, or one day on which
    # both files list the same transactions.
    if len(common) >= 2:
        return True
    (day,) = common
    return bool(a.get("day_sha", {}).get(day)) and a["day_sha"].get(day) == b.get("day_sha", {}).get(day)


def different_evidence(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Whether the files themselves say these are different accounts."""
    # Both sides must state the SAME KIND of identifier in their headers and the values must differ: an IBAN
    # against an IBAN, an account number against an account number, a bank name against a bank name. One side
    # stating something and the other nothing (or another kind) is no evidence of a difference.
    sa, sb = _stated(a), _stated(b)
    if sa and sb and kind(sa) == kind(sb) and sa != sb:
        return True
    if _bank(a) and _bank(b) and _bank(a) != _bank(b):
        return True
    ca, cb = normalise(a.get("currency")), normalise(b.get("currency"))
    return bool(ca and cb and ca != cb)


class _Sets:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def join(self, i: int, j: int) -> None:
        self.parent[self.find(i)] = self.find(j)


def _answered(answers: list[dict[str, Any]], group_a: list[dict[str, Any]], group_b: list[dict[str, Any]]) -> str | None:
    """A person's standing answer ("same" | "different") for two groups of statements, if any."""
    ids_a, ids_b = {r["job_id"] for r in group_a}, {r["job_id"] for r in group_b}
    for ans in answers:
        left, right = set(ans["a"]), set(ans["b"])
        if (ids_a & left and ids_b & right) or (ids_a & right and ids_b & left):
            return str(ans["answer"])
    return None


def resolve_accounts(records: list[dict[str, Any]], answers: list[dict[str, Any]]) -> dict[str, Any]:
    """{"groups": [statements of one account], "uncertain": [[group index...]], "separate": {(i, j)}}."""
    sets = _Sets(len(records))
    for i, a in enumerate(records):
        for j in range(i + 1, len(records)):
            if not different_evidence(a, records[j]) and same_evidence(a, records[j]):
                sets.join(i, j)
    groups = _collect(records, sets)
    # A person's answer joins two groups (same account) or separates them (different accounts).
    separate: set[tuple[int, int]] = set()
    changed = True
    while changed:
        changed = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if _answered(answers, groups[i], groups[j]) == "same":
                    index = {r["job_id"]: k for k, r in enumerate(records)}
                    sets.join(index[groups[i][0]["job_id"]], index[groups[j][0]["job_id"]])
                    groups = _collect(records, sets)
                    changed = True
                    break
            if changed:
                break
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            told = _answered(answers, groups[i], groups[j])
            if told == "different" or any(different_evidence(a, b) for a in groups[i] for b in groups[j]):
                separate.add((i, j))
    cluster = _Sets(len(groups))
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            if (i, j) not in separate:
                cluster.join(i, j)
    members: dict[int, list[int]] = {}
    for i in range(len(groups)):
        members.setdefault(cluster.find(i), []).append(i)
    return {"groups": groups, "uncertain": [m for m in members.values() if len(m) > 1], "separate": separate}


def _collect(records: list[dict[str, Any]], sets: _Sets) -> list[list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for i, rec in enumerate(records):
        grouped.setdefault(sets.find(i), []).append(rec)
    return list(grouped.values())


def _gaps(group: list[dict[str, Any]]) -> list[str]:
    """Calendar months wholly between two of an account's statements, covered by neither."""
    spans = sorted(
        (str(r["extent"]["start"])[:10], str(r["extent"]["end"])[:10]) for r in group if r.get("extent")
    )
    out: list[str] = []
    reach = spans[0][1] if spans else ""
    for start, end in spans[1:]:
        if start > reach:
            y, m = int(reach[:4]), int(reach[5:7])
            while True:
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
                first, last = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
                if last.isoformat() >= start:
                    break
                if first.isoformat() > reach:
                    out.append(f"{y:04d}-{m:02d}")
        reach = max(reach, end)
    return out


def _union_extent(group: list[dict[str, Any]], name: str | None) -> dict[str, Any] | None:
    """One account's statements as one extent for the burn's coverage (its gaps are marked separately)."""
    extents = sorted((r["extent"] for r in group if r.get("extent")), key=lambda e: (str(e["start"]), str(e["end"])))
    if not extents:
        return None
    if len(extents) == 1:
        return {**extents[0], "filename": extents[0].get("filename") or name}
    first, last = extents[0], max(extents, key=lambda e: str(e["end"]))
    return {
        "start": first["start"], "end": last["end"], "opening_cents": first.get("opening_cents"),
        "closing_cents": last.get("closing_cents"), "filename": name,
        "start_stated": bool(first.get("start_stated")), "end_stated": bool(last.get("end_stated")),
    }


def _account(group: list[dict[str, Any]], newest: str, limit: int, names: dict[str, str]) -> dict[str, Any]:
    last = max(group, key=lambda r: (r["date"], r["job_id"]))
    ident = next((r["identity"] for r in group if _stated(r)), None)
    behind = (date.fromisoformat(newest) - date.fromisoformat(last["date"])).days
    name = next((names[r["job_id"]] for r in group if r["job_id"] in names), None) or last["filename"]
    # An account whose newest balance is older than the burn window against the other accounts' is only assumed.
    basis, note = aged_basis(last["basis"], last["reason"], behind, last["date"])
    return {
        "name": name, "job_id": last["job_id"], "as_of": last["date"],
        "balance_cents": last["balance_cents"], "currency": last["currency"], "basis": basis,
        "basis_note": note, "identity": ident, "identity_hint": mask(ident), "statements": len(group),
        "behind_days": behind, "lagging": behind > limit, "gaps": _gaps(group),
        "job_ids": [r["job_id"] for r in group], "extent": _union_extent(group, name),
    }


async def _answers(db: AsyncSession, org_id: str) -> list[dict[str, Any]]:
    from app.models.decision import DecisionKind
    from app.services.decisions import list_decisions

    rows, _ = await list_decisions(
        db, org_id, kind=DecisionKind.ACCOUNT_IDENTITY.value, current_only=True, limit=500
    )
    return [
        {"answer": d.outcome, "a": list((d.after or {}).get("a") or []), "b": list((d.after or {}).get("b") or []),
         "name_a": (d.after or {}).get("name_a"), "name_b": (d.after or {}).get("name_b"), "decision_id": d.id}
        for d in rows if d.outcome in ("same", "different") and d.after
    ]


async def proven_balances(db: AsyncSession, org_id: str, currency: str | None = None) -> dict[str, Any]:
    """The company's proven cash: {"opening", "accounts", "excluded", "other_currencies", "currency", "questions"}.

    `currency` is the one the figures are in (default: the organisation's effective base,
    `core/currency_totals.effective_base`). `opening` is None when no account in it is proven; else
    {date (newest balance date), balance_cents, job_id, filename (the newest account's), basis,
    accounts, extents, uncertain, identity_note, gaps}. `questions` are the pairs of statements nothing
    links or separates (see the module docstring), each to be answered by a person.
    """
    if currency is None:
        from app.services.ledger_base import effective_base_of

        currency = (await effective_base_of(db, org_id)).run_currency
    base = normalise(currency) or DEFAULT_BASE
    jobs = (await db.execute(
        select(AnalysisJob.id, AnalysisJob.filename, AnalysisJob.result_metadata).where(
            AnalysisJob.org_id == org_id, AnalysisJob.status == JobStatus.COMPLETED,
        )
    )).all()
    proven, excluded = _records([tuple(j) for j in jobs])
    for r in proven:
        r["currency"] = normalise(r["currency"]) or None
    answers = await _answers(db, org_id)
    names: dict[str, str] = {}
    for ans in answers:
        for key, label in (("a", "name_a"), ("b", "name_b")):
            if ans.get(label):
                names.update({j: str(ans[label]) for j in ans[key]})
    limit = get_settings().radar_balance_stale_after_days
    newest = max((r["date"] for r in proven), default=None)
    accounts: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    notes: list[str] = []
    if newest:
        found = resolve_accounts(proven, answers)
        groups = found["groups"]
        entries = [_account(g, newest, limit, names) for g in groups]
        used = set(range(len(groups)))
        for cluster in found["uncertain"]:
            winner = max(cluster, key=lambda k: (entries[k]["as_of"], entries[k]["job_id"]))
            used -= set(cluster) - {winner}
            entries[winner]["identity_uncertain"] = True
            entries[winner]["basis"] = "assumed"
            notes.append(UNCERTAIN_NOTE.format(n=len(cluster), date=entries[winner]["as_of"]))
            for i in cluster:
                for j in cluster:
                    if i < j and (i, j) not in found["separate"]:
                        questions.append(_question(entries[i], entries[j], groups[i], groups[j]))
        accounts = [entries[i] for i in sorted(used)]
        for a in accounts:
            a["currency_assumed"] = not a["currency"]
            a["currency"] = a["currency"] or base
    mine = [a for a in accounts if a["currency"] == base]
    others: dict[str, dict[str, Any]] = {}
    for a in accounts:
        if a["currency"] != base:
            o = others.setdefault(a["currency"], {"currency": a["currency"], "balance_cents": 0, "as_of": a["as_of"], "accounts": 0})
            o["balance_cents"] += a["balance_cents"]
            o["as_of"] = max(o["as_of"], a["as_of"])
            o["accounts"] += 1
    shown = [{k: v for k, v in a.items() if k not in ("extent", "identity")} for a in accounts]
    opening = None
    if mine:
        top = max(mine, key=lambda a: a["as_of"])
        uncertain = any(a.get("identity_uncertain") for a in mine)
        weak = uncertain or any(a["basis"] == "assumed" for a in mine)
        opening = {
            "date": top["as_of"], "balance_cents": sum(a["balance_cents"] for a in mine),
            "job_id": top["job_id"], "filename": top["name"], "basis": "assumed" if weak else "known",
            "accounts": [{k: v for k, v in a.items() if k not in ("extent", "identity")} for a in mine],
            "extents": [a["extent"] for a in mine if a["extent"]],
            "uncertain": uncertain, "identity_note": "; ".join(notes) or None,
            "gaps": {a["name"]: a["gaps"] for a in mine if a["gaps"]},
        }
    return {
        "currency": base, "opening": opening, "accounts": shown, "excluded": excluded,
        "other_currencies": sorted(others.values(), key=lambda o: o["currency"]), "questions": questions,
    }


def _question(a: dict[str, Any], b: dict[str, Any], ga: list[dict[str, Any]], gb: list[dict[str, Any]]) -> dict[str, Any]:
    def side(e: dict[str, Any]) -> dict[str, Any]:
        return {"name": e["name"], "as_of": e["as_of"], "balance_cents": e["balance_cents"],
                "currency": e["currency"], "identity_hint": e.get("identity_hint")}

    return {
        "question": "Bu ekstreler aynı banka hesabına mı ait?",
        "a": side(a), "b": side(b),
        "job_ids_a": sorted(r["job_id"] for r in ga), "job_ids_b": sorted(r["job_id"] for r in gb),
    }


async def proven_balance(db: AsyncSession, org_id: str, currency: str | None = None) -> dict[str, Any] | None:
    """The company's opening cash in its base currency (see `proven_balances`), or None."""
    opening: dict[str, Any] | None = (await proven_balances(db, org_id, currency))["opening"]
    return opening


async def proven_statements(db: AsyncSession, org_id: str, currency: str | None = None) -> list[dict[str, Any]]:
    """One extent per account in the base currency: the statements behind that balance, for coverage."""
    opening = await proven_balance(db, org_id, currency)
    return list(opening["extents"]) if opening else []
