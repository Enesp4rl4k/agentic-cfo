#!/usr/bin/env bash
# Backup -> restore -> migrate -> health, on throwaway databases. Proves the procedure, not a backup.
#
# CI runs it (the "Migrations on Postgres" job of .github/workflows/ci.yml) against a Postgres service. It needs no Docker, no
# secrets and no network beyond localhost:
#
#   1. migrate an empty database to head and put known rows and files in it (the "source")
#   2. dump it (pg_dump -Fc, the format scripts/backup.sh of the staging stack writes) and tar the uploads
#   3. restore the dump into a second, empty database (pg_restore --exit-on-error)
#   4. every table has the source's row count; the uploads unpack to identical files
#   5. `python -m app.core.preflight --db` accepts the restored database (schema at head)
#   6. one migration down: the same command REFUSES the database (behind) and /api/v1/ready answers 503;
#      back up to head: it is accepted again and /api/v1/ready is not a 503
#   7. scripts/smoke-test.sh passes against the API running on the restored database
#
# Tools: psql, pg_dump, pg_restore, createdb, dropdb (PostgreSQL 16 client), python with the backend's
# requirements, tar, sha256sum, curl. The backend dependencies must be installed.
#
# Environment (defaults suit the CI service container):
#   PGHOST=localhost PGPORT=5432 PGUSER=aicfo   (PGPASSWORD if the server wants one)
#   RT_API_PORT=8765   port for the throwaway API
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PGHOST="${PGHOST:-localhost}" PGPORT="${PGPORT:-5432}" PGUSER="${PGUSER:-aicfo}"
RT_API_PORT="${RT_API_PORT:-8765}"
SRC_DB="aicfo_rt_src_$$"
DST_DB="aicfo_rt_dst_$$"
WORK="$(mktemp -d)"
API_PID=""
log() { printf '%s roundtrip: %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { printf '%s roundtrip: FAIL %s\n' "$(date -u +%FT%TZ)" "$*" >&2; exit 1; }

cleanup() {
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null || true
  dropdb --if-exists "$SRC_DB" >/dev/null 2>&1 || true
  dropdb --if-exists "$DST_DB" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

for bin in psql pg_dump pg_restore createdb dropdb python tar sha256sum curl; do
  command -v "$bin" >/dev/null || die "missing '$bin'"
done

# The application's own settings, pointed at one database or the other. A good production
# configuration: the preflight must accept it, so only the database's state can fail it.
app_env() {
  local db="$1"
  export USE_SQLITE=false
  export DATABASE_URL_OVERRIDE="postgresql+asyncpg://${PGUSER}@${PGHOST}:${PGPORT}/${db}"
  export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
  export BACKEND_SECRET_KEY="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  export NEXTAUTH_SECRET="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  export FRONTEND_URL="https://app.roundtrip.test" BRAND_APP_URL="https://app.roundtrip.test"
  export BACKEND_URL="https://api.roundtrip.test" BACKEND_CORS_ORIGINS="https://app.roundtrip.test"
  export OPENAI_API_KEY="llm-placeholder-ci" LANGGRAPH_CHECKPOINT=memory
}
in_backend() { (cd "$REPO_ROOT/backend" && "$@"); }
count_rows() {
  local db="$1"
  psql -d "$db" -At -F $'\t' -c "
    SELECT table_name,
           (xpath('/row/c/text()',
                  query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name),
                               false, true, '')))[1]::text
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    ORDER BY table_name;"
}

# 1. Source database: migrated, with known content ---------------------------------------------
createdb "$SRC_DB"
(app_env "$SRC_DB"; in_backend alembic upgrade head) >/dev/null
HEAD_REV="$(psql -d "$SRC_DB" -At -c 'SELECT version_num FROM alembic_version')"
[[ -n "$HEAD_REV" ]] || die "source database has no alembic revision"
psql -d "$SRC_DB" -v ON_ERROR_STOP=1 -q <<'SQL'
INSERT INTO outbox_messages (id, key, org_id, channel, recipient, subject, body, source, source_ref,
                             delivery_class, status, attempts, created_at)
VALUES ('00000000-0000-0000-0000-0000000000a1', 'roundtrip:sentinel-1', 'org-roundtrip', 'email',
        'sentinel@example.test', 'sentinel', 'body', 'roundtrip', 'ref-1', 'released', 'sent', 1, now()),
       ('00000000-0000-0000-0000-0000000000a2', 'roundtrip:sentinel-2', 'org-roundtrip', 'email',
        'sentinel@example.test', 'sentinel', 'body', 'roundtrip', 'ref-2', 'released', 'failed', 3, now());
