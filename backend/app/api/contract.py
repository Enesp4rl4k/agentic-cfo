"""The API's response envelope, typed — and which routes the frontend's types come from.

Every route answers `{data, error, meta?}` (CLAUDE.md), but routes returned
`dict[str, Any]`: 1 of 369 had a typed response, so the frontend's types were
written by hand and had already drifted from what the backend sent (a profile
that was always blank, amounts in lira). A route that declares
`response_model=Envelope[X]` publishes X in the OpenAPI schema, and
`scripts/api_contract.py` turns the pilot routes' schema into
`frontend/src/lib/api/generated/`. Tests fail when the committed copy is stale.
"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    data: T
    error: str | None = None
    meta: dict[str, Any] | None = None


# The routes whose types the frontend generates. A route joins when its
# response is typed; the contract test checks every one here is.
PILOT_PATHS: tuple[str, ...] = (
    "/api/v1/baslangic",
    "/api/v1/briefing/monday",
    "/api/v1/briefing/monday/respond",
    "/api/v1/ledger/cash-radar",
    "/api/v1/ledger/plan-changes",
    "/api/v1/ledger/plan-changes/{change_id}/approve",
    "/api/v1/ledger/plan-changes/{change_id}/reject",
    "/api/v1/ledger/plan-changes/{change_id}/withdraw",
)


def pilot_openapi(schema: dict[str, Any]) -> dict[str, Any]:
    """The app's OpenAPI schema cut down to the pilot routes and what they reference."""
    import json
    import re

    paths = {p: schema["paths"][p] for p in PILOT_PATHS if p in schema["paths"]}
    all_schemas: dict[str, Any] = schema.get("components", {}).get("schemas", {})
    keep: set[str] = set()
    pending = re.findall(r"#/components/schemas/([^\"]+)", json.dumps(paths))
    while pending:
        name = pending.pop()
        if name in keep or name not in all_schemas:
            continue
        keep.add(name)
        pending.extend(re.findall(r"#/components/schemas/([^\"]+)", json.dumps(all_schemas[name])))
    return {
        "openapi": schema["openapi"],
        "info": {"title": "Tiphys pilot API", "version": schema["info"]["version"]},
        "paths": paths,
        "components": {"schemas": {k: all_schemas[k] for k in sorted(keep)}},
    }
