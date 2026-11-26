"""The owner's view of what leaves for a language model, and the owner's choice (Veri ve gizlilik).

Counts and settings only: the provider's host and model from the configuration, the mode in force and why,
which categories of data go in that mode, how many calls and bytes left in the last 30 days, and how many
names the books gave the masking dictionary. No payload is stored anywhere, so none can be shown.

The owner's choice is `organizations.llm_data_mode` and every change writes a decision record (who, when,
from what to what). It may tighten the platform's `LLM_DATA_MODE`; loosening it needs LLM_ORG_MAY_RELAX.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.decision import DecidedVia, DecisionKind
from app.models.organization import Organization
from app.platform.llm_egress import audit, dictionary, policy
from app.platform.llm_egress.policy import DataMode
from app.services.decisions import record_decision

_STRICTNESS = {DataMode.OFF: 0, DataMode.MASKED: 1, DataMode.RAW: 2}
_ALL = ("figures", "counterparties", "company", "identifiers", "descriptions", "document_text", "chat", "embeddings")


class ModeRefused(ValueError):
    """The requested mode is looser than the operator allows."""


def _embeddings_on() -> bool:
    s = get_settings()
    key = (s.openai_api_key or "").strip()
    return bool(s.rag_embedding_enabled and key and not key.startswith("llm-placeholder-"))


def categories(mode: DataMode) -> list[dict[str, str]]:
    """What goes in `mode`, by kind of data. States: sent, replaced (by placeholders), partly, not_sent."""
    docs_never = get_settings().llm_document_text == "never"
    if mode == DataMode.OFF:
        states = dict.fromkeys(_ALL, "not_sent")
    elif mode == DataMode.MASKED:
        states = {"figures": "sent", "counterparties": "replaced", "company": "replaced", "identifiers": "replaced",
                  "descriptions": "partly", "document_text": "not_sent" if docs_never else "partly",
                  "chat": "partly", "embeddings": "partly" if _embeddings_on() else "not_sent"}
    else:
        states = dict.fromkeys(("figures", "counterparties", "company", "identifiers", "descriptions", "chat"), "sent")
        states["document_text"] = "not_sent" if docs_never else "sent"
        states["embeddings"] = "sent" if _embeddings_on() else "not_sent"
    return [{"key": k, "state": states[k]} for k in _ALL]


def allowed_modes() -> list[str]:
    ceiling = policy.platform_mode()
    relax = bool(get_settings().llm_org_may_relax)
    return [m.value for m in DataMode if relax or _STRICTNESS[m] <= _STRICTNESS[ceiling]]


async def view(db: AsyncSession, org: Organization) -> dict[str, Any]:
    policy.forget_choice(str(org.id))
    decision = await policy.effective_mode(str(org.id))
    settings = get_settings()
    known = await dictionary.load(str(org.id)) if decision.mode == DataMode.MASKED else None
    host = policy.provider_host()
    return {
        "mode": decision.mode.value,
        "source": decision.source,
        "platform_mode": decision.platform_mode.value,
        "organisation_choice": decision.organisation_choice.value if decision.organisation_choice else None,
        "choice_capped": decision.capped,
        "allowed_modes": allowed_modes(),
        "provider_host": host,
        "provider_is_local": policy.is_local_provider(host),
        "model": settings.llm_model,
        "document_text": settings.llm_document_text,
        "categories": categories(decision.mode),
        "usage": await audit.usage_last_days(db, str(org.id), 30),
        "dictionary": None if known is None else {
            "known_names": len(known.names), "truncated": known.names.truncated, "complete": known.complete,
        },
    }


async def set_mode(db: AsyncSession, org: Organization, user_id: str, mode: str | None) -> None:
    """Record the owner's choice (None clears it: the platform's mode applies again). The caller commits."""
    new = None if mode is None else DataMode(mode)
    if new is not None and new.value not in allowed_modes():
        raise ModeRefused(new.value)
    before = {"mode": org.llm_data_mode}
    org.llm_data_mode = new.value if new else None
    await record_decision(
        db, org_id=str(org.id), kind=DecisionKind.LLM_DATA_MODE_CHANGE, target_type="organization",
        target_id=str(org.id), outcome="changed", decided_via=DecidedVia.HUMAN, decided_by=user_id,
        before=before, after={"mode": org.llm_data_mode},
    )
    policy.forget_choice(str(org.id))
