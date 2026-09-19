"""Connector registry — the same shrink-only, decorator-registered pattern as
`app.services.regional.packs`.
"""
from __future__ import annotations

from app.connectors.base import Connector

_CONNECTORS: dict[str, Connector] = {}


def register(connector: type[Connector]) -> type[Connector]:
    """Class decorator: instantiate and register under `connector.name`."""
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
    """Import adapter modules so their @register decorators run. Import-time
    side effect kept explicit and cheap."""
    from app.connectors import github  # noqa: F401


_load_builtin()
