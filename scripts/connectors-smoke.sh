#!/usr/bin/env bash
# Connector Platform (Faz 13) smoke — structural + registry check (no network)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAIL=0
ok() { echo "✓ $1"; }
bad() { echo "✗ $1"; FAIL=1; }

# ── Package + port ─────────────────────────────────────────────────────────
test -f backend/app/connectors/base.py && ok "connectors/base.py" || bad "connectors/base.py"
grep -q "class Connector(Protocol)" backend/app/connectors/base.py && ok "Connector protocol" || bad "Connector protocol"
grep -q "class Watermark" backend/app/connectors/base.py && ok "Watermark cursor type" || bad "Watermark"
grep -q "def register" backend/app/connectors/registry.py && ok "registry.register" || bad "registry.register"
grep -q "async def run_connector_sync" backend/app/connectors/runner.py && ok "run_connector_sync service" || bad "run_connector_sync"

# ── First adapter: GitHub → CTO ───────────────────────────────────────────
grep -q '@register' backend/app/connectors/github.py && ok "github adapter registered" || bad "github adapter"
grep -q 'kernel_role: ClassVar\[str | None\] = "cto"' backend/app/connectors/github.py && ok "github feeds CTO" || bad "github kernel_role"

# ── Canonical model + migration ──────────────────────────────────────────
test -f backend/app/models/canonical_eng_signal.py && ok "canonical_eng_signal model" || bad "canonical_eng_signal model"
test -f backend/app/models/connector_connection.py && ok "connector_connection model" || bad "connector_connection model"
test -f backend/alembic/versions/027_connectors.py && ok "migration 027_connectors" || bad "migration 027"
grep -q "uq_canonical_eng_org_source_record" backend/app/models/canonical_eng_signal.py && ok "canonical idempotency constraint" || bad "idempotency constraint"

# ── API + kernel flip ────────────────────────────────────────────────────
grep -q '"/connectors/{name}/sync"' backend/app/api/connectors.py && ok "POST /connectors/{name}/sync" || bad "sync route"
grep -q "cto_existing_data_from_signals" backend/app/api/cto_cmo_kernel.py && ok "CTO kernel reads real eng signals" || bad "CTO kernel not wired to signals"
grep -q "app.api.connectors" backend/app/api/registry.py && ok "connectors router registered" || bad "connectors router"

# ── Frontend: connector control on the CTO page ─────────────────────────
test -f frontend/src/lib/api/connectors.ts && ok "frontend connectors api lib" || bad "frontend connectors lib"
test -f frontend/src/components/cto/GitHubConnectorCard.tsx && ok "GitHubConnectorCard component" || bad "GitHubConnectorCard"
grep -q "GitHubConnectorCard" "frontend/src/app/(dashboard)/cto/page.tsx" && ok "CTO page mounts connector card" || bad "CTO page not wired"

# ── Registry actually loads the adapter ──────────────────────────────────
( cd backend && python -c "from app.connectors import list_connectors; names=[c.name for c in list_connectors()]; assert 'github' in names, names; print('registry loads', names)" ) \
  && ok "connector registry import" || bad "connector registry import"

if [[ $FAIL -eq 0 ]]; then
  echo "✓ CONNECTOR PLATFORM SMOKE PASSED"
  exit 0
else
  echo "✗ CONNECTOR PLATFORM SMOKE FAILED"
  exit 1
fi
