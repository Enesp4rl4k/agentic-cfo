"""Guard: every registered router must actually import.

`register_routers` deliberately swallows ImportError so one broken optional
module cannot take down the server in production. That resilience also makes a
broken router *invisible* — `app.api.ingestion_webhooks` sat in the registry for
months importing a symbol that never existed, silently skipped on every boot.

This test removes the blind spot: the registry is the contract, and every entry
in it must import cleanly and expose its router attribute. If a module is
genuinely optional, delete its registry line — do not leave it broken.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi import APIRouter

from app.api.registry import _ROUTERS


def test_registry_is_not_empty() -> None:
    assert len(_ROUTERS) > 50, "router registry looks truncated"


@pytest.mark.parametrize(
    ("module_path", "attr"),
    [(m, a) for m, a, _ in _ROUTERS],
    ids=[m.rsplit(".", 1)[-1] for m, _, _ in _ROUTERS],
)
def test_registered_router_imports(module_path: str, attr: str) -> None:
    """Each registry entry imports and exposes an APIRouter."""
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:  # pragma: no cover - the failure IS the message
        pytest.fail(
            f"{module_path} is registered but does not import: {exc}\n"
            "Fix the module or remove its line from app/api/registry.py — "
            "a registered-but-broken router is silently skipped at runtime."
        )
    router = getattr(module, attr, None)
    assert isinstance(router, APIRouter), (
        f"{module_path}.{attr} is not an APIRouter (got {type(router).__name__})"
    )


def test_no_duplicate_router_registrations() -> None:
    paths = [m for m, _, _ in _ROUTERS]
    dupes = {p for p in paths if paths.count(p) > 1}
    assert not dupes, f"duplicate router registrations: {sorted(dupes)}"
