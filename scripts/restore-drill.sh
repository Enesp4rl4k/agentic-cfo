#!/usr/bin/env bash
# Restore drill: prove a backup made by scripts/backup.sh actually restores.
#
#   ./scripts/restore-drill.sh                      # newest archive on the remote
#   ./scripts/restore-drill.sh path/to/aicfo-….tar.age
#
# What it does, all in throwaway containers on a throwaway network (nothing
# published, nothing touching the live stack's volumes):
#   1. fetch + checksum-verify + decrypt the archive (needs the age PRIVATE key)
#   2. start an EMPTY pgvector/pgvector:pg16 and pg_restore the dump into it
#   3. `alembic current` (with the backend image) must equal the revision
#      recorded at backup time, and be a head of the image's migrations
#   4. per-table row counts vs the backup's manifest
#   5. uploads archive unpacks and holds the recorded file count
#   6. scripts/golden_path_check.py (repo structural check — it checks the code
#      the restored data will run under, not the data itself)
#
# Required env:
#   AGE_IDENTITY_FILE      path to the age private key (bring it for the drill,
#                          delete it after — it must not stay on the server)
# Optional:
#   BACKUP_RCLONE_REMOTE   where to fetch the newest archive when none is given
#   BACKEND_IMAGE          default agentic-cfo-backend:${IMAGE_TAG:-latest}
#
# Exit 0 = the backup restores. Anything else = treat backups as broken.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f .env && -z "${BACKUP_RCLONE_REMOTE:-}" ]]; then
  line="$(grep -E '^BACKUP_RCLONE_REMOTE=' .env | tail -n1 || true)"
  [[ -n "$line" ]] && export BACKUP_RCLONE_REMOTE="${line#*=}"
fi
: "${AGE_IDENTITY_FILE:?AGE_IDENTITY_FILE (age private key file) is not set}"
[[ -r "$AGE_IDENTITY_FILE" ]] || { echo "drill: cannot read $AGE_IDENTITY_FILE" >&2; exit 2; }
BACKEND_IMAGE="${BACKEND_IMAGE:-agentic-cfo-backend:${IMAGE_TAG:-latest}}"

for bin in docker age sha256sum tar; do
  command -v "$bin" >/dev/null || { echo "drill: missing '$bin'" >&2; exit 2; }
done

log()  { printf '%s drill: %s\n' "$(date -u +%FT%TZ)" "$*"; }
fail() { printf '%s drill: FAIL %s\n' "$(date -u +%FT%TZ)" "$*" >&2; FAILED=1; }
FAILED=0

