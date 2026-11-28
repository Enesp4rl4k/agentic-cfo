"""The payload-free audit trail of what left for a language model.

One `llm_call_logs` row per logical call (the cost ledger's own table: no new table): organisation,
purpose (`task_type`: the agent or task), mode, how many placeholders of each type were substituted,
bytes sent. Never a prompt, a reply, a name or a number from the books.

`usage_last_days` is what the owner's screen shows: calls and bytes in the last 30 days, and the calls masked
mode refused (fail closed) with their reason, counts only.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.platform.llm_egress.session import CallTally

ERROR_PREFIX = "egress_refused:"  # == refusals.ERROR_PREFIX (refusals imports this module lazily)

logger = logging.getLogger(__name__)

_TASK_MAX = 48
_ERROR_MAX = 120
_TYPE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,79}")
_REASON_RE = re.compile(r"[a-z0-9_]{1,40}")
_HTTP_RE = re.compile(r"\b(?:error code|status(?: code)?|http)\W{0,3}([1-5][0-9]{2})\b", re.I)


def safe_error(error: str | None) -> str | None:
    """What `llm_call_logs.error` may hold: the exception TYPE and a fixed code, never the message.

    A provider's or a validator's message can quote the prompt or the model's output (a counterparty's name, an
    IBAN). Callers pass `"{type}: {message}"` (model_gateway) or the type alone (embedding_gateway); either way only
    the leading type name survives, plus `:http_<status>` when the message carried an HTTP status, and the masked
    mode's refusals keep their fixed reason (`egress_refused:<reason>`). Anything else becomes `error`."""
    if not error:
        return None
    text = str(error).strip()
    if text.startswith(ERROR_PREFIX):
        reason = text[len(ERROR_PREFIX):]
        return ERROR_PREFIX + reason if _REASON_RE.fullmatch(reason) else ERROR_PREFIX + "other"
    head, _, message = text.partition(":")
    kind = head.strip()
    if not _TYPE_RE.fullmatch(kind):
        return "error"
    status = _HTTP_RE.search(message)
    return (f"{kind}:http_{status.group(1)}" if status else kind)[:_ERROR_MAX]


def persist_call_log(
    *,
    org_id: str | None,
    job_id: str | None,
    task: str,
    model: str,
    res: Any | None,
    ok: bool,
    error: str | None,
    tally: CallTally | None = None,
    data_mode: str | None = None,
) -> None:
    """Best-effort write of one LLMCallLog row. Never raises into the caller.

    `error` is reduced to the exception type and a safe code (`safe_error`): the message is never stored. A row for an
    organisation being erased is refused by the session guard every ORM write passes (`privacy.write_guard`, installed
    by the API and the workers; this platform layer does not import it), and the final sweep removes any other."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    org_id = org_id or (tally.org_id if tally else None)
    stored_error = safe_error(error)

    async def _write() -> None:
        try:
            from app import database
            from app.models.llm_call_log import LLMCallLog
            async with database.session_factory()() as db:
                db.add(
                    LLMCallLog(
                        org_id=org_id,
                        job_id=job_id,
                        task_type=task[:_TASK_MAX],
                        model=model[:64],
                        input_tokens=res.input_tokens if res else 0,
                        output_tokens=res.output_tokens if res else 0,
                        # llm_call_log.cost_usd is NOT NULL (follow-up migration): unpriced rows store 0.0
                        cost_usd=(res.cost_usd or 0.0) if res else 0.0,
                        latency_ms=res.latency_ms if res else 0.0,
                        ok=ok,
                        from_cache=res.from_cache if res else False,
                        attempts=res.attempts if res else 1,
                        error=stored_error,
                        data_mode=(tally.mode if tally else None) or data_mode,
                        bytes_out=tally.bytes_out if tally else 0,
                        replaced=tally.as_record() if tally else None,
                    )
                )
                await db.commit()
        except Exception as exc:  # pragma: no cover - ledger must not break agents
            logger.debug("LLMCallLog persist skipped: %s", exc)

    from app.core.background import spawn

    spawn(_write(), name="llm-call-log")


async def usage_last_days(db: Any, org_id: str, days: int = 30) -> dict[str, Any]:
    """Counts only: calls that sent something, bytes sent, per task and per mode."""
    from app.models.llm_call_log import LLMCallLog

    since = datetime.now(UTC) - timedelta(days=days)
    where = (LLMCallLog.org_id == org_id, LLMCallLog.created_at >= since, LLMCallLog.bytes_out > 0)
    calls, sent = (await db.execute(
        select(func.count(), func.coalesce(func.sum(LLMCallLog.bytes_out), 0)).where(*where)
    )).one()
    by_mode = {
        (mode or "unknown"): int(n)
        for mode, n in (await db.execute(
            select(LLMCallLog.data_mode, func.count()).where(*where).group_by(LLMCallLog.data_mode)
        )).all()
    }
    refused = {
        str(error).removeprefix(ERROR_PREFIX): int(n)
        for error, n in (await db.execute(
            select(LLMCallLog.error, func.count()).where(
                LLMCallLog.org_id == org_id, LLMCallLog.created_at >= since, LLMCallLog.error.like(ERROR_PREFIX + "%")
            ).group_by(LLMCallLog.error)
        )).all()
    }
    return {"days": days, "calls": int(calls), "bytes_out": int(sent), "calls_by_mode": by_mode,
            "refused": refused, "refused_total": sum(refused.values())}
