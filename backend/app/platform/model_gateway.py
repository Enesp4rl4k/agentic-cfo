"""
Model Gateway — the single egress point for every LLM call in the backend.

Nothing else may instantiate ``ChatOpenAI`` (or any other model client).  All
agents, skills, routers and services call :func:`complete`, which owns the
cross-cutting concerns that were previously copy-pasted (or missing) at ~40 call
sites:

  * model selection      — task→tier table in ``model_catalog``; tier→id from settings
  * structured output    — ``schema=`` returns a validated pydantic instance
  * retry + backoff      — transient errors are retried up to LLM_CALL_MAX_ATTEMPTS
  * timeout              — every call is bounded by LLM_CALL_TIMEOUT_SECONDS
  * cost ledger          — one ``LLMCallLog`` row per call + in-process aggregate
  * tracing              — an OpenTelemetry span per call
  * graceful degradation — a placeholder API key raises :class:`LLMUnavailable`
                           so callers fall back to their deterministic templates

Design rule (tests/test_platform/test_llm_egress_single_chokepoint.py): ChatOpenAI is imported here only.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from pydantic import BaseModel

from app.core.llm_key import (
    is_placeholder_key,  # one shared predicate (re-exported: chat.py imports it from here)
)
from app.platform import llm_egress as egress
from app.platform.llm_egress.audit import failure_code as _failure_code
from app.platform.llm_egress.audit import persist_call_log as _persist_call_log
from app.platform.model_catalog import (
    ModelConfig,
    Tier,
    config_for_model,
    config_for_tier,
    cost_usd,
    http_status,
    is_provider_rejection,
    llm_config_report,
    select_model,
)
from app.platform.model_ledger import Ledger as _Ledger
from app.platform.policies import (
    LLM_CACHE_MAX_ENTRIES,
    LLM_CACHE_TTL_SECONDS,
    LLM_CALL_BACKOFF_BASE_SECONDS,
    LLM_CALL_MAX_ATTEMPTS,
    LLM_CALL_TIMEOUT_SECONDS,
    LLM_ORG_BUDGET_CHECK_TTL_SECONDS,
    LLM_ORG_BUDGET_SOFT_WARN_RATIO,
    LLM_ORG_MONTHLY_BUDGET_USD_DEFAULT,
)

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "Sen C-Suite düzeyinde bir Türk iş danışmanısın. "
    "Kısa, net ve eyleme dönüştürülebilir cevaplar ver. Sayısal verileri vurgula."
)


class LLMUnavailable(RuntimeError):
    """No usable API key is configured — callers should use a deterministic fallback."""


class LLMDisabled(LLMUnavailable):
    """The effective data mode is `off`: no data is sent to a language model; use the deterministic path."""


class LLMEgressRefused(LLMDisabled):
    """`masked` mode failed closed (company or its names unknown for this call): nothing was sent."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class LLMBudgetExceeded(RuntimeError):
    """The org has spent past its monthly LLM budget. Callers should fall back."""

    def __init__(self, org_id: str, spend_usd: float, budget_usd: float) -> None:
        super().__init__(
            f"org {org_id} LLM spend ${spend_usd:.2f} >= budget ${budget_usd:.2f}"
        )
        self.org_id = org_id
        self.spend_usd = spend_usd
        self.budget_usd = budget_usd




# ── Result type ──────────────────────────────────────────────────────────────

@dataclass
class GatewayResult:
    text: str
    model: str
    task: str
    parsed: Any | None = None          # pydantic instance when schema= was given
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = 0.0       # None = model price unknown (never 0)
    latency_ms: float = 0.0
    from_cache: bool = False
    attempts: int = 1


# ── In-process cost ledger (survives without a DB): app/platform/model_ledger.py ──

_LEDGER = _Ledger()
_CACHE: OrderedDict[str, tuple[GatewayResult, float]] = OrderedDict()


def ledger_snapshot() -> dict[str, Any]:
    """In-process aggregate — cheap, always available, resets on process restart."""
    return _LEDGER.snapshot()


def reset_ledger() -> None:
    _LEDGER.reset()
    _CACHE.clear()
    _ORG_SPEND_CACHE.clear()


# ── Per-org budget guard ───────────────────────────────────────────────────

