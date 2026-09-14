#!/usr/bin/env bash
# =============================================================================
# staging-smoke.sh — Post-deploy smoke checks for ops visibility
#
# Usage:
#   BACKEND_URL=http://localhost:8000 ./scripts/staging-smoke.sh
#
# Exit 0 = all checks passed
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
OK()   { echo -e "${GREEN}✓${NC} $*"; }
FAIL() { echo -e "${RED}✗${NC} $*"; }
INFO() { echo -e "${CYAN}→${NC} $*"; }

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
API_PREFIX="${API_PREFIX:-/api/v1}"
FAILURES=0

check_http() {
  local name="$1"
  local url="$2"
  local expect_field="$3"

  INFO "GET $url"
  local body
  body=$(curl -sf --max-time 10 "$url") || {
    FAIL "$name — request failed"
    FAILURES=$((FAILURES + 1))
    return
  }

  if ! echo "$body" | grep -q "$expect_field"; then
    FAIL "$name — missing field: $expect_field"
    FAILURES=$((FAILURES + 1))
    return
  fi

  OK "$name"
}

echo ""
echo -e "${CYAN}  STAGING SMOKE — $BACKEND_URL${NC}"
echo ""

check_http "Liveness (/health)" \
  "$BACKEND_URL/health" \
  '"status"'

check_http "System health schema" \
  "$BACKEND_URL${API_PREFIX}/system/health" \
  '"schema_version"'

check_http "System ops queue depths" \
  "$BACKEND_URL${API_PREFIX}/system/ops" \
  '"queue_depths"'

# Validate maintenance queue key appears in ops payload
OPS_BODY=$(curl -sf --max-time 10 "$BACKEND_URL${API_PREFIX}/system/ops") || OPS_BODY=""
if echo "$OPS_BODY" | grep -q '"maintenance"'; then
  OK "Ops exposes maintenance queue depth"
else
  FAIL "Ops missing maintenance queue depth field"
  FAILURES=$((FAILURES + 1))
fi

echo ""
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}  ✓ STAGING SMOKE PASSED${NC}\n"
  exit 0
else
  echo -e "${RED}  ✗ STAGING SMOKE FAILED ($FAILURES)${NC}\n"
  exit 1
fi
