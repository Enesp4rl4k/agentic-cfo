# An upload is stuck, held or failed

Code: `api/upload.py`, `worker.py`, `services/job_reaper.py`, `api/analysis.py`, `api/held_rows.py`.

Statuses of `analysis_jobs.status`: `pending`, `ingesting`, `analyzing`, `awaiting_review`, `completed`, `failed`.

First separate **held** from **stuck**:

- **Held** (`awaiting_review`, or rows held as questions) is the product waiting for a *person*: a currency,
  rows that cannot be read, a failed reconciliation, a possible duplicate. Nothing is broken. The company's
  owner, admin, cfo or accountant answers it in the app (`/analyses/held`, `/held-rows`). Tell them which job.
- **Stuck** (`pending`, `ingesting` or `analyzing` for too long) is a worker problem.

## Check

```bash
curl -s https://<API_DOMAIN>/api/v1/ready          # checks.worker, checks.redis
dc ps worker worker-maintenance
dc logs --tail=200 worker
dc exec redis redis-cli ZCARD arq:queue:analysis    # queued, not yet taken
psql_app -c "select id, status, filename, created_at, locked_by, lease_expires_at, left(error_message, 120)
             from analysis_jobs where org_id = '<org id>' order by created_at desc limit 5;"
```

- Queue grows and `worker` is down or restarting: `dc restart worker`; read the log for the crash.
- `worker` up, job in `analyzing` past `lease_expires_at`: the reaper (every 10 minutes, `REAPER_ENABLED`)
  marks it `failed` and notifies the user; a job nobody enqueued has no lease and is never touched.
- `pending` with no lease: the upload was accepted but not enqueued (Redis was unreachable at that moment).
- `failed` with an `error_message`: the message is the reason shown to the user.
- An LLM outage does not block a run: numbers do not need it; chat and narrative answer 503.

## Fix

- Failed or never-started: the user re-runs it from the app (`POST /analysis/{job_id}/rerun`, writer role),
  or you do so as that user. The original file is on the volume (`/app/uploads/uploads/<job id>/document.<ext>`);
  nothing is lost.
- Unreadable file: ask for the original export. `.xls` is refused by design (re-save as `.xlsx`).
- Never delete rows from `analysis_jobs` by hand: ledger rows and decisions hang off them.

## Not verified

The worker has never run on a real host. The queue key names are the defaults (`ARQ_ANALYSIS_QUEUE_NAME`).
