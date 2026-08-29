"""
Model Gateway — the single egress point for every LLM call in the backend.

Nothing else may instantiate ``ChatOpenAI`` (or any other model client).  All
agents, skills, routers and services call :func:`complete`, which owns the
cross-cutting concerns that were previously copy-pasted (or missing) at ~40 call
sites:

  * model selection      — delegated to the task→model table in ``llm_router``
  * structured output    — ``schema=`` returns a validated pydantic instance
  * retry + backoff      — transient errors are retried up to LLM_CALL_MAX_ATTEMPTS
  * timeout              — every call is bounded by LLM_CALL_TIMEOUT_SECONDS
  * cost ledger          — one ``LLMCallLog`` row per call + in-process aggregate
  * tracing              — an OpenTelemetry span per call
  * graceful degradation — a placeholder API key raises :class:`LLMUnavailable`
                           so callers fall back to their deterministic templates

Design rule (enforced by tests/test_platform/test_llm_egress_single_chokepoint.py):
``from langchain_openai import ChatOpenAI`` appears in this module only.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from pydantic import BaseModel

from app.platform.model_catalog import MODELS, ModelConfig, select_model
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

_PLACEHOLDER_KEYS = {
    "llm-placeholder-dev",
    "llm-placeholder-demo",
    "llm-placeholder-ci",
    "",
}

_DEFAULT_SYSTEM_PROMPT = (
    "Sen C-Suite düzeyinde bir Türk iş danışmanısın. "
    "Kısa, net ve eyleme dönüştürülebilir cevaplar ver. Sayısal verileri vurgula."
)


class LLMUnavailable(RuntimeError):
    """No usable API key is configured — callers should use a deterministic fallback."""


class LLMBudgetExceeded(RuntimeError):
    """The org has spent past its monthly LLM budget. Callers should fall back."""

    def __init__(self, org_id: str, spend_usd: float, budget_usd: float) -> None:
        super().__init__(
            f"org {org_id} LLM spend ${spend_usd:.2f} >= budget ${budget_usd:.2f}"
        )
        self.org_id = org_id
        self.spend_usd = spend_usd
        self.budget_usd = budget_usd


def is_placeholder_key(api_key: str | None) -> bool:
    if not api_key:
        return True
    return api_key in _PLACEHOLDER_KEYS or api_key.startswith("llm-placeholder-")


# ── Result type ──────────────────────────────────────────────────────────────

@dataclass
class GatewayResult:
    text: str
    model: str
    task: str
    parsed: Any | None = None          # pydantic instance when schema= was given
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    from_cache: bool = False
    attempts: int = 1


# ── In-process cost ledger (survives without a DB) ───────────────────────────

@dataclass
class _Ledger:
    calls: int = 0
    ok_calls: int = 0
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    by_model: dict[str, dict[str, float]] = field(default_factory=dict)
    by_org: dict[str, dict[str, float]] = field(default_factory=dict)

    def record(self, res: GatewayResult, org_id: str | None, ok: bool) -> None:
        self.calls += 1
        if ok:
            self.ok_calls += 1
        self.total_cost_usd = round(self.total_cost_usd + res.cost_usd, 6)
        self.total_input_tokens += res.input_tokens
        self.total_output_tokens += res.output_tokens
        m = self.by_model.setdefault(res.model, {"calls": 0, "cost_usd": 0.0})
        m["calls"] += 1
        m["cost_usd"] = round(m["cost_usd"] + res.cost_usd, 6)
        key = org_id or "(none)"
        o = self.by_org.setdefault(key, {"calls": 0, "cost_usd": 0.0})
        o["calls"] += 1
        o["cost_usd"] = round(o["cost_usd"] + res.cost_usd, 6)

    def snapshot(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "ok_calls": self.ok_calls,
            "total_cost_usd": self.total_cost_usd,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "avg_cost_usd": round(self.total_cost_usd / self.calls, 6) if self.calls else 0.0,
            "by_model": self.by_model,
            "by_org": self.by_org,
        }

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]


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
    if model_override:
        return MODELS.get(model_override, MODELS["gpt-4o"])
    try:
        return select_model(task, prompt_len)
    except Exception:  # deterministic task / unknown → safest capable model
        return MODELS["gpt-4o"]


def _cache_key(model: str, system_prompt: str, prompt: str, schema_name: str) -> str:
    h = hashlib.sha256()
    h.update(f"{model}\x00{schema_name}\x00{system_prompt}\x00{prompt}".encode())
    return h.hexdigest()


# ── Raw provider call (the ONLY place ChatOpenAI is built) ───────────────────

History = list[dict[str, str]]  # [{"role": "user"|"assistant", "content": "..."}]


def _build_client(cfg: ModelConfig, temperature: float | None, max_tokens: int | None) -> Any:
    """Construct the model client. The ONLY ChatOpenAI() call in the backend."""
    from app.config import get_settings

    settings = get_settings()
    if is_placeholder_key(settings.openai_api_key):
        raise LLMUnavailable("openai_api_key is a placeholder")

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=cfg.model_id,
        temperature=cfg.temperature if temperature is None else temperature,
        max_tokens=cfg.max_tokens if max_tokens is None else max_tokens,
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


async def _raw_chat(
    cfg: ModelConfig,
    system_prompt: str,
    prompt: str,
    *,
    schema: type[BaseModel] | None,
    temperature: float | None,
    max_tokens: int | None,
    history: History | None = None,
) -> tuple[str, Any | None, int, int]:
    llm = _build_client(cfg, temperature, max_tokens)
    messages = _build_messages(system_prompt, prompt, history)

    if schema is not None:
        structured = llm.with_structured_output(schema)
        parsed = await structured.ainvoke(messages)
        text = parsed.to_text() if hasattr(parsed, "to_text") else str(parsed)
        # structured-output responses rarely expose usage; estimate from text
        in_tok = int(len((system_prompt + prompt).split()) * 1.3)
        out_tok = int(len(text.split()) * 1.3)
        return text, parsed, in_tok, out_tok

    response = await llm.ainvoke(messages)
    text = response.content or ""
    usage = getattr(response, "usage_metadata", None) or {}
    in_tok = int(usage.get("input_tokens", len((system_prompt + prompt).split()) * 1.3))
    out_tok = int(usage.get("output_tokens", len(text.split()) * 1.3))
    return text, None, in_tok, out_tok


def _persist_call_log(
    *,
    org_id: str | None,
    job_id: str | None,
    task: str,
    model: str,
    res: GatewayResult | None,
    ok: bool,
    error: str | None,
) -> None:
    """Best-effort write of one LLMCallLog row. Never raises into the caller."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _write() -> None:
        try:
            from app.database import session_factory
            from app.models.llm_call_log import LLMCallLog

            async with session_factory()() as db:
                db.add(
                    LLMCallLog(
                        org_id=org_id,
                        job_id=job_id,
                        task_type=task,
                        model=model,
                        input_tokens=res.input_tokens if res else 0,
                        output_tokens=res.output_tokens if res else 0,
                        cost_usd=res.cost_usd if res else 0.0,
                        latency_ms=res.latency_ms if res else 0.0,
                        ok=ok,
                        from_cache=res.from_cache if res else False,
                        attempts=res.attempts if res else 1,
                        error=(error or None),
                    )
                )
                await db.commit()
        except Exception as exc:  # pragma: no cover - ledger must not break agents
            logger.debug("LLMCallLog persist skipped: %s", exc)

    loop.create_task(_write())


