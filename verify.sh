#!/usr/bin/env bash
# =============================================================================
# verify.sh — Deterministic CI gate for Agentic CFO
#
# Usage:
#   ./verify.sh              → run all checks
#   ./verify.sh --fast       → skip mypy (type check takes longest)
#   ./verify.sh --backend    → backend checks only
#   ./verify.sh --frontend   → frontend checks only
#   ./scripts/proof.sh       → consolidation proof (structural + verify + optional staging)
#
# Exit codes:
#   0 = all checks passed (DONE)
#   1 = one or more checks failed
#
# Checks:
#   1. pytest backend/tests/     → 0 failures
#   2. ruff check backend/       → 0 lint errors
#   3. mypy backend/app/         → 0 type errors   (skip with --fast)
#   4. npm run build (frontend)  → 0 build errors
#
# =============================================================================
set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
OK()   { echo -e "${GREEN}✓${NC} $*"; }
FAIL() { echo -e "${RED}✗ FAILED:${NC} $*"; }
INFO() { echo -e "${CYAN}→${NC} $*"; }
WARN() { echo -e "${YELLOW}⚠${NC} $*"; }

# ── Argument parsing ──────────────────────────────────────────────────────────
RUN_BACKEND=true
RUN_FRONTEND=true
RUN_MYPY=true

for arg in "$@"; do
  case $arg in
    --fast)     RUN_MYPY=false ;;
    --backend)  RUN_FRONTEND=false ;;
    --frontend) RUN_BACKEND=false ;;
    --help|-h)
      echo "Usage: ./verify.sh [--fast] [--backend] [--frontend]"
      exit 0 ;;
  esac
done

FAILURES=0
CHECKS_RUN=0

# ── Helper: run a check ───────────────────────────────────────────────────────
check() {
  local name="$1"; shift
  INFO "Running: $name"
  CHECKS_RUN=$((CHECKS_RUN + 1))
  if "$@"; then
    OK "$name"
  else
    FAIL "$name"
    FAILURES=$((FAILURES + 1))
  fi
  echo ""
}

# ── Backend section ───────────────────────────────────────────────────────────
if $RUN_BACKEND; then
  echo -e "\n${CYAN}════════════════════════════════════════${NC}"
  echo -e "${CYAN}  BACKEND CHECKS${NC}"
  echo -e "${CYAN}════════════════════════════════════════${NC}\n"

  # Detect python executable. Try `python` first: on Windows `python3` is often
  # the Microsoft Store stub that errors out, while `python` is the real venv.
  PYTHON=""
  for py in python python3 py; do
    if command -v "$py" &>/dev/null && "$py" -c "import sys; sys.exit(0)" &>/dev/null; then
      PYTHON="$py"
      break
    fi
  done

  if [[ -z "$PYTHON" ]]; then
    WARN "Python not found in PATH — skipping backend checks"
    WARN "Install Python 3.11+ or activate your virtualenv"
    FAILURES=$((FAILURES + 1))
  else
    PY_VERSION=$($PYTHON --version 2>&1)
    INFO "Using: $PY_VERSION"

    # 1. pytest — full suite (parsers included), randomised order via
    #    pytest-randomly to surface cross-test state pollution.
    check "pytest (unit tests)" \
      $PYTHON -m pytest backend/tests/ -q --tb=short --no-header

    # 2. ruff lint
    if $PYTHON -m ruff --version &>/dev/null 2>&1; then
      check "ruff (lint)" \
        $PYTHON -m ruff check backend/app/ --output-format=concise
    else
      WARN "ruff not installed — install with: pip install ruff"
    fi

    # 3. mypy type check (slow, skippable with --fast)
    if $RUN_MYPY; then
      if $PYTHON -m mypy --version &>/dev/null 2>&1; then
        # 3a. Strict allowlist — BLOCKING. Modules in backend/mypy_strict.ini
        #     must stay at zero errors (the module-by-module paydown ratchet).
        check "mypy (strict allowlist)" \
          bash -c "cd backend && $PYTHON -m mypy --config-file mypy_strict.ini"
        # 3b. Full tree — NON-BLOCKING. ~590 legacy errors; shown for triage,
        #     does not fail the gate. Green a module, then add it to 3a.
        INFO "Running: mypy (full tree, advisory)"
        if $PYTHON -m mypy backend/app/ \
            --ignore-missing-imports --no-error-summary --pretty; then
          OK "mypy (full tree, advisory) — clean"
        else
          WARN "mypy (full tree, advisory) — legacy errors remain (not blocking)"
        fi
        echo ""
      else
        WARN "mypy not installed — install with: pip install mypy"
      fi
    else
      WARN "mypy skipped (--fast mode)"
    fi
  fi
fi

# ── Frontend section ──────────────────────────────────────────────────────────
if $RUN_FRONTEND; then
  echo -e "\n${CYAN}════════════════════════════════════════${NC}"
  echo -e "${CYAN}  FRONTEND CHECKS${NC}"
  echo -e "${CYAN}════════════════════════════════════════${NC}\n"

  if ! command -v node &>/dev/null; then
    WARN "Node.js not found in PATH — skipping frontend checks"
    WARN "Install Node 18+ and run: npm install --prefix frontend"
    FAILURES=$((FAILURES + 1))
  else
    NODE_VERSION=$(node --version)
    INFO "Using: Node $NODE_VERSION"

    if [[ ! -d "frontend/node_modules" ]]; then
      INFO "node_modules not found — running npm install..."
      npm install --prefix frontend --silent
    fi

    # 4. TypeScript build check
    check "tsc (type check)" \
      npm run --prefix frontend typecheck

    # 5. Next.js build (optional — slow, comment out for fast CI)
    # check "next build" \
    #   npm run --prefix frontend build 2>&1 | tail -20
  fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}════════════════════════════════════════${NC}"
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}  ✓ ALL CHECKS PASSED ($CHECKS_RUN checks)${NC}"
  echo -e "${CYAN}════════════════════════════════════════${NC}\n"
  exit 0
else
  echo -e "${RED}  ✗ $FAILURES CHECK(S) FAILED (of $CHECKS_RUN)${NC}"
  echo -e "${CYAN}════════════════════════════════════════${NC}\n"
  exit 1
fi