ID="drill-$$-$(date +%s)"
NET="$ID-net"
PG="$ID-pg"
PGPASS="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
WORK="$(mktemp -d)"
cleanup() {
  docker rm -f "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

# ── 1. Fetch, verify, decrypt ────────────────────────────────────────────────
ARCHIVE="${1:-}"
if [[ -z "$ARCHIVE" ]]; then
  : "${BACKUP_RCLONE_REMOTE:?give an archive path or set BACKUP_RCLONE_REMOTE}"
  command -v rclone >/dev/null || { echo "drill: missing 'rclone'" >&2; exit 2; }
  newest="$(rclone lsf --include 'aicfo-*.tar.age' "$BACKUP_RCLONE_REMOTE/" | sort | tail -n1)"
  [[ -n "$newest" ]] || { echo "drill: no archives on $BACKUP_RCLONE_REMOTE" >&2; exit 1; }
  rclone copy --include "$newest" --include "$newest.sha256" "$BACKUP_RCLONE_REMOTE/" "$WORK/"
  ARCHIVE="$WORK/$newest"
fi
[[ -f "$ARCHIVE" ]] || { echo "drill: $ARCHIVE not found" >&2; exit 1; }
log "archive $(basename "$ARCHIVE")"

if [[ -f "$ARCHIVE.sha256" ]]; then
  (cd "$(dirname "$ARCHIVE")" && sha256sum -c "$(basename "$ARCHIVE").sha256") \
    || { echo "drill: archive checksum mismatch" >&2; exit 1; }
else
  log "no .sha256 beside the archive — skipping transport checksum"
fi

age -d -i "$AGE_IDENTITY_FILE" "$ARCHIVE" | tar -C "$WORK" -xf -
B="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d -name 'aicfo-*' | head -n1)"
[[ -n "$B" && -f "$B/MANIFEST" ]] || { echo "drill: archive has no MANIFEST" >&2; exit 1; }
(cd "$B" && grep -E '^[0-9a-f]{64}  ' MANIFEST | sha256sum -c --quiet) \
  || { echo "drill: contents do not match MANIFEST checksums" >&2; exit 1; }
log "decrypted; MANIFEST checksums match"

# ── 2. Empty Postgres, restore ───────────────────────────────────────────────
docker network create --internal "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" \
  -e POSTGRES_USER=aicfo -e POSTGRES_DB=aicfo -e POSTGRES_PASSWORD="$PGPASS" \
  pgvector/pgvector:pg16 >/dev/null
for _ in $(seq 1 60); do
  docker exec "$PG" pg_isready -U aicfo -d aicfo >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$PG" pg_isready -U aicfo -d aicfo >/dev/null || { echo "drill: postgres did not start" >&2; exit 1; }

docker exec -i "$PG" pg_restore -U aicfo -d aicfo --no-owner --exit-on-error < "$B/db.dump"
log "pg_restore ok"

psql_q() { docker exec "$PG" psql -U aicfo -d aicfo -At -F $'\t' -c "$1"; }

# ── 3. alembic current ───────────────────────────────────────────────────────
alembic_in_image() {
  docker run --rm --network "$NET" \
    -e USE_SQLITE=false -e POSTGRES_HOST="$PG" -e POSTGRES_PORT=5432 \
    -e POSTGRES_USER=aicfo -e POSTGRES_DB=aicfo -e POSTGRES_PASSWORD="$PGPASS" \
    -e REDIS_URL=redis://unused:6379/0 \
    "$BACKEND_IMAGE" alembic "$@"
}
expected_rev="$(tr -d '[:space:]' < "$B/alembic_version.txt")"
current_out="$(alembic_in_image current 2>&1)" || { echo "$current_out" >&2; fail "alembic current errored"; }
heads_out="$(alembic_in_image heads 2>&1)" || { echo "$heads_out" >&2; fail "alembic heads errored"; }
while IFS= read -r l; do echo "  alembic current: $l"; done <<<"$current_out"
if [[ -z "$expected_rev" ]]; then
  fail "backup recorded no alembic revision"
elif ! grep -q "$expected_rev" <<<"$current_out"; then
  fail "restored revision is not the backed-up one ($expected_rev)"
elif ! grep -q "$expected_rev" <<<"$heads_out"; then
  log "WARN restored revision $expected_rev is not a head of $BACKEND_IMAGE — the image is newer; 'alembic upgrade head' would run on restore"
else
  log "alembic current = $expected_rev (head of $BACKEND_IMAGE)"
fi

# ── 4. Row counts vs manifest ────────────────────────────────────────────────
psql_q "
  SELECT table_name,
         (xpath('/row/c/text()',
                query_to_xml(format('SELECT count(*) AS c FROM %I.%I',
                                    table_schema, table_name), false, true, '')))[1]::text
  FROM information_schema.tables
  WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
  ORDER BY table_name;" > "$WORK/restored_counts.tsv"

printf '  %-40s %12s %12s\n' table backed_up restored
drift=0
while IFS=$'\t' read -r table want; do
  got="$(awk -F'\t' -v t="$table" '$1==t {print $2}' "$WORK/restored_counts.tsv")"
  printf '  %-40s %12s %12s\n' "$table" "$want" "${got:-MISSING}"
  if [[ -z "$got" ]]; then
    fail "table $table missing after restore"
  elif [[ "$want" -gt 0 && "$got" -eq 0 ]]; then
    fail "table $table had $want rows, restored empty"
  elif [[ "$want" != "$got" ]]; then
    drift=$((drift + 1))
  fi
done < "$B/row_counts.tsv"
[[ "$drift" -eq 0 ]] || log "WARN $drift table(s) differ slightly — rows written between pg_dump and the count (see backup.sh)"

# ── 5. Uploads ───────────────────────────────────────────────────────────────
mkdir -p "$WORK/uploads-restore"
tar -C "$WORK/uploads-restore" -xzf "$B/uploads.tar.gz"
got_files="$(find "$WORK/uploads-restore" -type f | wc -l | tr -d ' ')"
want_files="$(tr -d '[:space:]' < "$B/uploads_file_count.txt")"
if [[ "$got_files" != "$want_files" ]]; then
  fail "uploads: $got_files files restored, manifest says $want_files"
else
  log "uploads: $got_files files"
fi

# ── 6. Golden path (structural) ──────────────────────────────────────────────
if command -v python3 >/dev/null; then
  python3 scripts/golden_path_check.py || fail "scripts/golden_path_check.py"
else
  fail "python3 not found — cannot run scripts/golden_path_check.py"
fi

if [[ "$FAILED" -ne 0 ]]; then
  log "RESULT: FAILED — do not rely on this backup"
  exit 1
fi
log "RESULT: OK — $(basename "$ARCHIVE") restores"
