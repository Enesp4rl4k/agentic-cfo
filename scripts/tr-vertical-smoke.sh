#!/usr/bin/env bash
# TR accounting vertical (L3 autopilot) smoke — import + structural check (no LLM required)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAIL=0
ok() { echo "✓ $1"; }
bad() { echo "✗ $1"; FAIL=1; }

# ── Backend: orchestration + endpoint ───────────────────────────────────────
test -f backend/app/agents/tr_vertical.py && ok "tr_vertical.py exists" || bad "tr_vertical.py"
grep -q "async def run_tr_vertical" backend/app/agents/tr_vertical.py && ok "run_tr_vertical entrypoint" || bad "run_tr_vertical"
grep -q "TR_VERTICAL_DEPTH_LEVEL = 3" backend/app/agents/tr_vertical.py && ok "declares L3 depth" || bad "L3 depth constant"
grep -q "approval_required" backend/app/agents/tr_vertical.py && ok "carries approval gate" || bad "approval gate field"
grep -q '"/muhasebe/tr-vertical"' backend/app/api/muhasebe.py && ok "POST /muhasebe/tr-vertical route" || bad "tr-vertical route"
grep -q 'tr-vertical/{job_id}/board-deck.pdf' backend/app/api/muhasebe.py && ok "GET board-deck.pdf download route" || bad "board-deck download route"
grep -q "board_deck_pdf_path" backend/app/agents/tr_vertical.py && ok "tr_vertical persists PDF path" || bad "PDF path not persisted"
! grep -q "import generate_board_deck_pdf" backend/app/api/advanced_intelligence.py && ok "advanced board-deck route uses a real builder" || bad "advanced board-deck route still imports missing symbol"
grep -q "require_tr_pack" backend/app/api/muhasebe.py && ok "route gated by require_tr_pack" || bad "route not gated"
grep -q '"auto_approved": False' backend/app/api/muhasebe.py && ok "never auto-approves" || bad "auto-approve guard"

# require_tr_pack must NOT touch the lazy .organization relationship (MissingGreenlet bug)
! grep -q 'getattr(current_user, "organization"' backend/app/api/deps_regional.py \
  && ok "require_tr_pack avoids lazy .organization load" || bad "require_tr_pack lazy-load regression"
grep -q "db.get(Organization" backend/app/api/deps_regional.py && ok "require_tr_pack loads org explicitly" || bad "explicit org load"

# ── Frontend: L3 page + api lib + nav ───────────────────────────────────────
test -f "frontend/src/app/(dashboard)/tr-vertical/page.tsx" && ok "tr-vertical page exists" || bad "tr-vertical page"
test -f frontend/src/lib/api/muhasebe.ts && ok "muhasebe.ts api lib exists" || bad "muhasebe.ts"
grep -q "runTrVertical" frontend/src/lib/api/muhasebe.ts && ok "runTrVertical client" || bad "runTrVertical client"
grep -q '"/tr-vertical"' "frontend/src/app/(dashboard)/layout.tsx" && ok "nav entry wired" || bad "nav entry"

# ── Eval corpus present ────────────────────────────────────────────────────
test -f backend/tests/test_eval_tr_corpus.py && ok "eval corpus test present" || bad "eval corpus test"
test -f backend/tests/fixtures/tr_corpus/technova_ocak_2024.csv && ok "eval fixture csv present" || bad "eval fixture csv"

# ── Confidence decomposition (differentiator #6) ──────────────────────────
test -f backend/app/agents/confidence_breakdown.py && ok "confidence_breakdown module" || bad "confidence_breakdown module"
grep -q "build_confidence_breakdown" backend/app/agents/verifier_node.py && ok "verifier emits confidence breakdown" || bad "verifier not wired"
grep -q "confidence_breakdown" backend/app/agents/tr_vertical.py && ok "tr_vertical passes breakdown through" || bad "tr_vertical not wired"
test -f frontend/src/components/ui/confidence-breakdown.tsx && ok "ConfidenceBreakdown component" || bad "ConfidenceBreakdown component"

if [[ $FAIL -eq 0 ]]; then
  echo "✓ TR VERTICAL SMOKE PASSED"
  exit 0
else
  echo "✗ TR VERTICAL SMOKE FAILED"
  exit 1
fi
