"""Connector registry — the same shrink-only, decorator-registered pattern as
`app.services.regional.packs`.
"""

from __future__ import annotations

from app.connectors.base import Connector

_CONNECTORS: dict[str, Connector] = {}


def register(connector: type[Connector]) -> type[Connector]:
    """Class decorator or registration helper: instantiate and register under `connector.name`."""
    instance = connector()  # type: ignore[call-arg]
    if instance.name in _CONNECTORS:
        raise ValueError(f"connector '{instance.name}' already registered")
    _CONNECTORS[instance.name] = instance
    return connector


def get_connector(name: str) -> Connector:
    try:
        return _CONNECTORS[name]
    except KeyError:
        raise KeyError(f"unknown connector '{name}'") from None


def list_connectors() -> list[Connector]:
    return list(_CONNECTORS.values())


def has_connector(name: str) -> bool:
    return name in _CONNECTORS


def _load_builtin() -> None:
    """Register built-in adapter modules. Kept explicit so adapters do not need
    to import registry back, avoiding circular import dependencies."""
    from app.connectors.github import GitHubConnector
    from app.connectors.open_banking import OpenBankingConnectorAdapter
    from app.connectors.parasut import ParasutConnectorAdapter

    register(GitHubConnector)
    register(ParasutConnectorAdapter)
    register(OpenBankingConnectorAdapter)


_load_builtin()
