#!/usr/bin/env bash
# verify.sh — deterministic done gate (verify-gate skill)
# Exits 0 = safe to ship. Non-zero = do not proceed.
# Used by CLAUDE.md law #1: "Done = ./verify.sh exits 0"
set -euo pipefail

echo "=== AI CFO verify gate ==="

# ── Backend checks ────────────────────────────────────────────────────────────
echo ""
echo "▶ Backend: ruff lint"
(cd backend && python -m ruff check app/ tests/ --quiet)

echo "▶ Backend: mypy type check"
(cd backend && python -m mypy app/ --ignore-missing-imports --quiet)

echo "▶ Backend: pytest"
(cd backend && python -m pytest tests/ -q --tb=short)

# ── Frontend checks ───────────────────────────────────────────────────────────
echo ""
echo "▶ Frontend: TypeScript type check"
(cd frontend && npm run typecheck --if-present)

echo "▶ Frontend: ESLint"
(cd frontend && npm run lint --if-present -- --max-warnings 0)

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "✓ All checks passed — safe to ship."
