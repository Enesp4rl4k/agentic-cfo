"""One outbound call's egress session: decide the mode, mask what goes, restore what comes back.

The Model Gateway opens a session for every send (and the embedding gateway for every embedding batch),
so a payload cannot reach a provider without passing here. `open_session` raises `PolicyOff` in `off`
mode: nothing is built, nothing is sent.

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
from app.platform.llm_egress import dictionary, policy
from app.platform.llm_egress.policy import DataMode, PolicyOff
from app.platform.llm_egress.pseudonymizer import Pseudonymizer, StreamRestorer

logger = logging.getLogger(__name__)

STABLE_TAG = "+pseud1"  # appended to a stored embedding's model name when it was computed on masked text


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


class EgressSession:
    def __init__(self, decision: policy.ModeDecision, org_id: str | None, pseudo: Pseudonymizer | None,
                 flags: set[str]) -> None:
        self.decision = decision
        self.mode = decision.mode
        self.org_id = org_id
        self.pseudo = pseudo
        self.flags = flags

    # ── what goes out ────────────────────────────────────────────────────────
    def outbound(self, system_prompt: str, prompt: str, history: list[dict[str, str]] | None
                 ) -> tuple[str, str, list[dict[str, str]] | None]:
        """The same three arguments, masked in `masked` mode and untouched in `raw` mode."""
        if self.pseudo is None:
            return system_prompt, prompt, history
        masked_history = None if history is None else [
            {**turn, "content": self.pseudo.mask(str(turn.get("content", "")))} for turn in history
        ]
        return self.pseudo.mask(system_prompt), self.pseudo.mask(prompt), masked_history

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
        """Restore placeholders in a structured (pydantic) reply: strings only, numbers are never touched."""
        if self.pseudo is None or parsed is None:
            return parsed
        dump = getattr(parsed, "model_dump", None)
        if dump is None:
            return parsed
        restored = self._restore_json(dump())
        try:
            return type(parsed).model_validate(restored)
        except Exception:
            return parsed.model_copy(update=restored)

    def _restore_json(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.pseudo.restore(value)  # type: ignore[union-attr]
        if isinstance(value, dict):
            return {k: self._restore_json(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._restore_json(v) for v in value]
        return value

    def stream_restorer(self) -> StreamRestorer | None:
        return None if self.pseudo is None else StreamRestorer(self.pseudo)


async def open_session(org_id: str | None, *, stable: bool = False) -> EgressSession:
    """Decide the mode for this call and prepare its pseudonymizer. Raises PolicyOff in `off` mode."""
    org = policy.active_org(org_id)  # the named organisation, else the request's / job's tenant
    decision = await policy.effective_mode(org)
    if decision.mode == DataMode.OFF:
        raise PolicyOff(f"Yapay zekâya veri gönderimi kapalı (LLM_DATA_MODE=off, {decision.source}): bu adım atlandı")
    if decision.mode == DataMode.RAW:
        return EgressSession(decision, org, None, set())
    flags: set[str] = set()
    names = None
    if org:
        loaded = await dictionary.load(org)
        names = loaded.names
        if not loaded.complete:
            flags.add("dictionary_incomplete")
        if names.truncated:
            flags.add("dictionary_truncated")
    else:
        flags.add("no_organisation_context")  # patterns only: no names are known without a company
    key = stable_key(org) if stable else None
    return EgressSession(decision, org, Pseudonymizer(names, stable_key=key), flags)
