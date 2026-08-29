#!/usr/bin/env bash
# Durable Runs & run ledger (Faz 14) smoke — structural check (no network)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAIL=0
ok() { echo "✓ $1"; }
bad() { echo "✗ $1"; FAIL=1; }

test -f backend/app/models/agent_run.py && ok "agent_run model" || bad "agent_run model"
test -f backend/alembic/versions/028_agent_runs.py && ok "migration 028_agent_runs" || bad "migration 028"
test -f backend/app/agents/run_ledger.py && ok "run_ledger module" || bad "run_ledger module"
grep -q "async def resume_run" backend/app/agents/run_ledger.py && ok "resume_run entrypoint" || bad "resume_run"
grep -q "def agent_run" backend/app/agents/run_ledger.py && ok "agent_run context manager" || bad "agent_run"
grep -q "from app.agents.run_ledger import agent_run" backend/app/api/muhasebe.py && ok "tr-vertical wrapped in run ledger" || bad "tr-vertical not wrapped"
grep -q '"/runs/slo"' backend/app/api/runs.py && ok "GET /runs/slo endpoint" || bad "slo endpoint"
grep -q '"/runs/{run_id}/resume"' backend/app/api/runs.py && ok "POST /runs/{id}/resume endpoint" || bad "resume endpoint"
grep -q "app.api.runs" backend/app/api/registry.py && ok "runs router registered" || bad "runs router"

( cd backend && python -c "from app.agents.run_ledger import agent_run, resume_run; from app.models.agent_run import AgentRun; print('run ledger imports ok')" ) \
  && ok "run ledger import" || bad "run ledger import"

if [[ $FAIL -eq 0 ]]; then
  echo "✓ DURABLE RUNS SMOKE PASSED"
  exit 0
else
  echo "✗ DURABLE RUNS SMOKE FAILED"
  exit 1
fi
