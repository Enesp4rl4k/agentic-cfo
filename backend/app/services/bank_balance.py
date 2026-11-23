"""The balance a bank statement closes on, when the statement proves it.

A statement's running balance ("bakiye") is the one cash figure a company does
not have to reconstruct. It is believed only when it checks out: each row's
balance is the previous one plus that row's movement. That also says which way
the file is ordered, since banks export both oldest-first and newest-first. A
file whose balances do not chain (a merged batch, a missing row, a parser that
read a column wrong) closes on no balance at all: unknown, not guessed.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services.balance_segments import SegmentChain, placed, segment_chain, signed

MIN_STEPS = 3  # reconciling balance steps a text statement needs to be believed outright (parsers/direction)


def _signed(tx: dict[str, Any]) -> int:
    amount = int(tx.get("amount_cents") or 0)
    return amount if tx.get("type") == "income" else -amount


def _chains(rows: list[dict[str, Any]]) -> bool:
    """Oldest first: every balance is the one before it plus this row's money."""
    return all(
        rows[i]["balance_cents"] == rows[i - 1]["balance_cents"] + _signed(rows[i])
        for i in range(1, len(rows))
    )


def chain_verified(counts: dict[str, Any] | None) -> bool:
    """False when the reader itself could not verify the statement's balance chain.

    `counts` is the run's ingest counts (state `ingest_counts`) or the stored ingest summary
    (`result_metadata["ingest"]`): both carry `balance_check` ("verified" | "unverified" | None for a
    file that is not a text statement) and `unaccounted` (rows the readers lost). A chain that checks
    out on the rows we hold is not a proven balance when the reader says it could not verify it, or
    when rows went missing: no balance, no extent, so no runway built on them.
    """
    c = counts or {}
    return c.get("balance_check") != "unverified" and not int(c.get("unaccounted") or 0)


