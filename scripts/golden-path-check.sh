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
grep -q "on_agent_complete" backend/app/agents/orchestration/auto_chain.py && ok "Auto-chain hook" || bad "Auto-chain"
grep -q "ManagementConductor" backend/app/agents/orchestration/auto_chain.py && ok "Conductor in auto-chain" || bad "Conductor wiring"

# Board deck
grep -q "node_board_deck" backend/app/agents/ceo/orchestrator.py && ok "CEO board deck node" || bad "Board deck node"
test -f backend/app/services/board_deck_pdf.py && ok "Board deck PDF service" || bad "Board deck PDF"

# Conflict / negotiation
test -f backend/app/services/negotiation/consensus_engine.py && ok "Consensus engine" || bad "Consensus engine"
grep -q "negotiation" backend/app/api/registry.py && ok "Negotiation API registered" || bad "Negotiation API"

# RAG abstraction
test -f backend/app/services/rag/retriever.py && ok "RAG retriever abstraction" || bad "RAG retriever"
test -f backend/app/services/rag/grounding_validator.py && ok "Grounding validator" || bad "Grounding validator"
grep -q "HybridRagRetriever" backend/app/services/rag/retriever.py && ok "Hybrid RAG retriever" || bad "Hybrid RAG retriever"
grep -q "no_evidence_verdict" backend/app/api/chat.py && ok "Chat no-evidence disclaimer" || grep -q "finalize_grounded_answer" backend/app/api/chat.py && ok "Chat no-evidence disclaimer" || bad "Chat no-evidence disclaimer"
grep -q "test_board_deck_pdf_smoke" backend/tests/test_agents/test_platform_engineering.py && ok "Board deck PDF smoke test" || bad "Board deck PDF smoke test"

# TR data plane
test -f backend/app/models/canonical_transaction.py && ok "Canonical transactions" || bad "Canonical model"
test -f backend/alembic/versions/022_sync_runs_and_canonical_idempotency.py && ok "Sync runs migration" || bad "Sync migration"

# Frontend surfaces
test -f frontend/src/app/\(dashboard\)/command-center/page.tsx && ok "Command Center page" || bad "Command Center"
test -f frontend/src/app/\(dashboard\)/ceo/page.tsx && ok "CEO page (board deck)" || bad "CEO page"

# Semantic model + unified write path
test -f backend/app/services/context_persist.py && ok "Context persist helper" || bad "Context persist"
grep -q "persist_agent_completion" backend/app/api/agent_jobs.py && ok "Agent jobs context persist" || bad "Agent jobs persist"
grep -q "prepare_grounded_chat" backend/app/api/chat.py && ok "Chat shared grounding pack" || bad "Chat shared grounding pack"
grep -q "finalize_grounded_answer" backend/app/api/chat.py && ok "Chat grounding finalize" || bad "Chat grounding finalize"
test -f backend/tests/test_agents/test_semantic_rebuild_integration.py && ok "Semantic rebuild integration test" || bad "Semantic rebuild integration test"
grep -q "ConflictCard" frontend/src/app/\(dashboard\)/command-center/page.tsx && ok "Command Center ConflictCard" || bad "Command Center ConflictCard"
grep -q "getDecisionBrief" frontend/src/app/\(dashboard\)/command-center/page.tsx && ok "Command Center getDecisionBrief" || bad "Command Center getDecisionBrief"
grep -q "/semantic/me/history" backend/app/api/semantic.py && ok "Semantic history API" || bad "Semantic history API"
grep -q "brief/approve" backend/app/api/semantic.py && ok "Brief approve API" || bad "Brief approve API"
test -f backend/app/services/semantic/rebuild.py && ok "Semantic rebuild" || bad "Semantic rebuild"
test -f frontend/src/components/ui/decision-brief-panel.tsx && ok "Decision brief panel" || bad "Decision brief panel"

test -f backend/app/services/data_plane/sync_complete.py && ok "Sync complete hook" || bad "Sync complete hook"
grep -q "billing_stripe" backend/app/services/scheduled_sync.py && ok "Stripe billing connector wired" || bad "Stripe billing connector"
grep -q "live-status" backend/app/api/semantic.py && ok "Live data status API" || bad "Live data status API"
test -f scripts/golden-path-live-sync-check.sh && ok "Live sync proof script" || bad "Live sync proof script"
test -f frontend/src/components/ui/baseline-source-badge.tsx && ok "Baseline source badge UI" || bad "Baseline badge UI"
test -f frontend/src/components/ui/semantic-metrics-panel.tsx && ok "Semantic metrics panel UI" || bad "Semantic metrics panel"
grep -q "_conductor_allows" backend/app/agents/orchestration/auto_chain.py && ok "Conductor skip in auto-chain" || bad "Conductor skip"
test -f frontend/src/components/ui/chat-evidence-chips.tsx && ok "Chat evidence chips UI" || bad "Chat evidence chips"
test -f backend/app/services/chat_grounding.py && ok "Shared chat grounding service" || bad "Chat grounding service"
grep -q "prepare_grounded_chat" backend/app/api/ws_stream.py && ok "WS stream grounded chat" || bad "WS stream grounding"
grep -q "finalize_grounded_answer" backend/app/api/ws_stream.py && ok "WS stream grounding finalize" || bad "WS stream finalize"
test -f frontend/src/lib/api/chat.ts && ok "Frontend grounded chat API" || bad "Frontend chat API"
grep -q "sendAgentChatMessage" frontend/src/app/\(dashboard\)/chat/page.tsx && ok "Main chat grounded mode" || bad "Main chat grounded mode"
grep -q "finalize_grounded_answer" backend/tests/test_agents/test_chat_grounding.py && ok "Chat grounding tests" || bad "Chat grounding tests"
grep -q "detect_metric_conflicts" backend/app/services/semantic/conflicts.py && ok "Metric conflict detector" || bad "Metric conflict detector"
test -f backend/app/services/eval_harness.py && ok "Grounding eval harness" || bad "Grounding eval harness"
grep -q "hr_export" backend/app/services/scheduled_sync.py && ok "HR export connector wired" || bad "HR export connector"
grep -q "github_activity" backend/app/services/scheduled_sync.py && ok "GitHub activity overlay wired" || bad "GitHub activity overlay"
grep -q "extract_numeric_claims" backend/app/services/rag/grounding_validator.py && ok "Numeric claim extractor" || bad "Numeric claim extractor"

echo ""
if [[ $FAIL -eq 0 ]]; then
  echo "✓ GOLDEN PATH STRUCTURAL CHECK PASSED"
  exit 0
else
  echo "✗ GOLDEN PATH STRUCTURAL CHECK FAILED"
  exit 1
fi