# ── Public entry point ─────────────────────────────────────────────────────

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
) -> GatewayResult:
    """
    Run one LLM completion with routing, retry, timeout, caching, cost logging
    and tracing.

    Raises:
        LLMUnavailable: the configured API key is a placeholder. Callers that
            have a deterministic fallback should catch this and use it.
    """
    system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
    cfg = _resolve_model(task, len(prompt), model_override)
    schema_name = schema.__name__ if schema is not None else ""

    if use_cache:
        key = _cache_key(cfg.model_id, system_prompt, prompt, schema_name)
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
                    ),
                    timeout=timeout_s,
                )
                break
            except LLMUnavailable:
                # No API key configured — not a real call. Don't touch the ledger
                # or spawn a DB write; the caller falls back to a template.
                raise
            except (TimeoutError, Exception) as exc:
                if attempt < max_attempts:
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
                    ok=False, error=f"{type(exc).__name__}: {exc}",
                )
                try:
                    span.set_attribute("llm.ok", False)
                except Exception:
                    pass
                raise RuntimeError(f"LLM call failed after {attempts} attempts: {exc}") from exc

    latency_ms = round((time.time() - start) * 1000, 1)
    cost = round(
        (in_tok * cfg.cost_per_1k_in + out_tok * cfg.cost_per_1k_out) / 1000, 6
    )
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
        res=result, ok=True, error=None,
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
    configured — callers with a deterministic template should catch it (a bare
    ``except Exception`` around a template fallback already does).
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

    Yields text chunks. Routing + tracing + cost logging still apply (cost is
    recorded once the stream finishes). No retry/caching for streams.

    Raises :class:`LLMUnavailable` before yielding anything when no key is set.
    """
    from app.services.telemetry import tracer

    await _enforce_org_budget(org_id)  # raises LLMBudgetExceeded

    system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
    cfg = _resolve_model(task, len(prompt), None)
    llm = _build_client(cfg, temperature, max_tokens)  # raises LLMUnavailable
    messages = _build_messages(system_prompt, prompt, history)

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
            if piece:
                pieces.append(piece)
                yield piece

    text = "".join(pieces)
    in_tok = int(len((system_prompt + prompt).split()) * 1.3)
    out_tok = int(len(text.split()) * 1.3)
    cost = round((in_tok * cfg.cost_per_1k_in + out_tok * cfg.cost_per_1k_out) / 1000, 6)
    res = GatewayResult(
        text=text, model=cfg.model_id, task=task,
        input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost,
        latency_ms=round((time.time() - start) * 1000, 1),
    )
    _LEDGER.record(res, org_id, ok=True)
    _persist_call_log(
        org_id=org_id, job_id=job_id, task=task, model=cfg.model_id,
        res=res, ok=True, error=None,
    )
