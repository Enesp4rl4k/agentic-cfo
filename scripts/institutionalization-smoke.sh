#!/usr/bin/env bash
# Kurumsallaşma Endeksi (institutionalization index) smoke — structural + behavioural
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAIL=0
ok() { echo "✓ $1"; }
bad() { echo "✗ $1"; FAIL=1; }

test -f backend/app/services/institutionalization.py && ok "index service" || bad "service"
test -f backend/app/models/institutionalization_snapshot.py && ok "snapshot model" || bad "model"
test -f backend/alembic/versions/031_institutionalization.py && ok "migration 031" || bad "migration 031"
grep -q "async def compute_index" backend/app/services/institutionalization.py && ok "compute_index()" || bad "compute_index"
for dim in financial_discipline delegated_authority decision_traceability human_oversight process_cadence key_person_risk; do
  grep -q "\"$dim\"" backend/app/services/institutionalization.py && ok "dimension: $dim" || bad "dimension: $dim"
done
grep -q '"/institutionalization/compute"' backend/app/api/institutionalization.py && ok "POST /institutionalization/compute" || bad "compute endpoint"
grep -q '"/institutionalization/history"' backend/app/api/institutionalization.py && ok "GET /institutionalization/history" || bad "history endpoint"
grep -q "app.api.institutionalization" backend/app/api/registry.py && ok "router registered" || bad "router not registered"
test -f frontend/src/lib/api/institutionalization.ts && ok "frontend api lib" || bad "frontend lib"
test -f "frontend/src/app/(dashboard)/kurumsallasma/page.tsx" && ok "/kurumsallasma page" || bad "page"
grep -q '"/kurumsallasma"' "frontend/src/app/(dashboard)/layout.tsx" && ok "nav entry" || bad "nav entry"

( cd backend && python -c "
import asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
import app.main  # noqa
from app.database import Base
from app.services.institutionalization import compute_index, WEIGHTS
async def go():
    e = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with e.begin() as c: await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(e)() as s:
        r = await compute_index('org-x', s)
    assert set(d['key'] for d in r['dimensions']) == set(WEIGHTS)
    assert 0 <= r['overall_score'] <= 100 and r['grade'] in 'ABCDE'
    print('compute_index ok, empty-org score', r['overall_score'], r['grade'])
asyncio.run(go())
" ) && ok "compute_index behaviour" || bad "compute_index behaviour"

if [[ $FAIL -eq 0 ]]; then
  echo "✓ KURUMSALLAŞMA ENDEKSİ SMOKE PASSED"
  exit 0
else
  echo "✗ KURUMSALLAŞMA ENDEKSİ SMOKE FAILED"
  exit 1
fi
