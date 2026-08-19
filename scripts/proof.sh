#!/usr/bin/env bash
# =============================================================================
# proof.sh — Consolidation proof gate
#
# Runs structural checks + verify.sh + optional staging/load baselines.
#
# Usage:
#   ./scripts/proof.sh              # full proof (verify + structural)
#   ./scripts/proof.sh --fast       # skip mypy in verify
#   BACKEND_URL=http://localhost:8000 ./scripts/proof.sh   # + staging smoke
#   RUN_LOAD_BASELINE=1 BACKEND_URL=... ./scripts/proof.sh # + load baseline
#
# Exit 0 = consolidation proof passed
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
OK()   { echo -e "${GREEN}✓${NC} $*"; }
FAIL() { echo -e "${RED}✗ FAILED:${NC} $*"; }
INFO() { echo -e "${CYAN}→${NC} $*"; }
WARN() { echo -e "${YELLOW}⚠${NC} $*"; }

FAILURES=0
CHECKS=0

check() {
  local name="$1"; shift
  INFO "Running: $name"
  CHECKS=$((CHECKS + 1))
  if "$@"; then
    OK "$name"
  else
    FAIL "$name"
    FAILURES=$((FAILURES + 1))
  fi
  echo ""
}

echo -e "\n${CYAN}════════════════════════════════════════${NC}"
echo -e "${CYAN}  CONSOLIDATION PROOF GATE${NC}"
echo -e "${CYAN}════════════════════════════════════════${NC}\n"

# ── Structural consolidation (no runtime deps) ───────────────────────────────
check "dual worker in docker-compose" \
  grep -q "worker-maintenance" docker-compose.yml

check "MaintenanceWorkerSettings wired" \
  grep -q "MaintenanceWorkerSettings" docker-compose.yml

check "maintenance queue env documented" \
  grep -q "ARQ_MAINTENANCE_QUEUE_NAME" .env.example

check "system ops API present" \
  test -f backend/app/api/system.py

check "canonical migration present" \
  test -f backend/alembic/versions/021_canonical_transactions.py

check "sync_runs migration present" \
  test -f backend/alembic/versions/022_sync_runs_and_canonical_idempotency.py

check "maintenance worker tasks registered" \
  grep -q "run_rag_backfill_maintenance" backend/app/worker.py

check "scheduler enqueues maintenance (not inline backfill)" \
  grep -q "enqueue_maintenance_job" backend/app/scheduler.py && \
  grep -q "run_rag_backfill_maintenance" backend/app/scheduler.py

# ── Core verify gate ─────────────────────────────────────────────────────────
INFO "Running: verify.sh (unit + lint + typecheck)"
CHECKS=$((CHECKS + 1))
if ./verify.sh "$@"; then
  OK "verify.sh"
else
  FAIL "verify.sh"
  FAILURES=$((FAILURES + 1))
fi
echo ""

# ── Optional staging smoke (live stack) ──────────────────────────────────────
if [[ -n "${BACKEND_URL:-}" ]]; then
  chmod +x scripts/staging-smoke.sh
  check "staging smoke ($BACKEND_URL)" \
    env BACKEND_URL="$BACKEND_URL" ./scripts/staging-smoke.sh
else
  WARN "BACKEND_URL not set — skipping staging smoke (set to enable live proof)"
  echo ""
fi

# ── Optional load baseline ───────────────────────────────────────────────────
if [[ "${RUN_LOAD_BASELINE:-0}" == "1" ]]; then
  if [[ -z "${BACKEND_URL:-}" ]]; then
    FAIL "RUN_LOAD_BASELINE=1 requires BACKEND_URL"
    FAILURES=$((FAILURES + 1))
  else
    chmod +x scripts/load-baseline.sh
    check "load baseline ($BACKEND_URL)" \
      env BACKEND_URL="$BACKEND_URL" ./scripts/load-baseline.sh
  fi
else
  WARN "RUN_LOAD_BASELINE not set — skipping load baseline"
  echo ""
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo -e "${CYAN}════════════════════════════════════════${NC}"
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}  ✓ CONSOLIDATION PROOF PASSED ($CHECKS checks)${NC}"
  echo -e "${CYAN}════════════════════════════════════════${NC}\n"
  exit 0
else
  echo -e "${RED}  ✗ CONSOLIDATION PROOF FAILED ($FAILURES of $CHECKS)${NC}"
  echo -e "${CYAN}════════════════════════════════════════${NC}\n"
  exit 1
fi