_ORG_SPEND_CACHE: dict[str, tuple[float, float]] = {}  # org_id -> (spend_usd, expiry)


def _org_budget_usd(org_id: str) -> float:
    """Monthly USD budget for an org. Per-org overrides can be wired here later."""
    return LLM_ORG_MONTHLY_BUDGET_USD_DEFAULT


async def _org_month_spend_usd(org_id: str) -> float:
    """
    LLM spend for `org_id` so far this calendar month, from LLMCallLog.
    Cached briefly; falls back to the in-process ledger when the DB is unusable.
    """
    hit = _ORG_SPEND_CACHE.get(org_id)
    if hit and hit[1] > time.time():
        return hit[0]

    spend = float((_LEDGER.by_org.get(org_id) or {}).get("cost_usd", 0.0))
    try:
        from datetime import datetime

        from sqlalchemy import func, select

        from app.database import session_factory
        from app.models.llm_call_log import LLMCallLog

        month_start = datetime.now(UTC).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        async with session_factory()() as db:
            total = await db.scalar(
                select(func.coalesce(func.sum(LLMCallLog.cost_usd), 0.0)).where(
                    LLMCallLog.org_id == org_id,
                    LLMCallLog.created_at >= month_start,
                )
            )
        if total is not None:
            spend = float(total)
    except Exception as exc:  # pragma: no cover - budget check must never crash a call
        logger.debug("org spend lookup fell back to in-process ledger: %s", exc)

    _ORG_SPEND_CACHE[org_id] = (spend, time.time() + LLM_ORG_BUDGET_CHECK_TTL_SECONDS)
    return spend


async def _enforce_org_budget(org_id: str | None) -> None:
    if not org_id:
        return
    budget = _org_budget_usd(org_id)
    if budget <= 0:
        return
    spend = await _org_month_spend_usd(org_id)
    if spend >= budget:
        raise LLMBudgetExceeded(org_id, spend, budget)
    if spend >= budget * LLM_ORG_BUDGET_SOFT_WARN_RATIO:
        logger.warning(
            "LLM budget: org=%s at $%.2f / $%.2f (%.0f%%)",
            org_id, spend, budget, 100 * spend / budget,
        )


# ── Model selection ─────────────────────────────────────────────────────────

def _resolve_model(task: str, prompt_len: int, model_override: str | None) -> ModelConfig:
    """``model_override`` is a tier name ("cheap"/"strong") or a literal model id."""
    if model_override:
        if model_override in (Tier.CHEAP, Tier.STRONG):
            return config_for_tier(model_override)
        return config_for_model(model_override)
    try:
        return select_model(task, prompt_len)
    except Exception:  # deterministic task / unknown → the strong tier
        return config_for_tier(Tier.STRONG)


def _cache_key(model: str, system_prompt: str, prompt: str, schema_name: str) -> str:
    raw = f"{model}\x00{schema_name}\x00{system_prompt}\x00{prompt}"
    return hashlib.sha256(raw.encode()).hexdigest()


def llm_config_status() -> dict[str, Any]:
    """Configured base_url/model pair for ops: no network call, never the key."""
    from app.config import get_settings
    return llm_config_report(api_key_configured=not is_placeholder_key(get_settings().openai_api_key))


# ── Raw provider call (the ONLY place ChatOpenAI is built) ───────────────────

History = list[dict[str, str]]  # [{"role": "user"|"assistant", "content": "..."}]


def _first(*values: Any) -> Any:  # first value that is not None
    return next(v for v in values if v is not None)
def _build_client(cfg: ModelConfig, temperature: float | None, max_tokens: int | None) -> Any:
    """Construct the model client. The ONLY ChatOpenAI() call in the backend."""
    from app.config import get_settings

    settings = get_settings()
    if is_placeholder_key(settings.openai_api_key):
        raise LLMUnavailable("openai_api_key is a placeholder")

    from langchain_openai import ChatOpenAI
    # ChatOpenAI >= 0.3 renames max_tokens to max_completion_tokens on the wire; extra_body keeps max_tokens.
    return ChatOpenAI(
        model=cfg.model_id,
        temperature=_first(temperature, cfg.temperature, settings.llm_temperature),
        extra_body={"max_tokens": _first(max_tokens, cfg.max_tokens, settings.llm_max_tokens)},
        api_key=settings.openai_api_key,  # type: ignore[arg-type]  # langchain coerces str→SecretStr
        base_url=getattr(settings, "llm_base_url", None) or None,
    )


