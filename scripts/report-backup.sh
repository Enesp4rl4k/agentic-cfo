#!/usr/bin/env bash
# Tell the application how the backup went, so a failed or silent backup reaches the operators by e-mail.
#
#   scripts/report-backup.sh ok|failed "short detail"
#
# Call it last in the backup cron, whatever the outcome (for example `backup.sh && report-backup.sh ok ||
# report-backup.sh failed "backup.sh exit $?"`). It POSTs to /api/v1/platform/ops/backup-report with the
# shared secret OPS_REPORT_TOKEN. The application stores the time of the last success (operators see it
# on /api/v1/ready), mails the operators at once on `failed`, and mails them when no success arrives for
# BACKUP_MAX_AGE_HOURS. It needs OPS_REPORT_TOKEN to be set on the application too; without it the endpoint
# answers 404 and nothing is monitored.
#
# Environment: API_URL (default http://localhost:8000), OPS_REPORT_TOKEN.
set -euo pipefail

status="${1:-}"
detail="${2:-}"
case "$status" in
  ok) ok=true ;;
  failed) ok=false ;;
  *) echo "usage: $0 ok|failed [detail]" >&2; exit 2 ;;
esac
: "${OPS_REPORT_TOKEN:?OPS_REPORT_TOKEN is not set}"
api="${API_URL:-http://localhost:8000}"

# The detail is sent as JSON built by python, never spliced into a string by the shell.
payload="$(OK="$ok" DETAIL="$detail" python3 -c 'import json,os; print(json.dumps({"ok": os.environ["OK"]=="true", "detail": os.environ["DETAIL"][:200]}))')"
curl -fsS --max-time 20 -X POST "$api/api/v1/platform/ops/backup-report" \
  -H "Content-Type: application/json" -H "X-Ops-Token: $OPS_REPORT_TOKEN" -d "$payload" >/dev/null
echo "backup report sent: $status"