def _chain_order(transactions: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """The rows oldest first, when the statement's balances chain (in file order or reversed)."""
    rows = [t for t in transactions if t.get("balance_cents") is not None and t.get("transaction_date")]
    # One row proves nothing: there is nothing to chain it to.
    if len(rows) < 2 or len(rows) != len(transactions):
        return None
    for ordered in (rows, rows[::-1]):
        if _chains(ordered):
            return ordered
    return None


def _segments(transactions: list[dict[str, Any]]) -> SegmentChain | None:
    """The segment chain of a statement that prints its balance on some rows only, when it reconciles."""
    found = segment_chain(transactions)
    return found if found is not None and found.reason is None and found.discriminating >= 1 else None


def closing_balance(transactions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """{"date", "balance_cents"} the statement ends on, or None if it does not prove one."""
    ordered = _chain_order(transactions)
    if ordered is None:
        found = _segments(transactions)
        if found is None:
            return None
        ordered = found.ordered
    last = ordered[-1]
    return {"date": str(last["transaction_date"])[:10], "balance_cents": int(last["balance_cents"])}


def statement_extent(transactions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The days a balance-proven statement covers and the balances it opens and closes on.

    {"start", "end", "opening_cents", "closing_cents"}: first and last transaction date (the data's
    own proven extent) and the balance before the first row / after the last. None when the
    balances do not chain. Two statements whose closing and opening balances meet are one account's
    consecutive statements (`app.services.coverage`).
    """
    ordered = _chain_order(transactions)
    opening_known = True
    if ordered is None:
        found = _segments(transactions)
        if found is None:
            return None
        ordered = found.ordered
        # A money row before the first printed balance moved the balance that row shows: the opening is unknown.
        opening_known = not found.before_first and (placed(ordered[0]) or not ordered[0].get("amount_cents"))
    dates = sorted(str(t["transaction_date"])[:10] for t in ordered)
    first, last = ordered[0], ordered[-1]
    out: dict[str, Any] = {"start": dates[0], "end": dates[-1], "closing_cents": int(last["balance_cents"])}
    if opening_known:
        out["opening_cents"] = int(first["balance_cents"]) - signed(first)
    return out


def balance_age(as_of: str, anchor: date, stale_after_days: int) -> tuple[int, bool]:
    """(days since the statement closed, whether that is older than the staleness limit).

    The one rule for how old a proven balance may be before it is shown as "last known": the
    cash radar and the forecast's runway both read it here.
    """
    age = max(0, (anchor - date.fromisoformat(str(as_of)[:10])).days)
    return age, age > stale_after_days


def aged_basis(
    basis: str | None, note: str | None, age_days: int, as_of: str | None = None,
) -> tuple[str, str | None]:
    """(basis, note) of a balance that is `age_days` old.

    A runway answers "how long does today's cash last": a balance older than the staleness limit
    (`radar_balance_stale_after_days`, the same limit `balance_age` flags with `stale`) is a fact about a past
    day, so it can only be `assumed`, and says so with its date. Within the limit it keeps its proof's basis.
    Every surface (radar, runway, briefing, alerts) reads this one rule; a summed set of accounts is as old as
    its oldest account (`bank_accounts._account` ages each account against the newest one)."""
    from app.config import get_settings

    if age_days <= get_settings().radar_balance_stale_after_days:
        return basis or "known", note
    when = f" ({as_of})" if as_of else ""
    sentence = f"bakiye {age_days} gün önceki ekstreye ait{when}"
    return "assumed", f"{note}; {sentence}" if note else sentence


def latest_balance(*candidates: dict[str, Any] | None) -> dict[str, Any] | None:
    """The newest of the proven balances given (the first one on a tie), or None."""
    known = [c for c in candidates if c]
    return max(known, key=lambda c: str(c["date"])[:10], default=None)


def _orders_that_chain(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [o for o in (rows, rows[::-1]) if _chains(o)]


def assess(
    transactions: list[dict[str, Any]], counts: dict[str, Any] | None, *, recheck: bool = False,
    identity: str | None = None,
) -> dict[str, Any]:
    """How far a statement's running balances can be believed, and why not when they cannot.

    `state`: "verified" (basis "known"), "weak" (basis "assumed": one or two reconciling steps) or
    "unverified" (basis None; `reason` says why). Never a guess: every row must carry a direction and
    a balance that chains to the next exactly, to the cent, in exactly one file order.

    The reader's own verdict (`counts["balance_check"]`, which needs `MIN_STEPS` steps) stands unless
    `recheck` (a person has since answered the direction or the held rows, so it is read again from
    the rows). A statement with fewer steps than that is weak evidence, not none: it is kept as an
    assumption with its step count stated, and never as known.
    """
    c = counts or {}
    rows = list(transactions)
    # An answer remembered from a person's earlier decision for this statement format settled the
    # direction at ingest (`held_direction.apply_remembered`), after the reader's verdict was written.
    recheck = recheck or any(r.get("direction_remembered") for r in rows)
    out: dict[str, Any] = {
        "state": "unverified", "basis": None, "steps": 0, "reason": None, "identity": identity,
        "has_balances": any(r.get("balance_cents") is not None for r in rows),
        "currency": _currency_of(rows),
    }
    if lost := int(c.get("unaccounted") or 0):
        return {**out, "reason": f"{lost} satır hesaba katılamadı"}
    ordered = _chain_order(rows)
    if ordered is None:
        part = segment_chain(rows)
        if part is None:
            return {**out, "reason": "satır bakiyeleri birbirini tutmuyor" if out["has_balances"] else None}
        return _assess_segments(out, part, c, recheck)
    steps = len(ordered) - 1
    out["steps"] = steps
    days = [str(r["transaction_date"])[:10] for r in ordered]
    if days != sorted(days):
        # Balances that chain only when the file is read against its own dates (a wrong direction can do that).
        return {**out, "reason": "bakiye zinciri satır tarihleriyle çelişiyor"}
    if any(r.get("type") not in ("income", "expense") for r in ordered):
        return {**out, "reason": "bazı satırların yönü (giriş/çıkış) belli değil"}
    out.update(_evidence(ordered))
    if steps >= MIN_STEPS:
        if c.get("balance_check") != "unverified" and not recheck:
            return {**out, "state": "verified", "basis": "known"}
        if recheck:
            return {**out, "state": "verified", "basis": "known"}
        return {**out, "reason": "okuyucu bakiye zincirini doğrulayamadı"}
    # Fewer than three reconciling steps is thin evidence for ANY file type (a CSV's "no verdict" is no proof).
    if not recheck and any(r.get("direction_from_balance") for r in ordered):
        # The balance steps are the only evidence for the directions AND are checked against them: circular.
        return {**out, "reason": "satırların yönü yalnızca bakiyeden çıkarıldı; bağımsız bir kanıt yok"}
    if len(_orders_that_chain(rows)) != 1:
        return {**out, "reason": "bakiye zinciri her iki sıralamada da tutuyor; hangisinin son olduğu belli değil"}
    return {
        **out, "state": "weak", "basis": "assumed",
        "reason": f"yalnızca {steps} bakiye adımıyla doğrulandı",
    }


def _assess_segments(out: dict[str, Any], part: SegmentChain, c: dict[str, Any], recheck: bool) -> dict[str, Any]:
    """The same verdict for a statement that prints its balance on some rows only (`balance_segments`).

    known: every segment from the first to the last printed balance reconciles, in one row order, at least
    two of them tell the sign convention apart, and no row with money lies outside the chain. A file with
    rows outside the chain (before the first or after the last printed balance, a footer between rows) or
    with a single discriminating segment is `assumed`, with the reason; with none, unproven.
    """
    out = {**out, "steps": part.segments, "segments": part.segments, "discriminating": part.discriminating,
           "outside": part.outside}
    if part.reason:
        return {**out, "reason": part.reason}
    out.update(_evidence(part.ordered))
    if c.get("balance_check") == "unverified" and not recheck and part.segments >= MIN_STEPS:
        return {**out, "reason": "okuyucu bakiye zincirini doğrulayamadı"}
    if not recheck and any(r.get("direction_from_balance") for r in part.ordered):
        return {**out, "reason": "satırların yönü yalnızca bakiyeden çıkarıldı; bağımsız bir kanıt yok"}
    if part.discriminating == 0:
        return {**out, "reason": "bakiye aralıklarının toplamı sıfır; satır yönleri bakiyeyle ayırt edilemiyor"}
    if part.outside:
        return {**out, "state": "weak", "basis": "assumed",
                "reason": f"{part.outside} satır bakiye zincirinin dışında kaldı; bakiye bu satırları doğrulamıyor"}
    if part.discriminating >= 2:
        return {**out, "state": "verified", "basis": "known"}
    return {**out, "state": "weak", "basis": "assumed",
            "reason": "yalnızca 1 bakiye aralığı satır yönlerini bakiyeyle ayırt ediyor"}


MAX_POINTS = 400


def _evidence(ordered: list[dict[str, Any]]) -> dict[str, Any]:
    """What lets two statements be recognised as one account: the rows' digest and the balance on each day.

    `content_sha`: the same statement uploaded twice has the same digest. `points`: {day: the balance the
    statement ends that day on} (the newest days when long); two statements of one account agree on every
    day they both show.
    """
    import hashlib

    digest = hashlib.sha256(
        "|".join(sorted(
            f"{str(r['transaction_date'])[:10]};{r.get('amount_cents')};{r.get('type')};{r.get('balance_cents')}"
            for r in ordered
        )).encode()
    ).hexdigest()[:32]
    points: dict[str, int] = {}
    for r in ordered:  # oldest first: the last row of a day is that day's closing balance
        if r.get("balance_cents") is not None:
            points[str(r["transaction_date"])[:10]] = int(r["balance_cents"])
    keep = sorted(points)[-MAX_POINTS:]
    per_day: dict[str, list[str]] = {}
    for r in ordered:
        per_day.setdefault(str(r["transaction_date"])[:10], []).append(f"{r.get('amount_cents')};{r.get('type')};{r.get('balance_cents')}")
    days = {d: hashlib.sha256("|".join(sorted(per_day[d])).encode()).hexdigest()[:16] for d in keep}
    return {"content_sha": digest, "points": {d: points[d] for d in keep}, "day_sha": days}


def _currency_of(rows: list[dict[str, Any]]) -> str | None:
    """The one currency the rows are in, None when they name none or more than one."""
    found = {str(r["currency"]).strip().upper() for r in rows if str(r.get("currency") or "").strip()}
    return next(iter(found)) if len(found) == 1 else None


def basis_of(meta: dict[str, Any] | None) -> str | None:
    """"known" | "assumed" | None: how far a completed job's stored statement balance may be believed.

    A job that recorded its proof (`balance_proof`, written at ingest and again after a person's
    answer) says so; an older job falls back to the reader's own verdict (`chain_verified`).
    """
    m = meta or {}
    proof = m.get("balance_proof")
    if isinstance(proof, dict) and "basis" in proof:
        basis = proof["basis"]
        return basis if isinstance(basis, str) else None
    return "known" if chain_verified(m.get("ingest")) else None


def proof_reason(meta: dict[str, Any] | None) -> str:
    """Why a statement's balance is not proven (or only assumed), in words."""
    m = meta or {}
    proof = m.get("balance_proof")
    if isinstance(proof, dict) and proof.get("reason"):
        return str(proof["reason"])
    lost = int((m.get("ingest") or {}).get("unaccounted") or 0)
    return f"{lost} satır hesaba katılamadı" if lost else "bakiye ile doğrulanamadı"