def _build_messages(system_prompt: str, prompt: str, history: History | None) -> list[Any]:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    msgs: list[Any] = [SystemMessage(content=system_prompt)]
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content", "")
        if role == "user":
            msgs.append(HumanMessage(content=content))
        elif role == "assistant":
            msgs.append(AIMessage(content=content))
    msgs.append(HumanMessage(content=prompt))
    return msgs


async def _open_egress(org_id: str | None, task: str | None) -> egress.EgressSession:
    try:
        return await egress.open_session(org_id, task=task)
    except egress.EgressRefused as exc:
        _note_skip("refused")
        raise LLMEgressRefused(str(exc), exc.reason) from exc
    except egress.PolicyOff as exc:
        _note_skip("off")
        raise LLMDisabled(str(exc)) from exc


def _note_skip(kind: str) -> None:
    skipped = egress.skipped_steps.get()
    if skipped is not None:
        skipped.append(kind)


def _texts(messages: list[Any]) -> list[str]:
    return [str(getattr(m, "content", "")) for m in messages]


async def _raw_chat(
    cfg: ModelConfig,
    system_prompt: str,
    prompt: str,
    *,
    schema: type[BaseModel] | None,
    temperature: float | None,
    max_tokens: int | None,
    history: History | None = None,
    json_reply: str | None = None,
) -> tuple[str, Any | None, int, int]:
    """One send. THE choke point: every payload is masked here (or refused, in `off` mode) before it is built.

    json_reply ("strict" | "narrative"): the reply is JSON; it is parsed BEFORE restoring and the parsed
    string values are restored (strict: an unknown placeholder makes that value None)."""
    llm = _build_client(cfg, temperature, max_tokens)  # raises LLMUnavailable without a key
    outer = egress.current_tally()
    tally = outer or egress.CallTally(task="llm_router")  # a direct caller (llm_router) has no `complete` around it
    sess = await _open_egress(tally.org_id, tally.task)
    ok = False
    failure: str | None = None
    try:
        out_system, out_prompt, out_history = sess.outbound(system_prompt, prompt, history)
        messages = _build_messages(out_system, out_prompt, out_history)
        sess.sent(_texts(messages), tally)

        if schema is not None:
            # the wire format has always been a tool call (langchain-openai >= 0.3 would default to json_schema)
            structured = llm.with_structured_output(schema, method="function_calling")
            parsed = sess.restore_obj(await structured.ainvoke(messages))
            text = parsed.to_text() if hasattr(parsed, "to_text") else str(parsed)
            # structured-output responses rarely expose usage; estimate from text
            in_tok = int(len((system_prompt + prompt).split()) * 1.3)
            out_tok = int(len(text.split()) * 1.3)
            ok = True
            return text, parsed, in_tok, out_tok

        response = await llm.ainvoke(messages)
        parsed_json: Any | None = None
        if json_reply is not None:
            text, parsed_json = egress.restore_json_reply(sess, response.content or "", strict=json_reply == "strict")
            if parsed_json is not egress.NOT_JSON and sess.unresolved:
                tally.flags.add("unresolved_placeholder")
        else:
            text = sess.restore(response.content or "")
        usage = getattr(response, "usage_metadata", None) or {}
        in_tok = int(usage.get("input_tokens", len((system_prompt + prompt).split()) * 1.3))
        out_tok = int(usage.get("output_tokens", len(text.split()) * 1.3))
        ok = True
        return text, parsed_json, in_tok, out_tok
    except BaseException as exc:
        failure = _failure_code(exc, is_provider_rejection(exc))
        raise
    finally:
        if outer is None:
            _persist_call_log(org_id=sess.org_id, job_id=None, task=tally.task or "llm_router", model=cfg.model_id,
                              res=None, ok=ok, error=failure, tally=tally)


# ── Public entry point ─────────────────────────────────────────────────────

