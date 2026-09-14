#!/usr/bin/env bash
# Structural check: live sync → canonical → semantic brief path is wired.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAIL=0
ok() { echo "✓ $1"; }
bad() { echo "✗ $1"; FAIL=1; }

echo "Live sync → brief structural checks"
echo "===================================="

test -f backend/app/services/data_plane/sync_complete.py && ok "sync_complete hook" || bad "sync_complete"
grep -q "on_sync_canonical_persisted" backend/app/services/scheduled_sync.py && ok "scheduled_sync hook" || bad "scheduled_sync hook"
test -f backend/app/services/connectors/billing_stripe.py && ok "Stripe revenue connector" || bad "Stripe connector"
grep -q "live-status" backend/app/api/semantic.py && ok "live-status API" || bad "live-status API"
test -f frontend/src/components/ui/baseline-source-badge.tsx && ok "baseline badge UI" || bad "baseline badge"

echo ""
if [[ $FAIL -eq 0 ]]; then
  echo "✓ LIVE SYNC STRUCTURAL CHECK PASSED"
  exit 0
else
  echo "✗ LIVE SYNC STRUCTURAL CHECK FAILED"
  exit 1
fi
