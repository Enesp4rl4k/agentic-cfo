"""Write the pilot routes' OpenAPI schema for the frontend to generate types from.

    cd backend && python ../scripts/api_contract.py
    cd frontend && npm run gen:api

`tests/test_api_contract.py` (backend) and `src/__tests__/api-contract.test.ts`
(frontend) fail when either committed file is stale, so a change to a pilot
route's response shape cannot reach master without the frontend's types.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "src" / "lib" / "api" / "generated" / "pilot-openapi.json"


def render() -> str:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.api.contract import pilot_openapi
    from app.main import app

    return json.dumps(pilot_openapi(app.openapi()), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
