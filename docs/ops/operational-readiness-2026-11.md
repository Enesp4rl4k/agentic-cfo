# Operational readiness audit, November 2026

Scope: the application as of `origin/master` (f22f25e) plus this PR, for three pilot companies on one VPS
behind a reverse proxy. Method: reading the code, config, compose files, workflows and the open PRs
(#96 staging stack, #133, #68 KVKK set); targeted backend tests; no stack was started and no host was
contacted. Anything that needs a running server is marked UNKNOWN, not guessed.

Ratings: **READY** (evidence in the row), **GAP** (a concrete shortfall; "blocker" means do not invite the
first company before it is closed or consciously accepted), **UNKNOWN** (cannot be shown from here).
"PR" in the evidence column means fixed by this PR; the row says what it was before.

<!-- summary -->
## Summary

| Area | READY | GAP | of which blocker | UNKNOWN |
|---|---|---|---|---|
| 1. Configuration | 10 | 2 | 0 | 1 |
| 2. Startup safety | 2 | 2 | 0 | 0 |
| 3. Database | 2 | 2 | 0 | 2 |
| 4. Backups and restore | 1 | 3 | 1 | 1 |
| 5. Health, readiness, observability | 2 | 5 | 1 | 0 |
| 6. Background work | 3 | 3 | 0 | 1 |
| 7. Outbox and e-mail | 2 | 2 | 0 | 1 |
| 8. Security posture for go-live | 7 | 6 | 0 | 0 |
| 9. Data lifecycle and KVKK operations | 1 | 6 | 0 | 0 |
| 10. Deploy and rollback (PR #96 assessed) | 3 | 2 | 0 | 1 |
| **Total** | **33** | **33** | **2** | **7** |

Areas 11 and 12 are documents, not findings: the runbooks and the checklist exist; none has been run on a host.
<!-- /summary -->


Related pages: [configuration.md](configuration.md) (every variable) · [pilot-acceptance-checklist.md](pilot-acceptance-checklist.md) ·
[runbooks/](runbooks/) · [mail.md](mail.md) · [auth-abuse-and-outbound.md](auth-abuse-and-outbound.md).

## 1. Configuration

| # | Rating | Finding | Evidence |
|---|---|---|---|
| 1.1 | READY | One authoritative table of all 137 settings and the process-environment variables; `.env.example` matches the code in both directions. Before: 25 variables documented that no code reads, 70 read but undocumented. | PR: `docs/ops/configuration.md`, `tests/test_configuration_docs.py` |
| 1.2 | READY | Insecure secrets are refused in production: the old list missed the template value of `.env.example` (38 characters). Placeholder markers and a 32-character floor added; the same for `NEXTAUTH_SECRET` when a shared `.env` carries it and for a `changeme` database password. | `config.py:424-437`; PR `core/preflight.py` `_secret_findings` |
| 1.3 | READY | `USE_SQLITE` defaults to `true`, so a deployment that forgets it ran as development. Now `APP_ENV` is REQUIRED whenever the database is Postgres (FATAL `app_env_missing` / `app_env_unknown`, naming the allowed values), so a host cannot run in "warnings only" mode by omission. The demo compose sets `APP_ENV: demo` (this PR, PR #139); Kubernetes and Helm set `production`. **Still to set: `APP_ENV: production` in `docker-compose.prod.yml` of #96** (the stack refuses to start without it). | `core/preflight.py` `_env_findings`, `tests/test_operator_ops.py` |
| 1.4 | READY | Verification required with no mail sender: logged at ERROR and warned at startup, not fatal by design (config.py:452-466). | config.py; see 7.4 for what the user sees |
| 1.5 | READY | `TRUSTED_PROXY_*`: static WARN at startup (PR) plus the runtime warning when only private peers are seen. | `core/client_ip.py:80-109`; PR preflight `no_trusted_proxy` |
| 1.6 | READY | `SUPPORT_CONTACT`, `PLATFORM_OPERATOR_EMAILS`, LLM key, SMTP, Sentry, field-encryption key: WARN with the consequence named. | PR preflight `_degraded_findings` |
| 1.7 | READY | Wildcard CORS with credentials is fatal. Demo mode and localhost e-mail links (`FRONTEND_URL`, `BRAND_APP_URL`) are fatal under `APP_ENV=production\|staging` and warnings with Postgres alone (the demo compose stack and a developer's compose run that way). | PR preflight `_exposure_findings`, `tests/test_preflight.py` |
| 1.8 | READY | No debug flag exists (`LOG_LEVEL=DEBUG` warns). | grep of `app/` |
| 1.9 | GAP | No allowed-hosts middleware; the API answers any `Host`. Low risk behind Caddy that routes two names. | `main.py` |
| 1.10 | READY | Error tracking: `init_sentry` read `settings.sentry_dsn`, a field `Settings` does not have, so `SENTRY_DSN` was ignored and error tracking was never on. It now reads the process environment. | PR `services/sentry_monitoring.py`, `tests/test_log_redaction_and_headers.py` |
| 1.11 | READY | **Registration is closed (FIXED, PR #139).** `REGISTRATION_MODE` (`open` / `invite_only` default / `closed`) is enforced by `POST /auth/register`, SSO sign-up and `POST /org/create`: without an invitation nothing is created, for any address alike (403). One supported way in: operator issues a pilot invite to an e-mail address and company name, the invitee registers through it and becomes owner of a new company, then invites the team ([onboard-company.md](runbooks/onboard-company.md)). The dead `PILOT_*` names are removed everywhere (code, `.env.example`, Kubernetes, Helm). | `services/registration.py`, `services/pilot_invites.py`, `api/auth.py`, `api/pilot.py`, `api/org.py`, `services/sso.py`, `tests/test_pilot_onboarding.py` |
| 1.12 | GAP | Connector secrets use `FIELD_ENCRYPTION_KEY`, or, when empty, a key derived from `BACKEND_SECRET_KEY` (`connectors/crypto.py:22-26`). Rotating the JWT secret then loses every stored connector secret. Not required today (WARN only). Set the key before the first connector. | `connectors/crypto.py`, runbook `rotate-secret.md` |
| 1.13 | UNKNOWN | NextAuth cookie flags (`Secure`, `HttpOnly`, `SameSite`) in the browser. The backend sets no cookies (bearer JWT, 30-minute access token). | `services/auth.py:25`; check once on staging |

## 2. Startup safety

| # | Rating | Finding | Evidence |
|---|---|---|---|
| 2.1 | READY | Production preflight with FATAL and WARN rules; fatal findings exit 1 naming every cause; outside production they only warn. Run by **both** the API (`main.py`) and the ARQ worker (`worker.py`) through `enforce_or_exit`. | `core/preflight.py`, `tests/test_operator_ops.py`, 42 tests in `tests/test_preflight.py` |
| 2.2 | READY | The schema is compared with the code's single head: `python -m app.core.preflight --db` (exit 1 on behind/ahead/unknown) and `/api/v1/ready`. Proved on real Postgres: restore, one migration down (refused), back up (accepted). | PR `scripts/restore-roundtrip.sh`, the `Migrations on Postgres` job in `ci.yml` |
| 2.3 | GAP | The API does not refuse to boot on a stale schema (it reports 503 on `/ready` instead). The staging stack's `migrate` one-shot gates startup, so on that stack the order is enforced by compose. Putting the check in the lifespan would touch the lines #96 and #133 change in `main.py`. | follow-up after those merge |
| 2.4 | GAP | `/docs`, `/redoc` and `/openapi.json` are public in production (route list, no data). | `api/access.py` `PUBLIC_ROUTES`; hide at Caddy or set `docs_url=None` |

## 3. Database

| # | Rating | Finding | Evidence |
|---|---|---|---|
| 3.1 | READY | One head (`074_materiality_smmm_brief`); CI applies the chain from empty, checks models against migrations, downgrades to base and upgrades again on Postgres. | `ci.yml` job "Migrations on Postgres"; `tests/test_preflight.py::test_the_real_migrations_have_one_head` |
| 3.2 | READY | No destructive upgrade: no migration drops a column or table in its `upgrade()` (script over `backend/alembic/versions`, 74 files); every migration has a `downgrade()`. | audit script, CI full-rollback step |
| 3.3 | GAP | The procedure "who runs `alembic upgrade`, when, with what backup first" lives in #96's `runbook.md` (backup, then `migrate` one-shot). It is not yet on master. Kubernetes uses a pre-upgrade hook job (`k8s/05-migration-job.yaml`) with no backup step. | #96 `docs/ops/runbook.md` §1; runbook `deploy-and-rollback.md` |
| 3.4 | GAP | Pool and timeouts: pool 20+10 per process with `pool_pre_ping`, `pool_recycle=1800` (`database.py:55-62`); no `statement_timeout`, `lock_timeout` or connect timeout. One stuck query holds a connection until the worker's job timeout (600 s). Postgres `max_connections=200` in #96 covers the arithmetic (config.py:334-340). | `database.py`, `config.py` |
| 3.5 | UNKNOWN | Indices for the pilot flow (upload, ledger, radar, briefing). The models declare per-table indexes (e.g. `ix_outbox_messages_status_created`); there is no query-plan evidence at pilot volume, and the Load Baseline job only calls `/system/ops` (`scripts/load-baseline.sh`), not the pilot path. | `ci.yml` `load-baseline` |
| 3.6 | UNKNOWN | Long transactions or locks in the worker. `deliver_pending` locks rows with `SKIP LOCKED` (`services/outbox.py`); other jobs were not profiled. | needs a pilot-volume run with `pg_stat_activity` |

## 4. Backups and restore

| # | Rating | Finding | Evidence |
|---|---|---|---|
| 4.1 | GAP, **blocker** | On master there is no backup job or script at all. #96 adds `scripts/backup.sh` (pg_dump -Fc + uploads, age-encrypted, rclone off-host, 14-day retention, nonzero on any failure) and `scripts/restore-drill.sh`. Not yet merged, never run on a real host, and no backup destination exists (owner decision D3). | #96 `scripts/`, `docs/ops/staging.md` §3-4 |
| 4.2 | READY | Restore procedure proven mechanically on every PR and push (a step of the `Migrations on Postgres` job): dump, restore into a fresh database, all tables and files identical, schema preflight, migrate down/up, API smoke test. | PR `.github/workflows/ci.yml` (job `migrations-postgres`), `scripts/restore-roundtrip.sh` |
| 4.3 | GAP | Uploads live on one volume (`uploads_data` at `/app/uploads`: uploads, reports, board decks, all under `STORAGE_LOCAL_PATH`). `/app/data` (boardroom memory, created in the Dockerfile) and the LangGraph SQLite checkpoint are in the container filesystem: not on a volume, not in the backup. Both are recomputable, but say so. | `backend/Dockerfile:46`, #96 compose volumes |
| 4.4 | GAP | The app side is ready (PR #139): the backup cron calls `scripts/report-backup.sh ok|failed` (`POST /platform/ops/backup-report`, header `X-Ops-Token` = `OPS_REPORT_TOKEN`); a failure mails the operators at once, no success for `BACKUP_MAX_AGE_HOURS` mails them, and `/ready` (operators) shows the last success. **Still to do: call the script at the end of `backup.sh`'s cron line (#96 / owner) and set `OPS_REPORT_TOKEN`.** | `api/ops.py`, `services/ops_watch.py`, `scripts/report-backup.sh` |
| 4.5 | UNKNOWN | Whether the encrypted archive restores with the owner's real key: needs the first real drill on the host (#96 `staging.md` step 11). | - |

## 5. Health, readiness, observability

| # | Rating | Finding | Evidence |
|---|---|---|---|
| 5.1 | READY | Liveness `/health`; readiness `/api/v1/ready`: required checks answer 503, advisory checks `degraded` with 200, no exception text. **Anonymous callers now get only `status` and `ok/degraded/fail/skipped` per check (PR #139); the migration revision, outbox counts, worker state and the last backup report are for platform operators (their bearer token).** | `api/ops.py`, `tests/test_operator_ops.py` |
| 5.2 | GAP | Worker heartbeat precision: ARQ writes its health key every 3600 s by default, so a dead worker shows as alive for up to an hour. Set `health_check_interval = 30` in both `WorkerSettings` (one line; `worker.py` is in #96/#133). | `worker.py:1114`, arq 0.28 default |
| 5.3 | GAP | The scheduler cannot be asked directly. `/ready` infers it from the outbox pass heartbeat (PR `core/heartbeat.py`, every five minutes). A scheduler that runs everything except the outbox pass would go unseen. | PR |
| 5.4 | READY | Logs: e-mail addresses, IBANs, bearer tokens and `key=value` secrets are masked in both formats; nine call sites logged addresses (`auth.py:381`, `org.py:283,442,514,707,836`, ...). | PR `core/log_redaction.py`, `services/telemetry.py` |
| 5.5 | GAP | No request ID in logs or responses; no metrics endpoint (no Prometheus client in `requirements.txt`). Sentry is wired but needs a DSN (decision D5). | grep |
| 5.6 | GAP, **blocker** | **App side ready (PR #139), blocker stays open until a deliberate test alert reaches the owner.** One hook (`services/operator_alerts.py`): an `operator_alert` immediate outbox row to `PLATFORM_OPERATOR_EMAILS`, de-duplicated per cool-down window, fired on: a scheduled job failed N times, a destination with repeated failed outbox rows, a caught-up missed briefing, startup preflight warnings, a failed backup report, a stale backup report. **Not delivered:** "readiness degraded for longer than M minutes" (the application cannot report that it is down: the external uptime monitor on `/api/v1/ready`, decision D4, covers it). | `services/ops_watch.py`, `tests/test_operator_ops.py` |
| 5.7 | GAP | Failed-login spikes: login is limited to 5/minute per client (`middleware/rate_limit.py`, Redis-backed) and audited; nothing counts or alerts. | `rate_limit.py` |

## 6. Background work

| # | Rating | Finding | Evidence |
|---|---|---|---|
| 6.1 | READY | Every cron is wrapped in `_exclusive` (Redis NX lock) and the company-level jobs are idempotent through the run ledger (6.3). #96 additionally moves APScheduler into the `worker` container only (`SCHEDULER_PROCESS`, defined in #96; this PR relies on it and defines nothing of its own). | `scheduler.py`, `models/job_run.py`, `models/outbox_message.py:40` |
| 6.2 | GAP | `_exclusive` fails open: with Redis down every process runs the job (`scheduler.py:64-66`). Duplicates of idempotent jobs are harmless; a non-idempotent job would double. No test pins the claim "every scheduled job is idempotent". | `scheduler.py` |
| 6.3 | READY | **Missed scheduled runs are caught up, once (FIXED, PR #139).** A ledger (`scheduled_job_runs`, unique per job, company and period) is claimed before the work and finished in the same transaction as it; a catch-up job runs after start and every 10 minutes for the Monday briefing (and morning brief) until the end of that UTC day, the nightly run until 12:00, the hourly KRI scan only within its hour. A second scheduler, a repeated start or a crash in the middle cannot lose or repeat a briefing (outbox keys as a second guard). Every job also has a deliberate `misfire_grace_time`, `coalesce` and `max_instances`. | `services/schedule_runner.py`, `services/job_runs.py`, `scheduler.py`, `tests/test_schedule_catchup.py` |
| 6.4 | READY | Retries: analysis jobs `max_tries=2`, `job_timeout` 600 s (maintenance 1200 s); outbox 5 attempts then `failed` with the reason; stuck jobs are failed by a lease reaper every 10 minutes; the user can re-run. | `worker.py:1114-1144`; `services/outbox.py:57,359`; `services/job_reaper.py` |
| 6.5 | GAP | Graceful shutdown: arq's `job_completion_wait` defaults to 0, so SIGTERM cancels in-flight jobs at once (they are retried, `retry_jobs=True`) and compose gives 10 s before SIGKILL. Add `job_completion_wait = 60` and `stop_grace_period: 90s`. | arq 0.28 `worker.py:202`, `worker.py:1114` |
| 6.6 | GAP | An operator can see failed outbox rows (`/notifications/delivery-status`, per organisation) and stuck jobs only through logs and the database; there is no operator view or retry endpoint. Runbooks give SQL. | `api/notifications.py:290` |
| 6.7 | UNKNOWN | Two scheduler instances were never run together against a real Redis and Postgres. | - |

## 7. Outbox and e-mail

| # | Rating | Finding | Evidence |
|---|---|---|---|
| 7.1 | READY | One sender (`outbox_transport.py`); statuses pending, sent, failed, held; unique idempotency key; rows locked while sending; attempt counter; failure reason stored; transactional bodies scrubbed after delivery; a failing channel notifies once per outage. | `services/outbox.py`, `models/outbox_message.py` |
| 7.2 | GAP | Retry policy is "every five minutes up to 5 attempts", no backoff; a permanently failing channel is retried five times. Acceptable at pilot volume. | `services/outbox.py:57,359` |
| 7.3 | GAP | No bounce or complaint handling: SMTP accepts the message and the outbox says `sent`; a later bounce is invisible. SPF, DKIM and DMARC are the mitigation; docs only (`mail.md`). | `outbox_transport.py` |
| 7.4 | READY | **No-SMTP honesty (FIXED, PR #139).** Every mail-dependent answer carries `mail_delivery` (`live` / `dev_recorded` / `not_configured`) and a notice; an organisation or pilot invitation that cannot be sent is refused (503 "davet iletilemedi") and not created; in production the preflight makes "invite-only registration or required verification with no sender" FATAL. | `services/mail_capability.py`, `core/preflight.py` `_mail_findings`, `tests/test_pilot_onboarding.py` |
| 7.5 | UNKNOWN | Domain, SPF/DKIM/DMARC records, sending provider and rate limits depend on decision D2. | `mail.md` |

## 8. Security posture for go-live

| # | Rating | Finding | Evidence |
|---|---|---|---|
| 8.1 | READY | TLS and HSTS at Caddy (Let's Encrypt automatic); HSTS also from the app. | #96 `deploy/Caddyfile`, `middleware/security_headers.py` |
| 8.2 | READY | API headers: nosniff, `X-Frame-Options: DENY`, Referrer-Policy, Permissions-Policy, COOP, and now a CSP (`default-src 'none'; frame-ancestors 'none'`, docs pages exempt). The docstring had promised a CSP that was never set. | PR `middleware/security_headers.py` |
| 8.3 | GAP | Frontend: nosniff, `X-Frame-Options`, Referrer-Policy, Permissions-Policy; **no CSP and no HSTS** from Next (Caddy adds HSTS). A CSP for a Next app needs nonces; not an ops change. | `frontend/next.config.mjs:25-45` |
| 8.4 | READY | CORS: explicit origins, credentials, preflight answered before the rate limiter; wildcard refused at startup. | `main.py`, PR preflight |
| 8.5 | READY | Uploads: extension allow-list, 10 MB streamed limit, magic bytes, `.xml` DTD/ENTITY refusal, Caddy 12 MB body cap. | `services/upload_service.py:115`, `services/ingest/ekle.py:115`, `core/xml_safety.py` |
| 8.6 | GAP | No antivirus, no zip-bomb limit on `.xlsx` (a zip) and no page or size limit on PDFs. The 10 MB cap bounds the compressed size only. | grep of `parsers/`, `services/ingest/` |
| 8.7 | GAP | Request timeouts: Caddy sets none, uvicorn defaults; slow-client handling is untested. | `deploy/Caddyfile` |
| 8.8 | READY | Rate limits per route class (login 5/min, register 5/min, reset 10/h, upload 10/min, chat 30/min, default 120/min), Redis-backed with an in-process fallback. The module docstring still says in-memory. | `middleware/rate_limit.py:46-72` |
| 8.9 | READY | Every route authenticates or is in `PUBLIC_ROUTES` with a reason; every state-changing route has an authorisation class; platform routes require `PLATFORM_OPERATOR_EMAILS`. | `tests/test_route_access.py`, `test_route_authorisation.py`, `api/access.py` |
| 8.10 | GAP | No dependency audit job (pip-audit, npm audit) and no Dependabot configuration. | `.github/` |
| 8.11 | READY | Backend container runs as uid 1001; the image copies only `app/`, `alembic/`, `alembic.ini` (no SQLite files, no `.env`); frontend runs as `nextjs`. Secrets are runtime env, not build args. | `backend/Dockerfile:30-48`, `frontend/Dockerfile:54` |
| 8.12 | GAP | The application connects as the Postgres superuser (`POSTGRES_USER` creates the role that owns everything; #96 compose). Migrations need DDL rights, the API and workers do not. A second role (DML only) needs a migration step and `DATABASE_URL_OVERRIDE`. Redis has no password (internal network only). | #96 `docker-compose.prod.yml` |
| 8.13 | GAP | Kubernetes manifests: `image: ...:latest`, no `securityContext`, probes on the liveness path. Not the pilot host; fix before anyone uses them. | `k8s/20-backend.yaml:20,40-50` |

## 9. Data lifecycle and KVKK operations

| # | Rating | Finding | Evidence |
|---|---|---|---|
| 9.1 | READY | Organisation erasure: two steps (request, then the owner types a phrase); scope computed from the schema so a new table is erased unless classified; one transaction; files removed; hash-chained proof record; tests fail on an unclassified table. Owner or admin may request, owner confirms. | `services/org_erasure.py`, `api/org_erasure.py`, `tests/test_org_erasure.py` |
| 9.2 | GAP | `anonymise` keeps the books and the audit log (11 tables); `hard_delete` is off until the retention question (plan G19) is answered. The owner and a lawyer must decide before an erasure request arrives. | `config.py:262-264`, `services/org_erasure.py` docstring |
| 9.3 | GAP | Export: only a per-user personal-data export (`/compliance/data-export`). No export of a company's whole dataset. | `api/compliance_gdpr.py:146` |
| 9.4 | GAP | Retention: no automatic deletion for any table; uploads stay forever; outbox bodies of briefings stay (only transactional bodies are scrubbed); `RETENTION_POLICY` is a report, not a job. PR #68 says the same. | `api/compliance_gdpr.py:41,247`; #68 `veri-envanteri.md` §1 |
| 9.5 | GAP | Mismatch with PR #68: 64 tables exist; the inventory has table rows for 33. Not listed as rows: `outbox_messages` (recipient e-mail and body), `password_reset_tokens`, `email_verification_tokens`, `journal_entries`, `journal_lines`, `decisions`, `held_transactions`, `counterparty_aliases`, `direction_mappings`, `org_erasure_requests`, `org_erasure_records`, `agent_jobs`, `agent_runs`, `proactive_alerts`, `alert_history`, `in_app_notifications` and 15 more. Nothing in the inventory is for a table that no longer exists. | script over `Base.metadata` and #68 `veri-envanteri.md` |
| 9.6 | GAP | Audit chain: the erasure records are hash-chained and verifiable (`verify_chain`); the audit log is retained but nothing verifies it periodically. | `services/org_erasure.py:326` |
| 9.7 | GAP | Prompts reach the LLM provider unmasked, and the default provider is DeepSeek (PR #68 §1, `config.py:280`). A KVKK matter for the owner and a lawyer, not ops: D6. | #68 |

## 10. Deploy and rollback (PR #96 assessed)

| # | Rating | Finding | Evidence |
|---|---|---|---|
| 10.1 | READY | The compose stack is coherent with the code: only Caddy publishes ports; Postgres and Redis on an internal network; `migrate` one-shot gates the API; crons only in the worker (`SCHEDULER_PROCESS`); inline fallback off; images tagged by commit; log rotation; Turkish documentation of install, deploy, rollback, backup, drill, incident. | #96 `docker-compose.prod.yml`, `docs/ops/` |
| 10.2 | READY | Rollback is documented including the migration case (downgrade with the new image first, then switch the tag) and the irreversible case (restore the pre-deploy backup). | #96 `runbook.md` §2 |
| 10.3 | GAP | Gaps in #96 itself: no `APP_ENV`; `/health` (liveness) is the only healthcheck; no worker healthcheck; no `stop_grace_period`; `NEXT_PUBLIC_LEGACY_DASHBOARDS` and the `NEXT_PUBLIC_BRAND_*` strings are not build args (legacy stays off because the default is not `true`; the brand falls back to its defaults); images are built on the VPS (needs disk and, for `next/font`, a reachable Google Fonts); its `.env` step still lists `PILOT_*`. | #96 compose and `staging.md` §4.5 |
| 10.4 | READY | Smoke test after deploy and restore: `scripts/smoke-test.sh --api ... --app ... --expect-commit <sha>`; `/api/v1/version` shows the commit (`GIT_SHA` build arg, or `IMAGE_TAG` from the compose `.env`). | PR |
| 10.5 | GAP | Downtime: `up -d` recreates containers, so a deploy is a short outage, not zero-downtime. Acceptable for three companies; deploy outside working hours. | #96 `runbook.md` §1 |
| 10.6 | UNKNOWN | Nothing in #96 has run on a real host (its own §5 says so). | #96 `staging.md` §5 |

## 11. Runbooks

[runbooks/](runbooks/) holds eleven short pages from the code's behaviour: login and e-mail, stuck or held
upload, briefing not sent, wrong number, IP allow-list lock-out, disk full, database restore, rotate a
secret, platform operators, onboarding a company, offboarding and erasure. Each marks what could not be
verified. Plus [deploy-and-rollback](runbooks/deploy-and-rollback.md). Rating: READY for existence, UNKNOWN
for execution (none has been run on a host).

## 12. Pilot acceptance

[pilot-acceptance-checklist.md](pilot-acceptance-checklist.md): one page, each line linked to its evidence.

## Owner decisions

| # | Decision | Recommended default | Configuration it needs |
|---|---|---|---|
| D1 | Who may register | **Decided 2026-11-23 and implemented (PR #139):** closed for the pilot, invitation only | `REGISTRATION_MODE=invite_only` (default) |
| D2 | Mail provider and domain | A transactional provider with a Turkish or EU region and DKIM on `notification_from`'s domain | `SMTP_HOST/PORT/USER/PASSWORD`, `NOTIFICATION_FROM`, DNS per `mail.md` |
| D3 | Backup destination | S3-compatible object storage in Turkey, separate from the VPS provider | `AGE_RECIPIENT`, `BACKUP_RCLONE_REMOTE`, `BACKUP_RETENTION_DAYS=14` |
| D4 | Alert channel | An uptime monitor on `/api/v1/ready` and a heartbeat ping at the end of `backup.sh`, notifying the owner by e-mail and phone | the monitor's URL and ping URL |
| D5 | Error tracking | Sentry (EU region) only after a KVKK check; otherwise leave unset and read container logs | `SENTRY_DSN`, `SENTRY_ENVIRONMENT` |
| D6 | LLM provider | Decide with a lawyer before real company data goes in; the numbers do not need an LLM | `OPENAI_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` |
| D7 | Erasure retention (G19) | Keep `anonymise` as the only mode | `ORG_ERASURE_HARD_DELETE_ENABLED=false` |
| D8 | Hosting provider, domain names | Chosen by the owner; unblocks D2 and D3 | `APP_DOMAIN`, `API_DOMAIN`, `ACME_EMAIL` |

## What this PR changed

Production preflight (`app/core/preflight.py`, 39 tests); `/api/v1/ready` and `/api/v1/version`
(`app/api/ops.py`, 14 tests); outbox-pass heartbeat; log redaction; API CSP; Sentry reads its DSN from the
environment; `/system/health` no longer returns driver error text; `.env.example` and
`docs/ops/configuration.md` matched to the code with a test; `scripts/smoke-test.sh`;
`scripts/restore-roundtrip.sh` run by CI in the `Migrations on Postgres` job; build args for `GIT_SHA` and
`BUILD_TIME`; this audit, the runbooks and the checklist.

## Pilot blockers: status after PR #139

| Blocker | Status |
|---|---|
| 1. Registration is open (1.11) | **FIXED**, PR #139 |
| 2. Monday briefing lost on a restart (6.3) | **FIXED**, PR #139 (ledger, catch-up, deliberate misfire settings) |
| 3. "Check your e-mail" with no SMTP (7.4) | **FIXED**, PR #139 |
| 4. Review follow-ups of #136 | **FIXED**, PR #139: worker runs the preflight, `APP_ENV` required with Postgres, `/ready` trimmed for anonymous callers, Sentry scrubbed and off without a DSN |
| 5. Alerting and backups (5.6, 4.1) | **Open**: the app side is ready (alert hook, backup report endpoint); the hosting-dependent parts are not (a backup destination, the cron line, an alert channel test, `APP_ENV=production` in the #96 compose) |

## Not done on purpose (files of open PRs)

After #96 and #133 merge: `health_check_interval = 30`, `job_completion_wait = 60` in `WorkerSettings` (5.2, 6.5); `APP_ENV`, a worker
healthcheck, `stop_grace_period`, the `NEXT_PUBLIC_*` build args and a `SCHEDULER_PROCESS` row in
`docs/ops/configuration.md` (the configuration test names it the moment the field exists); the schema check
inside the lifespan (2.3).