SQL
mkdir -p "$WORK/uploads/uploads/job-1" "$WORK/uploads/reports/job-1"
printf 'ledger-a\n' > "$WORK/uploads/uploads/job-1/document.csv"
head -c 100000 /dev/urandom > "$WORK/uploads/uploads/job-1/document.pdf"
printf 'report\n' > "$WORK/uploads/reports/job-1/report.xlsx"
log "source at $HEAD_REV with 2 sentinel rows and 3 files"

# 2. Back up -----------------------------------------------------------------------------------
pg_dump -d "$SRC_DB" -Fc --no-owner > "$WORK/db.dump"
[[ -s "$WORK/db.dump" ]] || die "pg_dump produced an empty file"
tar -C "$WORK" -czf "$WORK/uploads.tar.gz" uploads
count_rows "$SRC_DB" > "$WORK/src_counts.tsv"
(cd "$WORK/uploads" && find . -type f -exec sha256sum {} + | sort -k2) > "$WORK/src_files.sha"
log "dumped $(du -h "$WORK/db.dump" | cut -f1), uploads archived"

# 3. Restore into an empty database --------------------------------------------------------------
createdb "$DST_DB"
pg_restore -d "$DST_DB" --no-owner --exit-on-error "$WORK/db.dump"
log "pg_restore ok"

# 4. Same rows, same files ---------------------------------------------------------------------
count_rows "$DST_DB" > "$WORK/dst_counts.tsv"
if ! diff -u "$WORK/src_counts.tsv" "$WORK/dst_counts.tsv"; then die "row counts differ after restore"; fi
[[ "$(psql -d "$DST_DB" -At -c "SELECT count(*) FROM outbox_messages WHERE source = 'roundtrip'")" == 2 ]] \
  || die "sentinel rows did not come back"
mkdir "$WORK/restored"
tar -C "$WORK/restored" -xzf "$WORK/uploads.tar.gz"
(cd "$WORK/restored/uploads" && find . -type f -exec sha256sum {} + | sort -k2) > "$WORK/dst_files.sha"
diff -u "$WORK/src_files.sha" "$WORK/dst_files.sha" || die "restored uploads differ"
log "$(wc -l < "$WORK/dst_counts.tsv" | tr -d ' ') tables and $(wc -l < "$WORK/dst_files.sha" | tr -d ' ') files identical"

# 5. The application accepts the restored database ---------------------------------------------
app_env "$DST_DB"
[[ "$(psql -d "$DST_DB" -At -c 'SELECT version_num FROM alembic_version')" == "$HEAD_REV" ]] \
  || die "restored alembic revision differs"
in_backend python -m app.core.preflight --db || die "preflight refused the restored database"

# 6. One migration behind: refused; at head again: accepted -------------------------------------
in_backend alembic downgrade -1 >/dev/null
if in_backend python -m app.core.preflight --db >"$WORK/behind.txt"; then
  cat "$WORK/behind.txt"; die "preflight accepted a database one migration behind"
fi
grep -q 'SCHEMA behind' "$WORK/behind.txt" || { cat "$WORK/behind.txt"; die "preflight did not say 'behind'"; }
log "preflight refuses a database behind the code"

start_api() {
  (cd "$REPO_ROOT/backend" && exec python -m uvicorn app.main:app --host 127.0.0.1 --port "$RT_API_PORT") \
    >"$WORK/api.log" 2>&1 &
  API_PID=$!
  for _ in $(seq 1 90); do
    curl -sf --max-time 3 "http://127.0.0.1:${RT_API_PORT}/health" >/dev/null && return 0
    kill -0 "$API_PID" 2>/dev/null || { tail -40 "$WORK/api.log"; die "API exited during startup"; }
    sleep 1
  done
  tail -40 "$WORK/api.log"; die "API did not answer in 90 s"
}
stop_api() { kill "$API_PID" 2>/dev/null || true; wait "$API_PID" 2>/dev/null || true; API_PID=""; }

start_api
ready_code="$(curl -s --max-time 10 -o "$WORK/ready.json" -w '%{http_code}' "http://127.0.0.1:${RT_API_PORT}/api/v1/ready")"
[[ "$ready_code" == 503 ]] || { cat "$WORK/ready.json"; die "/ready answered $ready_code on a database behind the code (want 503)"; }
grep -q '"code": *"behind"' "$WORK/ready.json" || { cat "$WORK/ready.json"; die "/ready did not report migrations 'behind'"; }
log "/api/v1/ready answers 503 'behind'"
stop_api

in_backend alembic upgrade head >/dev/null
in_backend python -m app.core.preflight --db || die "preflight refused the database after migrating"
log "migrated back to head; preflight accepts"

# 7. Smoke test against the API on the restored database ---------------------------------------
start_api
"$REPO_ROOT/scripts/smoke-test.sh" --api "http://127.0.0.1:${RT_API_PORT}" --origin "https://app.roundtrip.test" \
  || die "smoke test failed on the restored database"
log "RESULT: OK — dump restores, migrates, passes preflight and the smoke test"
