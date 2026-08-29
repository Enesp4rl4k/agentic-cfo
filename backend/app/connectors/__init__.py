"""Connector Platform (Faz 13) — ports & adapters for external data sources.

Public surface:
  - `Connector` / `Watermark` / `CanonicalRow` / `ConnectorPayload` — the port.
  - `register` / `get_connector` / `list_connectors` — the registry.
  - `run_connector_sync` — the application service (persist + bookkeep).
"""
from __future__ import annotations

from app.connectors.base import (
    CanonicalRow,
    Connector,
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorError,
    ConnectorHealth,
    ConnectorPayload,
    Watermark,
)
from app.connectors.registry import (
    get_connector,
    has_connector,
    list_connectors,
    register,
)
from app.connectors.runner import ConnectorSyncResult, run_connector_sync

__all__ = [
    "CanonicalRow",
    "Connector",
    "ConnectorAuthError",
    "ConnectorConfigError",
    "ConnectorError",
    "ConnectorHealth",
    "ConnectorPayload",
    "ConnectorSyncResult",
    "Watermark",
    "get_connector",
    "has_connector",
    "list_connectors",
    "register",
    "run_connector_sync",
]
