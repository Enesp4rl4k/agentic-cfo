#!/usr/bin/env bash
# Board deck PDF smoke — import + structural check (no LLM required)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAIL=0
ok() { echo "✓ $1"; }
bad() { echo "✗ $1"; FAIL=1; }

test -f backend/app/services/board_deck_pdf.py && ok "board_deck_pdf.py exists" || bad "board_deck_pdf.py"
grep -q "async def generate_board_deck_pdf" backend/app/services/board_deck_pdf.py && ok "generate_board_deck_pdf" || bad "generate_board_deck_pdf"
grep -q "Generate board deck" frontend/src/app/\(dashboard\)/command-center/page.tsx && ok "Command Center CTA" || bad "Command Center CTA"
grep -q "analyze-from-job" frontend/src/app/\(dashboard\)/command-center/page.tsx && ok "CTA wires analyze-from-job" || bad "CTA wiring"
grep -q "job_completion_p95_ms" frontend/src/app/\(dashboard\)/command-center/page.tsx && ok "P95 timing display" || bad "P95 timing"

if [[ $FAIL -eq 0 ]]; then
  echo "✓ BOARD DECK SMOKE PASSED"
  exit 0
else
  echo "✗ BOARD DECK SMOKE FAILED"
  exit 1
fi
