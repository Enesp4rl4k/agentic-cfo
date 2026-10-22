#!/usr/bin/env python3
"""
golden_path_check.py — Cross-platform Golden Path Structural Verification.
Mirrors scripts/golden-path-check.sh for Windows and Linux.
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent


def check() -> int:
    fail = 0

    def ok(msg: str) -> None:
        print(f"✓ {msg}")

    def bad(msg: str) -> None:
        nonlocal fail
        print(f"✗ {msg}")
        fail = 1

    def file_exists(rel_path: str) -> bool:
        return (ROOT / rel_path).is_file()

    def file_contains(rel_path: str, needle: str) -> bool:
        p = ROOT / rel_path
        if not p.is_file():
            return False
        try:
            return needle in p.read_text(encoding="utf-8")
        except Exception:
            return False

    print("Golden path structural checks")
    print("===========================")

    # CFO pipeline
    if file_contains("backend/app/agents/orchestrator.py", "run_cfo_pipeline"):
        ok("CFO orchestrator")
    else:
        bad("CFO orchestrator")

    if file_contains("backend/app/agents/orchestrator.py", "node_verifier"):
        ok("Verifier node in CFO graph")
    else:
        bad("Verifier node")

    if file_contains("backend/app/worker.py", "run_ceo_analysis"):
        ok("CEO ARQ worker task")
    else:
        bad("CEO worker")

    # Auto chain + conductor
    if file_contains("backend/app/agents/orchestration/auto_chain.py", "on_agent_complete"):
        ok("Auto-chain hook")
    else:
        bad("Auto-chain")

    if file_contains("backend/app/agents/orchestration/auto_chain.py", "ManagementConductor"):
        ok("Conductor in auto-chain")
    else:
        bad("Conductor wiring")

    # Board deck
    if file_contains("backend/app/agents/ceo/orchestrator.py", "node_board_deck"):
        ok("CEO board deck node")
    else:
        bad("Board deck node")

    if file_exists("backend/app/services/board_deck_pdf.py"):
        ok("Board deck PDF service")
    else:
        bad("Board deck PDF")

    # Conflict / negotiation
    if file_exists("backend/app/services/negotiation/consensus_engine.py"):
        ok("Consensus engine")
    else:
        bad("Consensus engine")

    if file_contains("backend/app/api/registry.py", "negotiation"):
        ok("Negotiation API registered")
    else:
        bad("Negotiation API")

    # RAG abstraction
    if file_exists("backend/app/services/rag/retriever.py"):
        ok("RAG retriever abstraction")
    else:
        bad("RAG retriever")

    if file_exists("backend/app/services/rag/grounding_validator.py"):
        ok("Grounding validator")
    else:
        bad("Grounding validator")

    if file_contains("backend/app/services/rag/retriever.py", "HybridRagRetriever"):
        ok("Hybrid RAG retriever")
    else:
        bad("Hybrid RAG retriever")

    if file_contains("backend/app/api/chat.py", "finalize_grounded_answer") or file_contains("backend/app/api/chat.py", "no_evidence_verdict"):
        ok("Chat no-evidence disclaimer")
    else:
        bad("Chat no-evidence disclaimer")

    if file_contains("backend/tests/test_agents/test_platform_engineering.py", "test_board_deck_pdf_smoke"):
        ok("Board deck PDF smoke test")
    else:
        bad("Board deck PDF smoke test")

    # TR data plane
    if file_exists("backend/app/models/canonical_transaction.py"):
        ok("Canonical transactions")
    else:
        bad("Canonical model")

    if file_exists("backend/alembic/versions/022_sync_runs_and_canonical_idempotency.py"):
        ok("Sync runs migration")
    else:
        bad("Sync migration")

    # Frontend surfaces
    if file_exists("frontend/src/app/(dashboard)/command-center/page.tsx"):
        ok("Command Center page")
    else:
        bad("Command Center")

    if file_exists("frontend/src/app/(dashboard)/ceo/page.tsx"):
        ok("CEO page (board deck)")
    else:
        bad("CEO page")

    # Semantic model + unified write path
    if file_exists("backend/app/services/context_persist.py"):
        ok("Context persist helper")
    else:
        bad("Context persist")

    if file_contains("backend/app/api/agent_jobs.py", "persist_agent_completion"):
        ok("Agent jobs context persist")
    else:
        bad("Agent jobs persist")

    if file_contains("backend/app/api/chat.py", "prepare_grounded_chat"):
        ok("Chat shared grounding pack")
    else:
        bad("Chat shared grounding pack")

    if file_contains("backend/app/api/chat.py", "finalize_grounded_answer"):
        ok("Chat grounding finalize")
    else:
        bad("Chat grounding finalize")

    if file_exists("backend/tests/test_agents/test_semantic_rebuild_integration.py"):
        ok("Semantic rebuild integration test")
    else:
        bad("Semantic rebuild integration test")

    if file_contains("frontend/src/app/(dashboard)/command-center/page.tsx", "ConflictCard"):
        ok("Command Center ConflictCard")
    else:
        bad("Command Center ConflictCard")

    if file_contains("frontend/src/app/(dashboard)/command-center/page.tsx", "getDecisionBrief"):
        ok("Command Center getDecisionBrief")
    else:
        bad("Command Center getDecisionBrief")

    if file_contains("backend/app/api/semantic.py", "/semantic/me/history"):
        ok("Semantic history API")
    else:
        bad("Semantic history API")

    if file_contains("backend/app/api/semantic.py", "brief/approve"):
        ok("Brief approve API")
    else:
        bad("Brief approve API")

    if file_exists("backend/app/services/semantic/rebuild.py"):
        ok("Semantic rebuild")
    else:
        bad("Semantic rebuild")

    if file_exists("frontend/src/components/ui/decision-brief-panel.tsx"):
        ok("Decision brief panel")
    else:
        bad("Decision brief panel")

    if file_exists("backend/app/services/data_plane/sync_complete.py"):
        ok("Sync complete hook")
    else:
        bad("Sync complete hook")

    if file_contains("backend/app/services/scheduled_sync.py", "billing_stripe"):
        ok("Stripe billing connector wired")
    else:
        bad("Stripe billing connector")

    if file_contains("backend/app/api/semantic.py", "live-status"):
        ok("Live data status API")
    else:
        bad("Live data status API")

    if file_exists("scripts/golden-path-live-sync-check.sh"):
        ok("Live sync proof script")
    else:
        bad("Live sync proof script")

    if file_exists("frontend/src/components/ui/baseline-source-badge.tsx"):
        ok("Baseline source badge UI")
    else:
        bad("Baseline badge UI")

    if file_exists("frontend/src/components/ui/semantic-metrics-panel.tsx"):
        ok("Semantic metrics panel UI")
    else:
        bad("Semantic metrics panel")

    if file_contains("backend/app/agents/orchestration/auto_chain.py", "_conductor_allows"):
        ok("Conductor skip in auto-chain")
    else:
        bad("Conductor skip")

    if file_exists("frontend/src/components/ui/chat-evidence-chips.tsx"):
        ok("Chat evidence chips UI")
    else:
        bad("Chat evidence chips")

    if file_exists("backend/app/services/chat_grounding.py"):
        ok("Shared chat grounding service")
    else:
        bad("Chat grounding service")

    if file_contains("backend/app/api/ws_stream.py", "prepare_grounded_chat"):
        ok("WS stream grounded chat")
    else:
        bad("WS stream grounding")

    if file_contains("backend/app/api/ws_stream.py", "finalize_grounded_answer"):
        ok("WS stream grounding finalize")
    else:
        bad("WS stream finalize")

    if file_exists("frontend/src/lib/api/chat.ts"):
        ok("Frontend grounded chat API")
    else:
        bad("Frontend chat API")

    if file_contains("frontend/src/app/(dashboard)/chat/page.tsx", "sendAgentChatMessage"):
        ok("Main chat grounded mode")
    else:
        bad("Main chat grounded mode")

    if file_contains("backend/tests/test_agents/test_chat_grounding.py", "finalize_grounded_answer"):
        ok("Chat grounding tests")
    else:
        bad("Chat grounding tests")

    if file_contains("backend/app/services/semantic/conflicts.py", "detect_metric_conflicts"):
        ok("Metric conflict detector")
    else:
        bad("Metric conflict detector")

    if file_exists("backend/app/services/eval_harness.py"):
        ok("Grounding eval harness")
    else:
        bad("Grounding eval harness")

    if file_contains("backend/app/services/scheduled_sync.py", "hr_export"):
        ok("HR export connector wired")
    else:
        bad("HR export connector")

    if file_contains("backend/app/services/scheduled_sync.py", "github_activity"):
        ok("GitHub activity overlay wired")
    else:
        bad("GitHub activity overlay")

    if file_contains("backend/app/services/rag/grounding_validator.py", "extract_numeric_claims"):
        ok("Numeric claim extractor")
    else:
        bad("Numeric claim extractor")

    print("")
    if fail == 0:
        print("✓ GOLDEN PATH STRUCTURAL CHECK PASSED")
        return 0
    else:
        print("✗ GOLDEN PATH STRUCTURAL CHECK FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(check())
