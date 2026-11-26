#!/usr/bin/env bash
# Nightly backup for the single-VPS stack (docker-compose.prod.yml).
#
#   pg_dump (custom format) + uploads/ + manifest
#     → one tar → encrypted with age (public key only on the server)
#     → copied off-server with rclone → remote copies older than 14 days deleted.
#
# The age PRIVATE key never lives on this server: whoever takes the box gets
# ciphertext. Restoring needs the key from the owner's password manager
# (scripts/restore-drill.sh, docs/ops/runbook.md).
#
# Required env (read from the repo's .env when present, or the environment):
#   AGE_RECIPIENT          age public key, "age1…"
#   BACKUP_RCLONE_REMOTE   rclone destination, e.g. "trbackup:aicfo-backups"
# Optional:
#   BACKUP_RETENTION_DAYS  default 14
#   BACKUP_LOCAL_DIR       staging dir for the archive, default /var/backups/aicfo
#   BACKUP_KEEP_LOCAL      keep the newest N encrypted archives locally, default 2
#   COMPOSE_FILE           default docker-compose.prod.yml (several files: a:b)
#
# Every delete in this script is limited to its own archives: the remote
# `rclone delete` is filtered to 'aicfo-*.tar.age*' (and --min-age), the local
# prune is a depth-1 `find` for 'aicfo-*.tar.age' in BACKUP_LOCAL_DIR plus each
# archive's own .sha256, and the scratch dir is the script's own mktemp -d.
#
# On success it writes "$BACKUP_LOCAL_DIR/last-success" (UTC time, archive name)
# once the off-server copy is verified; monitoring can alert when that file is
# older than ~26 h (docs/ops/staging.md section 9).
#
# Cron (root or the deploy user, in the repo checkout):
#   15 2 * * * cd /opt/agentic-cfo && ./scripts/backup.sh >> /var/log/aicfo-backup.log 2>&1
#
# Exits non-zero on any failure — a backup that "mostly worked" is a failure.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f .env ]]; then
  # Only the keys this script needs — never `source` the whole file (values
  # are not shell-quoted and some contain spaces or $).
  for key in AGE_RECIPIENT BACKUP_RCLONE_REMOTE BACKUP_RETENTION_DAYS \
             BACKUP_LOCAL_DIR BACKUP_KEEP_LOCAL POSTGRES_USER POSTGRES_DB; do
    if [[ -z "${!key:-}" ]]; then
      line="$(grep -E "^${key}=" .env | tail -n1 | tr -d '\r' || true)"
      [[ -n "$line" ]] && export "$key=${line#*=}"
    fi
  done
fi

: "${AGE_RECIPIENT:?AGE_RECIPIENT (age public key) is not set}"
: "${BACKUP_RCLONE_REMOTE:?BACKUP_RCLONE_REMOTE (rclone remote:path) is not set}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
LOCAL_DIR="${BACKUP_LOCAL_DIR:-/var/backups/aicfo}"
KEEP_LOCAL="${BACKUP_KEEP_LOCAL:-2}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
PGUSER_="${POSTGRES_USER:-aicfo}"
PGDB_="${POSTGRES_DB:-aicfo}"

[[ "$AGE_RECIPIENT" == age1* ]] || { echo "backup: AGE_RECIPIENT must be an age PUBLIC key (age1...)" >&2; exit 2; }
[[ "$BACKUP_RCLONE_REMOTE" == *:* ]] || { echo "backup: BACKUP_RCLONE_REMOTE must be remote:path" >&2; exit 2; }
[[ "$RETENTION_DAYS" =~ ^[0-9]+$ && "$RETENTION_DAYS" -ge 1 ]] || { echo "backup: BACKUP_RETENTION_DAYS must be a whole number >= 1" >&2; exit 2; }
[[ "$KEEP_LOCAL" =~ ^[0-9]+$ && "$KEEP_LOCAL" -ge 1 ]] || { echo "backup: BACKUP_KEEP_LOCAL must be a whole number >= 1" >&2; exit 2; }

for bin in docker age rclone sha256sum tar flock; do
  command -v "$bin" >/dev/null || { echo "backup: missing '$bin'" >&2; exit 2; }
done

export COMPOSE_FILE   # may name several files (a:b), which docker compose reads itself
dc() { docker compose "$@"; }
log() { printf '%s backup: %s\n' "$(date -u +%FT%TZ)" "$*"; }

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="aicfo-${STAMP}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/$NAME" "$LOCAL_DIR"
chmod 700 "$WORK" "$LOCAL_DIR"

