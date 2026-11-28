"""One outbound call's egress session: decide the mode, mask what goes, restore what comes back.

The Model Gateway opens a session for every send (and the embedding gateway for every embedding batch),
so a payload cannot reach a provider without passing here. `open_session` raises `PolicyOff` in `off`
mode: nothing is built, nothing is sent.

FAIL CLOSED in `masked` mode: the session finds the company itself (the explicit `org_id`, else the tenant
context that `get_current_user`, the WebSocket and every worker / scheduler job set). When there is no
company, or its names dictionary cannot be read completely, nothing is sent: `EgressRefused` (a `PolicyOff`,
so callers take the same honest deterministic path as `off`), an audit row with the reason, a warning in the
log and an operator alert (`refusals`). Only a task declared in `system_calls.SYSTEM_CALLS`, each with the
reason it carries no tenant data, may go out without a company, with pattern masking only.

A `CallTally` collects, per logical call (all its retries), what the audit row records: the mode, how
many placeholders of each type were substituted, the bytes sent. Never the payload itself.
"""
from __future__ import annotations

import contextvars
import functools
import hashlib
import hmac
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.platform.llm_egress import dictionary, policy, refusals
from app.platform.llm_egress.policy import DataMode, PolicyOff
from app.platform.llm_egress.pseudonymizer import (
    PROMPT_NOTE,
    RESIDUE,
    Pseudonymizer,
    StreamRestorer,
)
from app.platform.llm_egress.system_calls import SYSTEM_CALLS

logger = logging.getLogger(__name__)

STABLE_TAG = "+pseud2"  # with the key version: a stored embedding's model name when computed on masked text
UNRESOLVED_KEY = "__unresolved__"  # strict JSON restore: the fields of this object that were set to None


@dataclass
class CallTally:
    org_id: str | None = None   # the organisation the call is made for (None: the tenant context decides)
    task: str | None = None     # purpose: the agent / task name
    mode: str | None = None
    bytes_out: int = 0
    sends: int = 0
    replaced: Counter = field(default_factory=Counter)
    flags: set[str] = field(default_factory=set)

    def as_record(self) -> dict[str, Any]:
        return {"counts": dict(self.replaced), "flags": sorted(self.flags), "sends": self.sends}


_TALLY: contextvars.ContextVar[CallTally | None] = contextvars.ContextVar("llm_call_tally", default=None)
# Set (to a list) by a narrative function that labels its template: the gateway appends "off" / "refused" when it
# did not send (agents.narrative_guard.labels_skipped_ai_step).
skipped_steps: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("llm_skipped_steps", default=None)
# The note a template carries when the AI step did not run for that reason (tr / en). Lives here, below every layer
# that labels a template (agents.narrative_guard, services.reasoning_loop).
AI_STEP_SKIPPED = {
    "off": "Yapay zekâ adımı atlandı (LLM_DATA_MODE=off): şablon metin. / AI step skipped (data mode off): template text.",
    "refused": "Yapay zekâ adımı atlandı (maskeli modda veri gönderilmedi): şablon metin. / "
               "AI step skipped (nothing sent in masked mode): template text.",
}


def begin_call(org_id: str | None = None, task: str | None = None) -> tuple[CallTally, contextvars.Token]:
    tally = CallTally(org_id=org_id, task=task)
    return tally, _TALLY.set(tally)


def end_call(token: contextvars.Token) -> None:
    _TALLY.reset(token)


def current_tally() -> CallTally | None:
    return _TALLY.get()


