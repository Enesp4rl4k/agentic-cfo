#!/usr/bin/env bash
# Yetki Matrisi / Delegation-of-Authority engine smoke — structural + behavioural
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAIL=0
ok() { echo "✓ $1"; }
bad() { echo "✗ $1"; FAIL=1; }

test -f backend/app/platform/authority_matrix.py && ok "authority_matrix engine" || bad "engine"
test -f backend/app/models/authority_policy.py && ok "authority_policy model" || bad "model"
test -f backend/alembic/versions/030_authority_policies.py && ok "migration 030" || bad "migration 030"
grep -q "def evaluate" backend/app/platform/authority_matrix.py && ok "evaluate()" || bad "evaluate()"
grep -q "def validate_rules" backend/app/platform/authority_matrix.py && ok "validate_rules()" || bad "validate_rules()"
grep -q "async def load_active_rules" backend/app/platform/authority_matrix.py && ok "load_active_rules()" || bad "load_active_rules()"

# wired into the accounting engine (replaces the hard-coded ONAY_LIMIT_TRY block)
grep -q "authority_matrix import" backend/app/agents/accounting/double_entry.py && ok "double_entry uses the matrix" || bad "double_entry not wired"
! grep -q "if amount > self.ONAY_LIMIT_TRY" backend/app/agents/accounting/double_entry.py && ok "hard-coded ONAY_LIMIT check removed" || bad "hard-coded check still present"
grep -q "authority_rules" backend/app/agents/accounting/orchestrator.py && ok "orchestrator threads authority_rules" || bad "orchestrator not threaded"
grep -q "load_active_rules" backend/app/api/muhasebe.py && ok "muhasebe API resolves org policy" || bad "muhasebe API not resolving policy"

grep -q '"/authority/policy"' backend/app/api/authority.py && ok "GET/PUT /authority/policy" || bad "policy endpoints"
grep -q '"/authority/evaluate"' backend/app/api/authority.py && ok "POST /authority/evaluate (dry-run)" || bad "evaluate endpoint"
grep -q 'role not in ("owner", "admin")' backend/app/api/authority.py && ok "PUT gated to owner/admin" || bad "PUT not gated"
grep -q "app.api.authority" backend/app/api/registry.py && ok "router registered" || bad "router not registered"

( cd backend && python -c "
from app.platform.authority_matrix import evaluate, AuthorityRequest, DEFAULT_POLICY_RULES as D
assert evaluate(D, AuthorityRequest(domain='journal_entry', amount_kurus=5000)).outcome == 'auto_approve'
d = evaluate(D, AuthorityRequest(domain='journal_entry', amount_kurus=100_000*100+1))
assert d.outcome == 'needs_approval' and d.required_approvals == [{'role':'owner','count':1}]
print('engine behaviour ok')
" ) && ok "engine behaviour (auto vs escalate)" || bad "engine behaviour"

if [[ $FAIL -eq 0 ]]; then
  echo "✓ AUTHORITY MATRIX SMOKE PASSED"
  exit 0
else
  echo "✗ AUTHORITY MATRIX SMOKE FAILED"
  exit 1
fi
