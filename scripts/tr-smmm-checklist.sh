#!/usr/bin/env bash
# =============================================================================
# tr-smmm-checklist.sh — Structural TR moat + SMMM package proof
#
# Exit 0 = required symbols/endpoints present (sandbox live sync optional)
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

OK()   { echo "✓ $*"; }
FAIL() { echo "✗ $*"; exit 1; }
INFO() { echo "→ $*"; }

INFO "TR / SMMM structural checklist"

grep -q "_canonical_fingerprint" backend/app/services/scheduled_sync.py \
  || FAIL "missing sync fingerprint helper"
grep -q "_find_reusable_job" backend/app/services/scheduled_sync.py \
  || FAIL "missing idempotent job reuse"
grep -q "SyncStatus.SKIPPED" backend/app/services/scheduled_sync.py \
  || FAIL "missing SKIPPED sync_run finish path"
grep -q "/smmm/onay/package/" backend/app/api/smmm_onay.py \
  || FAIL "missing SMMM package endpoint"
grep -q "get_efatura_client\|GIB_EFATURA\|gib_efatura" backend/app/services/scheduled_sync.py \
  || FAIL "missing GIB e-Fatura pull hook"
grep -q "ParasutConnector" backend/app/services/scheduled_sync.py \
  || FAIL "missing Parasut connector pull"

OK "Paraşüt → canonical → SMMM package symbols present"
OK "GIB e-Fatura pull path present (live sandbox = staging skip if no creds)"
exit 0
