#!/usr/bin/env bash
# Golden path structural check — components for 60s board deck demo exist and are wired.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAIL=0
ok() { echo "✓ $1"; }
bad() { echo "✗ $1"; FAIL=1; }

echo "Golden path structural checks"
echo "==========================="

# CFO pipeline
grep -q "run_cfo_pipeline" backend/app/agents/orchestrator.py && ok "CFO orchestrator" || bad "CFO orchestrator"
grep -q "node_verifier" backend/app/agents/orchestrator.py && ok "Verifier node in CFO graph" || bad "Verifier node"
grep -q "run_ceo_analysis" backend/app/worker.py && ok "CEO ARQ worker task" || bad "CEO worker"

# Auto chain + conductor
grep -q "on_agent_complete" backend/app/services/auto_chain.py && ok "Auto-chain hook" || bad "Auto-chain"
grep -q "ManagementConductor" backend/app/services/auto_chain.py && ok "Conductor in auto-chain" || bad "Conductor wiring"

# Board deck
grep -q "node_board_deck" backend/app/agents/ceo/orchestrator.py && ok "CEO board deck node" || bad "Board deck node"
test -f backend/app/services/board_deck_pdf.py && ok "Board deck PDF service" || bad "Board deck PDF"

# Conflict / negotiation
test -f backend/app/services/negotiation/consensus_engine.py && ok "Consensus engine" || bad "Consensus engine"
grep -q "negotiation" backend/app/api/registry.py && ok "Negotiation API registered" || bad "Negotiation API"

# RAG abstraction
test -f backend/app/services/rag/retriever.py && ok "RAG retriever abstraction" || bad "RAG retriever"
test -f backend/app/services/rag/grounding_validator.py && ok "Grounding validator" || bad "Grounding validator"

# TR data plane
test -f backend/app/models/canonical_transaction.py && ok "Canonical transactions" || bad "Canonical model"
test -f backend/alembic/versions/022_sync_runs_and_canonical_idempotency.py && ok "Sync runs migration" || bad "Sync migration"

# Frontend surfaces
test -f frontend/src/app/\(dashboard\)/command-center/page.tsx && ok "Command Center page" || bad "Command Center"
test -f frontend/src/app/\(dashboard\)/ceo/page.tsx && ok "CEO page (board deck)" || bad "CEO page"

echo ""
if [[ $FAIL -eq 0 ]]; then
  echo "✓ GOLDEN PATH STRUCTURAL CHECK PASSED"
  exit 0
else
  echo "✗ GOLDEN PATH STRUCTURAL CHECK FAILED"
  exit 1
fi