@egress.tallied
async def complete(
    *,
    task: str,
    prompt: str,
    system_prompt: str | None = None,
    schema: type[BaseModel] | None = None,
    history: History | None = None,
    org_id: str | None = None,
    job_id: str | None = None,
    model_override: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    use_cache: bool = False,
    timeout_s: float = LLM_CALL_TIMEOUT_SECONDS,
    max_attempts: int = LLM_CALL_MAX_ATTEMPTS,
    json_reply: str | None = None,
) -> GatewayResult:
    """
    Run one LLM completion: routing, retry, timeout, caching, cost log, tracing.

    Raises:
        LLMUnavailable: placeholder API key, or the provider refused the model
            (4xx, not retried). Callers should use their deterministic fallback.
    """
    system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
    cfg = _resolve_model(task, len(prompt), model_override)
    schema_name = schema.__name__ if schema is not None else ""

    if use_cache:
        if (await egress.effective_mode(org_id)).mode == egress.DataMode.OFF:
            _note_skip("off")
            raise LLMDisabled("Yapay zekâya veri gönderimi kapalı (LLM_DATA_MODE=off): önbellekteki yanıt da verilmez")
        key = _cache_key(cfg.model_id, system_prompt, prompt, schema_name + (json_reply or ""))
        hit = _CACHE.get(key)
        if hit and hit[1] > time.time():
            cached = hit[0]
            _CACHE.move_to_end(key)
            return GatewayResult(**{**cached.__dict__, "from_cache": True})

    await _enforce_org_budget(org_id)  # raises LLMBudgetExceeded

    from app.services.telemetry import tracer

    start = time.time()
    attempts = 0

    with tracer.start_as_current_span("llm.complete") as span:
        try:
            span.set_attribute("llm.task", task)
            span.set_attribute("llm.model", cfg.model_id)
            if org_id:
                span.set_attribute("llm.org_id", org_id)
        except Exception:
            pass

        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            try:
                text, parsed, in_tok, out_tok = await asyncio.wait_for(
                    _raw_chat(
                        cfg,
                        system_prompt,
                        prompt,
                        schema=schema,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        history=history,
                        **({"json_reply": json_reply} if json_reply else {}),
                    ),
                    timeout=timeout_s,
                )
                break
            except LLMUnavailable:
                # No API key configured — not a real call. Don't touch the ledger
                # or spawn a DB write; the caller falls back to a template.
                raise
            except (TimeoutError, Exception) as exc:
                rejected = is_provider_rejection(exc)
                if rejected:
                    logger.error(
                        "LLM provider rejected the request (HTTP %s): base_url host=%s "
                        "model=%s task=%s. Check LLM_BASE_URL/LLM_MODEL; not retrying.",
                        http_status(exc), llm_config_report()["base_url_host"],
                        cfg.model_id, task,
                    )
                if attempt < max_attempts and not rejected:
                    await asyncio.sleep(LLM_CALL_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
                    continue
                latency_ms = round((time.time() - start) * 1000, 1)
                _LEDGER.record(
                    GatewayResult(text="", model=cfg.model_id, task=task, latency_ms=latency_ms,
                                  attempts=attempts),
                    org_id, ok=False,
                )
                _persist_call_log(
                    org_id=org_id, job_id=job_id, task=task, model=cfg.model_id,
                    res=GatewayResult(text="", model=cfg.model_id, task=task,
                                      latency_ms=latency_ms, attempts=attempts),
                    ok=False, error=_failure_code(exc, rejected), tally=egress.current_tally(),
                )
                try:
                    span.set_attribute("llm.ok", False)
                except Exception:
                    pass
                if rejected:
                    raise LLMUnavailable(f"LLM provider rejected model {cfg.model_id}: {exc}") from exc
                raise RuntimeError(f"LLM call failed after {attempts} attempts: {exc}") from exc

    latency_ms = round((time.time() - start) * 1000, 1)
    cost = cost_usd(cfg, in_tok, out_tok)
    result = GatewayResult(
        text=text,
        model=cfg.model_id,
        task=task,
        parsed=parsed,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        latency_ms=latency_ms,
        attempts=attempts,
    )

    _LEDGER.record(result, org_id, ok=True)
    _persist_call_log(
        org_id=org_id, job_id=job_id, task=task, model=cfg.model_id,
        res=result, ok=True, error=None, tally=egress.current_tally(),
    )

    if use_cache:
        _CACHE[key] = (result, time.time() + LLM_CACHE_TTL_SECONDS)  # type: ignore[possibly-undefined]
        _CACHE.move_to_end(key)  # type: ignore[possibly-undefined]
        while len(_CACHE) > LLM_CACHE_MAX_ENTRIES:
            _CACHE.popitem(last=False)

    return result


async def complete_text(
    *,
    task: str,
    prompt: str,
    system_prompt: str | None = None,
    history: History | None = None,
    org_id: str | None = None,
    job_id: str | None = None,
    model_override: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    use_cache: bool = False,
) -> str:
    """
    Convenience wrapper around :func:`complete` for plain-text narratives.

    Returns the model's text. Raises :class:`LLMUnavailable` when no API key is
    configured; callers with a template fallback should catch it.
    """
    result = await complete(
        task=task,
        prompt=prompt,
        system_prompt=system_prompt,
        history=history,
        org_id=org_id,
        job_id=job_id,
        model_override=model_override,
        temperature=temperature,
        max_tokens=max_tokens,
        use_cache=use_cache,
    )
    return result.text


async def complete_json(*, task: str, prompt: str, strict: bool, **kwargs: Any) -> Any:
    """A completion whose reply is JSON, parsed and THEN restored (never textual replacement inside JSON).

    strict=True for data that may reach the books: a value holding an unknown or mangled placeholder comes
    back as None (the field is missing). strict=False for narratives: it reads "[bilinmeyen taraf]".
    Raises ValueError when the reply is not JSON, LLMUnavailable like `complete`."""
    result = await complete(task=task, prompt=prompt, json_reply="strict" if strict else "narrative", **kwargs)
    if result.parsed is egress.NOT_JSON or result.parsed is None:
        raise ValueError("the model's reply is not JSON")
    return result.parsed


async def stream(
    *,
    task: str,
    prompt: str,
    system_prompt: str | None = None,
    history: History | None = None,
    org_id: str | None = None,
    job_id: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
):
    """
    Stream a completion token-by-token through the gateway.

    Yields text chunks. Routing, tracing and cost logging still apply (cost is
    recorded when the stream ends). No retry/caching. Raises
    :class:`LLMUnavailable` before yielding when no key is set.
    """
    from app.services.telemetry import tracer

    await _enforce_org_budget(org_id)  # raises LLMBudgetExceeded

    system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
    cfg = _resolve_model(task, len(prompt), None)
    llm = _build_client(cfg, temperature, max_tokens)  # raises LLMUnavailable
    tally = egress.CallTally(org_id=org_id, task=task)
    sess = await _open_egress(org_id, task)  # raises LLMDisabled in `off` mode, before anything is built
    out_system, out_prompt, out_history = sess.outbound(system_prompt, prompt, history)
    messages = _build_messages(out_system, out_prompt, out_history)
    sess.sent(_texts(messages), tally)
    restorer = sess.stream_restorer()

    start = time.time()
    pieces: list[str] = []
    with tracer.start_as_current_span("llm.stream") as span:
        try:
            span.set_attribute("llm.task", task)
            span.set_attribute("llm.model", cfg.model_id)
        except Exception:
            pass
        async for chunk in llm.astream(messages):
            piece = getattr(chunk, "content", None) or (chunk if isinstance(chunk, str) else "")
            piece = restorer.feed(piece) if restorer and piece else piece
            if piece:
                pieces.append(piece)
                yield piece
        tail = restorer.flush() if restorer else ""
        if tail:
            pieces.append(tail)
            yield tail

    text = "".join(pieces)
    in_tok = int(len((system_prompt + prompt).split()) * 1.3)
    out_tok = int(len(text.split()) * 1.3)
    cost = cost_usd(cfg, in_tok, out_tok)
    res = GatewayResult(
        text=text, model=cfg.model_id, task=task,
        input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost,
        latency_ms=round((time.time() - start) * 1000, 1),
    )
    _LEDGER.record(res, org_id, ok=True)
    _persist_call_log(
        org_id=org_id, job_id=job_id, task=task, model=cfg.model_id,
        res=res, ok=True, error=None, tally=tally,
    )