def tallied(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Run an async gateway entry point (keyword arguments `org_id`, `task`) inside one call tally."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        _tally, token = begin_call(kwargs.get("org_id"), kwargs.get("task"))
        try:
            return await fn(*args, **kwargs)
        finally:
            end_call(token)

    return wrapper


def _size(parts: list[str]) -> int:
    return sum(len(p.encode("utf-8")) for p in parts)


def stable_key(org_id: str | None) -> bytes:
    """Key of the per-organisation embedding pseudonyms: the server secret, bound to the organisation."""
    secret = get_settings().backend_secret_key
    return hmac.new(secret.encode(), f"llm-embedding-pseudonym:{org_id or ''}".encode(), hashlib.sha256).digest()


def key_version() -> str:
    """A short public fingerprint of the pseudonym key, part of a stored vector's tag: rotating
    BACKEND_SECRET_KEY changes the tag, so vectors of the old key are never compared with new ones; they are
    counted as "awaiting re-index" and re-embedded by the re-index job instead of silently ranking wrong."""
    secret = get_settings().backend_secret_key
    return hmac.new(secret.encode(), b"llm-embedding-key-version", hashlib.sha256).hexdigest()[:6]


def _looks_like_placeholder(value: str) -> bool:
    return bool(RESIDUE.search(value))


class EgressSession:
    def __init__(self, decision: policy.ModeDecision, org_id: str | None, pseudo: Pseudonymizer | None,
                 flags: set[str]) -> None:
        self.decision = decision
        self.mode = decision.mode
        self.org_id = org_id
        self.pseudo = pseudo
        self.flags = flags
        self.unresolved = 0  # strict restores that found an unknown / mangled placeholder (the value became None)

    def __repr__(self) -> str:  # the mapping lives in `pseudo`, whose repr is counts only
        return f"EgressSession(mode={self.mode.value}, org={'set' if self.org_id else 'none'}, pseudo={self.pseudo!r})"

    # ── what goes out ────────────────────────────────────────────────────────
    def outbound(self, system_prompt: str, prompt: str, history: list[dict[str, str]] | None
                 ) -> tuple[str, str, list[dict[str, str]] | None]:
        """The same three arguments, masked in `masked` mode and untouched in `raw` mode."""
        if self.pseudo is None:
            return system_prompt, prompt, history
        masked_history = None if history is None else [
            {**turn, "content": self.pseudo.mask(str(turn.get("content", "")))} for turn in history
        ]
        masked_system, masked_prompt = self.pseudo.mask(system_prompt), self.pseudo.mask(prompt)
        if self.pseudo.issued:  # say what the placeholders are and that they are copied unchanged
            masked_system = f"{masked_system}\n\n{PROMPT_NOTE}"
        return masked_system, masked_prompt, masked_history

    def outbound_texts(self, texts: list[str]) -> list[str]:
        return texts if self.pseudo is None else [self.pseudo.mask(t) for t in texts]

    def mask_obj(self, value: Any) -> Any:
        """Mask every string inside a JSON-like value (tool arguments, structured payloads)."""
        if self.pseudo is None:
            return value
        if isinstance(value, str):
            return self.pseudo.mask(value)
        if isinstance(value, dict):
            return {k: self.mask_obj(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self.mask_obj(v) for v in value]
        return value

    def sent(self, parts: list[str], tally: CallTally | None = None) -> None:
        """Record that a payload of these (already masked) texts is about to leave."""
        tally = tally or current_tally()
        if tally is None:
            return
        tally.mode = self.mode.value
        tally.org_id = tally.org_id or self.org_id  # the tenant context names the company when the caller did not
        tally.sends += 1
        tally.bytes_out += _size(parts)
        tally.flags |= self.flags
        if self.pseudo is not None:
            tally.replaced.update(self.pseudo.counts)
            self.pseudo.counts.clear()

    # ── what comes back ──────────────────────────────────────────────────────
    def restore(self, text: str) -> str:
        return text if self.pseudo is None else self.pseudo.restore(text)

    def restore_obj(self, parsed: Any) -> Any:
        """A structured (pydantic) narrative reply, restored AFTER parsing, string values only (numbers are
        never touched); an unknown placeholder reads "[bilinmeyen taraf]"."""
        if self.pseudo is None or parsed is None:
            return parsed
        dump = getattr(parsed, "model_dump", None)
        if dump is None:
            return parsed
        restored = self.restore_json(dump(), strict=False)
        try:
            return type(parsed).model_validate(restored)
        except Exception:
            return parsed.model_copy(update=restored)

    def restore_json(self, value: Any, *, strict: bool) -> Any:
        """Restore the string values of an already PARSED JSON value, never the serialised text (so a name
        with a quote or a backslash cannot break it). strict: a string holding an unknown or mangled
        placeholder becomes None, the field is missing (data for the books is never a placeholder);
        otherwise it reads "[bilinmeyen taraf]"."""
        if isinstance(value, dict):
            out: dict[Any, Any] = {}
            missing: list[str] = []
            for k, v in value.items():
                key = k
                if isinstance(k, str):  # keys are restored too: a placeholder can stand where a name was a key
                    restored_key = self.restore_json(k, strict=strict)
                    if restored_key is None:  # unknown placeholder as a key: the field is missing, the row held
                        missing.append(k)
                        continue
                    key = restored_key
                out[key] = self.restore_json(v, strict=strict)
                if strict and isinstance(v, str) and out[key] is None:
                    missing.append(key)
            if missing:  # say which fields were placeholders nobody can resolve: the consumer holds the row
                out[UNRESOLVED_KEY] = missing
            return out
        if isinstance(value, list):
            return [self.restore_json(v, strict=strict) for v in value]
        if not isinstance(value, str):
            return value
        if not strict:
            return value if self.pseudo is None else self.pseudo.restore(value)
        restored = (None if _looks_like_placeholder(value) else value) if self.pseudo is None else self.pseudo.restore_strict(value)
        self.unresolved += restored is None
        return restored

    def stream_restorer(self) -> StreamRestorer | None:
        return None if self.pseudo is None else StreamRestorer(self.pseudo)


async def open_session(org_id: str | None, *, stable: bool = False, task: str | None = None) -> EgressSession:
    """Decide the mode for this call and prepare its pseudonymizer.

    Raises PolicyOff in `off` mode, and EgressRefused (a PolicyOff) in `masked` mode when the company is
    unknown or its names cannot be loaded completely: nothing is sent, the reason is recorded."""
    org = policy.active_org(org_id)  # the named organisation, else the request's / job's tenant
    decision = await policy.effective_mode(org)
    if decision.mode == DataMode.OFF:
        raise PolicyOff(f"Yapay zekâya veri gönderimi kapalı (LLM_DATA_MODE=off, {decision.source}): bu adım atlandı")
    if decision.mode == DataMode.RAW:
        return EgressSession(decision, org, None, set())
    flags: set[str] = set()
    names = None
    if org:
        try:
            loaded = await dictionary.load(org)
        except Exception as exc:  # the names could not be read: nothing goes out unmasked
            loaded = None
            logger.warning("llm egress: names dictionary failed to load (%s)", type(exc).__name__)
        if loaded is None or not loaded.complete:
            raise refusals.refuse("dictionary_unavailable", task=task, org_id=org)
        names = loaded.names
        if names.truncated:
            flags.add("dictionary_truncated")
    elif task in SYSTEM_CALLS:
        flags.add("system_call_patterns_only")
    else:
        raise refusals.refuse("no_organisation_context", task=task, org_id=None)
    key = stable_key(org) if stable else None
    return EgressSession(decision, org, Pseudonymizer(names, stable_key=key), flags)