# One run at a time: an overlapping cron run would race on the same files.
exec 9>"$LOCAL_DIR/.backup.lock"
flock -n 9 || { echo "backup: another run holds the lock" >&2; exit 1; }

log "start $NAME"

# 1. Database. Custom format: compressed, and pg_restore can pick tables.
#    One pg_dump = one consistent snapshot of every table.
dc exec -T postgres pg_dump -U "$PGUSER_" -d "$PGDB_" -Fc --no-owner \
  > "$WORK/$NAME/db.dump"
[[ -s "$WORK/$NAME/db.dump" ]] || { log "pg_dump produced an empty file"; exit 1; }

# 2. Manifest the restore drill checks against. Row counts are taken right
#    after the dump, so a table written during the dump window can differ by
#    a few rows; the drill reports those, and fails only on a table that had
#    rows and came back empty or missing.
dc exec -T postgres psql -U "$PGUSER_" -d "$PGDB_" -At -F $'\t' -c "
  SELECT table_name,
         (xpath('/row/c/text()',
                query_to_xml(format('SELECT count(*) AS c FROM %I.%I',
                                    table_schema, table_name), false, true, '')))[1]::text
  FROM information_schema.tables
  WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
  ORDER BY table_name;" > "$WORK/$NAME/row_counts.tsv"

dc exec -T postgres psql -U "$PGUSER_" -d "$PGDB_" -At \
  -c "SELECT version_num FROM alembic_version;" > "$WORK/$NAME/alembic_version.txt"

# 3. Uploads (the user's original files — the database points at them).
dc exec -T backend tar -C /app -czf - uploads > "$WORK/$NAME/uploads.tar.gz"
tar -tzf "$WORK/$NAME/uploads.tar.gz" > "$WORK/uploads.list"   # fails loudly on a corrupt archive
grep -vc '/$' "$WORK/uploads.list" > "$WORK/$NAME/uploads_file_count.txt" || true   # grep -c exits 1 on a count of 0

{
  echo "name=$NAME"
  echo "created_utc=$STAMP"
  echo "git_sha=$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "host=$(hostname)"
  (cd "$WORK/$NAME" && sha256sum db.dump uploads.tar.gz row_counts.tsv alembic_version.txt)
} > "$WORK/$NAME/MANIFEST"

# 4. Encrypt. Plaintext only ever exists in $WORK (removed on exit).
ARCHIVE="$LOCAL_DIR/$NAME.tar.age"
tar -C "$WORK" -cf - "$NAME" | age -r "$AGE_RECIPIENT" -o "$ARCHIVE"
(cd "$LOCAL_DIR" && sha256sum "$NAME.tar.age" > "$NAME.tar.age.sha256")
log "encrypted $(du -h "$ARCHIVE" | cut -f1) → $ARCHIVE"

# 5. Off-server copy, then verify it arrived intact.
rclone copy "$ARCHIVE" "$BACKUP_RCLONE_REMOTE/"
rclone copy "$ARCHIVE.sha256" "$BACKUP_RCLONE_REMOTE/"
rclone check --one-way --include "$NAME.tar.age" "$LOCAL_DIR" "$BACKUP_RCLONE_REMOTE/"
log "uploaded to $BACKUP_RCLONE_REMOTE"

# Success marker: written only after the off-server copy is verified.
printf '%s %s
' "$(date -u +%FT%TZ)" "$NAME" > "$LOCAL_DIR/last-success.tmp"
mv -f -- "$LOCAL_DIR/last-success.tmp" "$LOCAL_DIR/last-success"

# 6. Retention: remote keeps RETENTION_DAYS, local keeps the newest KEEP_LOCAL.
rclone delete --min-age "${RETENTION_DAYS}d" --include 'aicfo-*.tar.age*' "$BACKUP_RCLONE_REMOTE/"
mapfile -t old < <(find "$LOCAL_DIR" -maxdepth 1 -name 'aicfo-*.tar.age' -printf '%T@ %p\n' \
  | sort -rn | tail -n +"$((KEEP_LOCAL + 1))" | cut -d' ' -f2-)
if (( ${#old[@]} )); then
  for f in "${old[@]}"; do rm -f -- "$f" "$f.sha256"; done
fi

log "done $NAME"
