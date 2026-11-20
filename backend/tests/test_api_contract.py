"""The frontend's pilot types come from the backend's own schema, and stay current.

1 of 369 routes had a typed response, so the frontend's types were written by
hand and had drifted (a profile that was always blank, amounts in lira). The
pilot routes now declare `response_model=Envelope[...]`; their schema is
committed as frontend/src/lib/api/generated/pilot-openapi.json and the TS
types are generated from it.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.api.contract import PILOT_PATHS, pilot_openapi
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
COMMITTED = ROOT / "frontend" / "src" / "lib" / "api" / "generated" / "pilot-openapi.json"


def _writer():
    spec = importlib.util.spec_from_file_location("api_contract", ROOT / "scripts" / "api_contract.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_schema_is_current() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == _writer().render(), (
        "pilot-openapi.json is stale — run `cd backend && python ../scripts/api_contract.py` "
        "and `cd frontend && npm run gen:api`, and commit both files"
    )


def test_every_pilot_route_has_a_typed_envelope() -> None:
    paths = pilot_openapi(app.openapi())["paths"]
    untyped = []
    for path in PILOT_PATHS:
        assert path in paths, f"{path} is not a route"
        for method, op in paths[path].items():
            ok = {code: r for code, r in op["responses"].items() if code.startswith("2")}
            # A typed response points at a named schema; `dict[str, Any]` does not.
            if not ok or not all("#/components/schemas/" in json.dumps(r) for r in ok.values()):
                untyped.append(f"{method.upper()} {path}")
    assert not untyped, "pilot route without a typed envelope:\n  " + "\n  ".join(untyped)


def test_the_published_radar_carries_every_field_the_radar_has() -> None:
    """A field added to the radar must not be dropped from the response by the schema."""
    from dataclasses import fields

    from app.api import radar_schema as out
    from app.services import cash_radar as radar

    pairs = [(radar.CashRadar, out.CashRadarOut), (radar.RadarWeek, out.RadarWeekOut),
             (radar.RadarItem, out.RadarItemOut), (radar.Shortfall, out.ShortfallOut)]
    for dc, model in pairs:
        assert {f.name for f in fields(dc)} == set(model.model_fields), dc.__name__
