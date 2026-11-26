"""What may leave for a language model: the mode, per platform and per organisation.

LLM_DATA_MODE (platform default) and `organizations.llm_data_mode` (the owner's own choice, written with
a decision record by `PUT /privacy/ai-data-mode`) take one of three values:

  off      no LLM and no embedding call at all; the product runs on its deterministic paths
  masked   identifiers and the names the books hold are replaced by placeholders before the call
  raw      today's behaviour: the text goes as it is. Always an explicit choice, never a fallback.

The organisation's choice may be as strict as or stricter than the platform's, and looser only when the
operator allows it (LLM_ORG_MAY_RELAX): the platform setting is the operator's ceiling. Nothing here
decides whether a transfer is lawful; it makes the lawful options possible.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from app.config import get_settings
from app.core.tenancy import get_current_tenant, set_current_tenant

logger = logging.getLogger(__name__)


class DataMode(StrEnum):
    OFF = "off"
    MASKED = "masked"
    RAW = "raw"


_STRICTNESS = {DataMode.OFF: 0, DataMode.MASKED: 1, DataMode.RAW: 2}
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "host.docker.internal")
_CHOICE_TTL_SECONDS = 20.0
_CHOICES: dict[str, tuple[str | None, float]] = {}


class PolicyOff(RuntimeError):
    """The effective mode is `off`: nothing is sent, the caller takes its deterministic path."""


@dataclass(frozen=True)
class ModeDecision:
    mode: DataMode
    source: str                 # "platform" | "organisation"
    platform_mode: DataMode
    organisation_choice: DataMode | None
    capped: bool                # the organisation asked for more than the operator allows


def parse_mode(value: object, default: DataMode = DataMode.MASKED) -> DataMode:
    try:
        return DataMode(str(value).strip().lower())
    except ValueError:
        return default


def platform_mode() -> DataMode:
    return parse_mode(getattr(get_settings(), "llm_data_mode", "masked"))


def provider_host() -> str | None:
    """Host of LLM_BASE_URL; None when it is unset (the OpenAI default)."""
    url = (getattr(get_settings(), "llm_base_url", "") or "").strip()
    return (urlsplit(url).hostname or None) if url else None


def is_local_provider(host: str | None = None) -> bool:
    host = host if host is not None else provider_host()
    if not host:
        return False
    return host in _LOCAL_HOSTS or host.endswith((".localhost", ".internal"))


def resolve(platform: DataMode, choice: DataMode | None, may_relax: bool) -> ModeDecision:
    if choice is None:
        return ModeDecision(platform, "platform", platform, None, False)
    if _STRICTNESS[choice] > _STRICTNESS[platform] and not may_relax:
        return ModeDecision(platform, "platform", platform, choice, True)
    return ModeDecision(choice, "organisation", platform, choice, False)


def forget_choice(org_id: str) -> None:
    _CHOICES.pop(org_id, None)


async def _stored_choice(org_id: str) -> str | None:
    hit = _CHOICES.get(org_id)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    from app import database
    from app.models.organization import Organization

    async with database.session_factory()() as db:
        value = await db.get(Organization, org_id)
    choice = getattr(value, "llm_data_mode", None) if value is not None else None
    _CHOICES[org_id] = (choice, time.monotonic() + _CHOICE_TTL_SECONDS)
    return choice


def active_org(org_id: str | None) -> str | None:
    """The organisation a call belongs to: the one named, else the request's / job's tenant context."""
    return org_id or get_current_tenant()


async def effective_mode(org_id: str | None) -> ModeDecision:
    settings = get_settings()
    platform = platform_mode()
    org = active_org(org_id)
    if not org:
        return ModeDecision(platform, "platform", platform, None, False)
    try:
        stored = await _stored_choice(org)
        choice = parse_mode(stored) if stored else None
    except Exception as exc:
        # Fail closed: the organisation's choice could not be read, so the stricter of the platform's
        # mode and `masked` applies, and the log says why.
        logger.warning("llm data mode: organisation choice unreadable (%s); using the stricter default", exc)
        fallback = platform if _STRICTNESS[platform] <= _STRICTNESS[DataMode.MASKED] else DataMode.MASKED
        return ModeDecision(fallback, "platform", platform, None, False)
    return resolve(platform, choice, bool(getattr(settings, "llm_org_may_relax", False)))


def document_text_allowed(mode: DataMode) -> bool:
    """Strict document mode: LLM_DOCUMENT_TEXT=never sends no uploaded-document text in any mode."""
    return mode != DataMode.OFF and getattr(get_settings(), "llm_document_text", "allow") != "never"


async def begin_document_extraction(org_id: str | None) -> str | None:
    """Enter the company's context for an extraction and say why the AI step must be skipped (shown to the
    person), or None when it may go."""
    if org_id:
        set_current_tenant(str(org_id))
    mode = (await effective_mode(org_id)).mode
    if mode == DataMode.OFF:
        return "Yapay zekâ adımı atlandı: bu şirket için yapay zekâya veri gönderimi kapalı (LLM_DATA_MODE=off)."
    if not document_text_allowed(mode):
        return "Yapay zekâ adımı atlandı: belge metni yapay zekâya gönderilmiyor (LLM_DOCUMENT_TEXT=never)."
    return None
