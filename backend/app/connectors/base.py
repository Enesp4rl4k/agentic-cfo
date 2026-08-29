"""The Connector port (ports & adapters).

A `Connector` is a stateless adapter over one external data source. It knows how
to check its own health and how to fetch records since a watermark, normalised
into a canonical row list. Everything else — persistence, idempotency, sync-run
bookkeeping, watermark storage, kernel notification — is the runner's job
(`app.connectors.runner`), so every adapter stays small.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Protocol, runtime_checkable


class ConnectorError(RuntimeError):
    """Base for connector failures."""


class ConnectorAuthError(ConnectorError):
    """Credentials missing, invalid, or revoked."""


class ConnectorConfigError(ConnectorError):
    """Non-secret config (e.g. owner/repo) missing or malformed."""


@dataclass(frozen=True)
class Watermark:
    """Opaque incremental cursor. `since` is the universal fallback every
    adapter understands; `cursor` is adapter-specific (e.g. an API page token)."""

    since: datetime | None = None
    cursor: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.since is None and self.cursor is None


@dataclass
class CanonicalRow:
    """One normalised record, ready for idempotent upsert.

    `source_record_id` must be stable for the same underlying record across
    syncs — it is the idempotency key together with (org_id, source).
    """

    source_record_id: str
    signal_type: str  # commit | pull_request | issue | incident | deploy
    occurred_at: datetime
    actor: str | None = None
    title: str | None = None
    magnitude: int | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorPayload:
    rows: list[CanonicalRow]
    next_watermark: Watermark
    warnings: list[str] = field(default_factory=list)


@dataclass
class ConnectorHealth:
    ok: bool
    detail: str
    account: str | None = None  # e.g. "acme/api" or the authed login


@runtime_checkable
class Connector(Protocol):
    """Adapter contract. Implementations are registered via
    `app.connectors.registry.register`."""

    name: ClassVar[str]           # "github"
    domain: ClassVar[str]         # engineering | hr | marketing | ops | finance
    kernel_role: ClassVar[str | None]  # C-level this feeds, e.g. "cto"; None if none

    async def health(self, *, config: Mapping[str, Any], secret: Mapping[str, Any]) -> ConnectorHealth:
        ...

    async def fetch(
        self,
        *,
        org_id: str,
        config: Mapping[str, Any],
        secret: Mapping[str, Any],
        since: Watermark,
    ) -> ConnectorPayload:
        ...
