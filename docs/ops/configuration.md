# Configuration reference

The authoritative list of every variable the application reads, checked against the code by
`backend/tests/test_configuration_docs.py`: a setting added to `backend/app/config.py` without a row
below, or a row without a setting, fails that test. `.env.example` is held to the same list.

Where a variable is read:

* **Settings** (section 1): `backend/app/config.py`, read from the process environment and from a
  `.env` file in the working directory. Variable name = field name in upper case.
* **Process environment only** (section 2): read with `os.environ` / `os.getenv`, so a value that exists
  only in a `.env` file does not reach it. With `docker compose` and `env_file:` the file becomes the
  process environment, which is why the compose stack works.
* **Frontend and compose** (section 3): not read by the backend.

Production means `USE_SQLITE=false`, or `APP_ENV` set to `production` or `staging`
(`backend/app/core/preflight.py`). **`APP_ENV` is required whenever the database is Postgres** (FATAL
`app_env_missing` / `app_env_unknown` otherwise): `production`, `prod`, `staging`, `demo`, `development`, `dev`,
`ci` or `test`. A host that forgot it would otherwise run in "warnings only" mode. Outside production a FATAL finding is logged as a warning, so a laptop
is never blocked. WARN findings are logged in every mode.

## What startup does

1. `Settings.validate_production_security()` (existing): insecure default secret, field encryption on
   without a key, inline job fallback on Postgres.
2. `app.core.preflight.enforce_or_exit()` (`backend/app/main.py` for the API, `backend/app/worker.py` for the
   ARQ worker: both process types run the same preflight): the rules in the "Caught at startup"
   column. In production any FATAL finding exits with status 1 and names every cause; WARN findings are
   logged at WARNING and returned.
3. `python -m app.core.preflight --db` runs the same checks and compares the database's Alembic revision
   with the code's single head (exit 1 on `behind`, `ahead`, `unknown`). Run it after `alembic upgrade
   head` in a deploy; the API reports the same comparison on `/api/v1/ready`.

## 1. Settings

<!-- settings-table-start -->
| Variable | Default | In production | Caught at startup | Note |
|---|---|---|---|---|
| `BRAND_NAME` | `Tiphys` | optional | - |  |
| `BRAND_DOMAIN` | (empty) | optional | - |  |
| `BRAND_APP_URL` | `http://localhost:3000` | REQUIRED | FATAL if localhost (APP_ENV production/staging), else WARN | public app URL (links, KVKK texts) |
| `BRAND_CONTACT_EMAIL` | (empty) | recommended | - | shown to users; empty = shown as unconfigured |
| `BRAND_PRIVACY_EMAIL` | (empty) | recommended | - | KVKK texts; empty = unconfigured |
| `BRAND_DPO_EMAIL` | (empty) | recommended | - | KVKK texts; empty = unconfigured |
| `OPENAI_API_KEY` | `llm-placeholder-dev` | recommended | WARN if placeholder | any OpenAI-compatible key; without it chat and narrative answer 503 |
| `RADAR_BALANCE_STALE_AFTER_DAYS` | 7 | optional | - |  |
| `RADAR_HELD_MATERIAL_RATIO` | 0.1 | optional | - |  |
| `POSTGRES_HOST` | `localhost` | optional | - |  |
| `POSTGRES_PORT` | 5432 | optional | - |  |
| `POSTGRES_DB` | `aicfo` | optional | - |  |
| `POSTGRES_USER` | `aicfo` | optional | - |  |
| `POSTGRES_PASSWORD` | `changeme` | REQUIRED | FATAL if empty or `changeme` | or DATABASE_URL_OVERRIDE; never `changeme` |
| `POSTGRES_SSLMODE` | (empty) | optional | validated against the known modes |  |
| `DATABASE_URL_OVERRIDE` | (empty) | optional | FATAL if it carries `:changeme@` |  |
| `REDIS_URL` | `redis://localhost:6379/0` | REQUIRED | - | queue, locks, rate limits |
| `ARQ_ANALYSIS_QUEUE_NAME` | `arq:queue:analysis` | optional | - |  |
| `ARQ_PRODUCER_CONN_RETRIES` | 1 | optional | - |  |
| `ARQ_MAINTENANCE_QUEUE_NAME` | `arq:queue:maintenance` | optional | - |  |
| `ARQ_ANALYSIS_MAX_JOBS` | 10 | optional | - |  |
| `ARQ_MAINTENANCE_MAX_JOBS` | 3 | optional | - |  |
| `BACKEND_SECRET_KEY` | `dev-secret-change-in-production` | REQUIRED | FATAL if placeholder, default or < 32 chars | random, >= 32 chars; also signs JWTs |
| `BACKEND_CORS_ORIGINS` | `http://localhost:3000,http://localhost:3001,http://localhost:3002` | REQUIRED | FATAL `*`; WARN localhost or http:// | exactly the public app origin(s), https |
| `BACKEND_URL` | `http://localhost:8000` | REQUIRED | WARN if localhost | public API URL (OAuth callbacks) |
| `FRONTEND_URL` | `http://localhost:3000` | REQUIRED | FATAL if localhost (APP_ENV production/staging), else WARN | public app URL; every e-mailed link is built from it |
| `AZURE_TENANT_ID` | (empty) | optional | - |  |
| `AZURE_CLIENT_ID` | (empty) | optional | - |  |
| `AZURE_CLIENT_SECRET` | (empty) | optional | - |  |
| `GOOGLE_CLIENT_ID` | (empty) | optional | - |  |
| `GOOGLE_CLIENT_SECRET` | (empty) | optional | - |  |
| `GITHUB_CLIENT_ID` | (empty) | optional | - |  |
| `GITHUB_CLIENT_SECRET` | (empty) | optional | - |  |
| `FIELD_ENCRYPTION_KEY` | (empty) | recommended | WARN if empty | Fernet key for connector secrets; set before the first connector, never rotate casually |
| `FIELD_ENCRYPTION_ENABLED` | False | optional | FATAL without FIELD_ENCRYPTION_KEY |  |
| `OPENBANKING_AKBANK_CLIENT_ID` | (empty) | optional | - |  |
| `OPENBANKING_AKBANK_CLIENT_SECRET` | (empty) | optional | - |  |
| `OPENBANKING_GARANTI_CLIENT_ID` | (empty) | optional | - |  |
| `OPENBANKING_GARANTI_CLIENT_SECRET` | (empty) | optional | - |  |
| `OPENBANKING_ISBANK_CLIENT_ID` | (empty) | optional | - |  |
| `OPENBANKING_ISBANK_CLIENT_SECRET` | (empty) | optional | - |  |
| `OPENBANKING_YAPIKREDI_CLIENT_ID` | (empty) | optional | - |  |
| `OPENBANKING_YAPIKREDI_CLIENT_SECRET` | (empty) | optional | - |  |
| `SHOPIFY_SHOP_DOMAIN` | (empty) | optional | - |  |
| `SHOPIFY_ACCESS_TOKEN` | (empty) | optional | - |  |
| `TRENDYOL_SUPPLIER_ID` | (empty) | optional | - |  |
| `TRENDYOL_API_KEY` | (empty) | optional | - |  |
| `TRENDYOL_API_SECRET` | (empty) | optional | - |  |
| `GOOGLE_SHEETS_SERVICE_ACCOUNT` | (empty) | optional | - |  |
| `SLACK_WEBHOOK_URL` | (empty) | optional | - |  |
| `TEAMS_WEBHOOK_URL` | (empty) | optional | - |  |
| `CUSTOM_WEBHOOK_URL` | (empty) | optional | - |  |
| `WHATSAPP_PHONE_NUMBER_ID` | (empty) | optional | - |  |
| `WHATSAPP_ACCESS_TOKEN` | (empty) | optional | - |  |
| `WHATSAPP_API_VERSION` | `v19.0` | optional | - |  |
| `TWILIO_ACCOUNT_SID` | (empty) | optional | - |  |
| `TWILIO_AUTH_TOKEN` | (empty) | optional | - |  |
| `TWILIO_WHATSAPP_FROM` | (empty) | optional | - |  |
| `WHATSAPP_VERIFY_TOKEN` | (empty) | optional | FATAL if set to the old public default `agentic-cfo-verify` and WhatsApp is configured | no default since #133: unset disables the WhatsApp webhook |
| `SLACK_BOT_TOKEN` | (empty) | optional | - |  |
| `SLACK_SIGNING_SECRET` | (empty) | optional | - |  |
| `WHATSAPP_APP_SECRET` | (empty) | optional | - |  |
| `EMAIL_INGEST_DOMAIN` | (empty) | optional | - |  |
| `EMAIL_INBOUND_SECRET` | (empty) | optional | - |  |
| `PARASUT_CLIENT_ID` | (empty) | optional | - |  |
| `PARASUT_CLIENT_SECRET` | (empty) | optional | - |  |
| `SMTP_HOST` | `smtp.gmail.com` | recommended | - | mail sender; the default is smtp.gmail.com |
| `SMTP_PORT` | 587 | optional | - |  |
| `SMTP_USER` | (empty) | recommended | WARN if no sender (ERROR log with verification required) | without it no invite, reset, verification or briefing mail leaves |
| `SMTP_PASSWORD` | (empty) | recommended | WARN if no sender | see SMTP_USER |
| `NOTIFICATION_FROM` | `noreply@aicfo.app` | recommended | - | From address; its domain needs SPF and DKIM (docs/ops/mail.md) |
| `OUTBOX_TRANSPORT` | `auto` | optional | WARN if `noop`; FATAL with APP_ENV production/staging when REGISTRATION_MODE=invite_only or verification is required | `noop` means no mail leaves the process |
| `OUTBOX_KICK_ON_ENQUEUE` | True | optional | - |  |
| `EMAIL_VERIFICATION_REQUIRED` | True | recommended | FATAL with APP_ENV production/staging when no mail sender is configured (else WARN) | true needs a working mail sender |
| `EMAIL_VERIFICATION_EXPIRE_HOURS` | 48 | optional | - |  |
| `TRUSTED_PROXY_COUNT` | 0 | recommended | WARN if neither it nor the CIDRs are set | 1 behind Caddy; or use TRUSTED_PROXY_CIDRS |
| `TRUSTED_PROXY_CIDRS` | (empty) | recommended | WARN if neither it nor the count is set | the proxy's network, instead of the count |
| `PASSWORD_RESET_EXPIRE_MINUTES` | 30 | optional | - |  |
| `PASSWORD_RESET_PER_EMAIL_PER_HOUR` | 3 | optional | - |  |
| `AUTH_MAIL_COOLDOWN_MINUTES` | 15 | optional | - |  |
| `PASSWORD_RESET_RESPONSE_FLOOR_SECONDS` | 0.5 | optional | - |  |
| `TCMB_API_KEY` | (empty) | optional | - |  |
| `GIB_VKN` | (empty) | optional | - |  |
| `GIB_USERNAME` | (empty) | optional | - |  |
| `GIB_PASSWORD` | (empty) | optional | - |  |
| `GIB_SANDBOX` | True | optional | - |  |
| `GIB_EDEFTER_ENV` | `test` | optional | - |  |
| `AKBANK_CLIENT_ID` | (empty) | optional | - |  |
| `AKBANK_CLIENT_SECRET` | (empty) | optional | - |  |
| `GARANTI_CLIENT_ID` | (empty) | optional | - |  |
| `GARANTI_CLIENT_SECRET` | (empty) | optional | - |  |
| `OPEN_BANKING_SANDBOX` | True | optional | - |  |
| `OPEN_BANKING_REDIRECT_URI` | `http://localhost:8000/api/v1/open-banking/callback` | optional | - |  |
| `STORAGE_BACKEND` | `local` | optional | - |  |
| `STORAGE_LOCAL_PATH` | `./uploads` | optional | - |  |
| `ORG_ERASURE_HARD_DELETE_ENABLED` | False | optional | - |  |
| `ERASURE_COOLING_OFF_DAYS` | 7 | optional | - | KVKK erasure: days between the owner's confirmation and the destructive step (0 = immediately); the owner can cancel until then |
| `ERASURE_PSEUDONYM_SECRET` | (unset) | optional | - | KVKK member erasure: key of the HMAC behind the stable `member-<hex>` pseudonym; empty falls back to `BACKEND_SECRET_KEY`. Set once and keep it: a new value only changes the pseudonym of people erased afterwards |
| `LLM_MODEL` | `deepseek-chat` | optional | - |  |
| `LLM_MODEL_CHEAP` | (unset) | optional | - |  |
| `LLM_MODEL_STRONG` | (unset) | optional | - |  |
| `LLM_MODEL_PRICES` | {} | optional | - |  |
| `LLM_TEMPERATURE` | 0.0 | optional | - |  |
| `LLM_MAX_TOKENS` | 16384 | optional | - |  |
| `LLM_BASE_URL` | `https://api.deepseek.com` | optional | - |  |
| `PLATFORM_OPERATOR_EMAILS` | (empty) | recommended | WARN if empty | who can mint pilot invites and break-glass an IP allow-list |
| `SUPPORT_CONTACT` | (empty) | recommended | WARN if empty | named in the lock-out message and on the invite-only sign-up page ("ask here for an invitation") |
| `REGISTRATION_MODE` | `invite_only` | REQUIRED to decide | FATAL with APP_ENV production/staging when `invite_only` and no mail sender | `open` anyone, `invite_only` a pilot or organisation invite, `closed` as invite_only but a pilot invite no longer creates a company. Governs `/auth/register`, SSO sign-up and `/org/create` |
| `PILOT_INVITE_EXPIRE_DAYS` | 14 | optional | - | lifetime of a pilot invitation link |
| `OPERATOR_ALERT_COOLDOWN_MINUTES` | 360 | optional | - | one alert code and subject goes to the operators once per this window |
| `JOB_FAILURE_ALERT_AFTER` | 3 | optional | - | a scheduled job (company and period) that failed this many times alerts the operators; retries stop after 5 |
| `OUTBOX_FAILURE_ALERT_THRESHOLD` | 5 | optional | - | failed outbox rows to one destination in 24 hours that alert the operators |
| `OPS_REPORT_TOKEN` | (empty) | recommended | - | shared secret of `POST /platform/ops/backup-report` (header `X-Ops-Token`); empty = the endpoint answers 404 and backups are not monitored |
| `BACKUP_MAX_AGE_HOURS` | 30 | optional | - | with `OPS_REPORT_TOKEN` set: no successful backup report for this long alerts the operators |
| `MAX_UPLOAD_SIZE_MB` | 10 | optional | - |  |
| `AUTO_ENQUEUE_ANALYSIS_ON_UPLOAD` | True | optional | - |  |
| `ALLOW_INLINE_JOB_FALLBACK` | (unset) | optional | FATAL on Postgres |  |
| `AGENT_AUTO_PROCEED_MIN_CONFIDENCE` | 0.8 | optional | - |  |
| `RAG_BACKFILL_ENABLED` | True | optional | - |  |
| `RAG_BACKFILL_LOOKBACK_DAYS` | 14 | optional | - |  |
| `RAG_EMBEDDING_ENABLED` | True | optional | - |  |
| `RAG_EMBEDDING_MODEL` | `text-embedding-3-small` | optional | - |  |
| `RAG_EMBEDDING_DIMENSIONS` | 1536 | optional | - |  |
| `JOB_LEASE_SECONDS` | 900 | optional | - |  |
| `STALE_PENDING_MINUTES` | 60 | optional | - |  |
| `STALE_AGENT_RUN_MINUTES` | 30 | optional | - |  |
| `REAPER_ENABLED` | True | optional | - |  |
| `SCHEDULER_ENABLED` | True | optional | - | kill switch: `false` starts no APScheduler cron anywhere |
| `SCHEDULER_PROCESS` | `api` | REQUIRED = `worker` on the compose stack (the stack sets it) | - | `api` or `worker` (anything else is refused at config load). Names the ONE process type that runs the APScheduler crons: `api` = every API process (dev without a worker); `worker` = only the arq analysis worker (`worker.WorkerSettings`), never the API or the maintenance worker. With `worker`, no worker running means no crons: the readiness `scheduler` check (`no_recent_outbox_pass`) reports it. `SCHEDULER_ENABLED=false` wins over both. Every cron also holds a Redis lock, so replicas of the owner never double-run a tick |
| `SSE_MAX_CONNECTIONS` | 50 | optional | - |  |
| `DB_POOL_SIZE` | 20 | optional | - |  |
| `DB_MAX_OVERFLOW` | 10 | optional | - |  |
| `CHECKPOINT_SQLITE_PATH` | `./langgraph_checkpoints.sqlite` | optional | - |  |
| `USE_SQLITE` | True | REQUIRED | FATAL with APP_ENV=production or staging | must be `false` |
| `SQLITE_BUSY_TIMEOUT_SEC` | 15.0 | optional | - |  |
| `DEMO_MODE` | `False` | optional | FATAL with APP_ENV production/staging, else WARN | never on where real companies sign in |
| `DEMO_COMPANY_NAME` | `TechNova Yazılım A.Ş.` | optional | - |  |
| `DEMO_GUEST_TTL_HOURS` | 24 | optional | - |  |
| `STRIPE_SECRET_KEY` | (empty) | optional | - |  |
| `STRIPE_WEBHOOK_SECRET` | (empty) | optional | - |  |
| `STRIPE_PUBLISHABLE_KEY` | (empty) | optional | - |  |
| `STRIPE_PRICE_STARTER_MONTHLY` | (empty) | optional | - |  |
| `STRIPE_PRICE_STARTER_YEARLY` | (empty) | optional | - |  |
| `STRIPE_PRICE_PRO_MONTHLY` | (empty) | optional | - |  |
| `STRIPE_PRICE_PRO_YEARLY` | (empty) | optional | - |  |
| `STRIPE_PRICE_ENTERPRISE_MONTHLY` | (empty) | optional | - |  |
| `STRIPE_PRICE_ENTERPRISE_YEARLY` | (empty) | optional | - |  |
<!-- settings-table-end -->

## 2. Process environment only

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | (empty = development on SQLite) | REQUIRED with Postgres: `production`, `prod`, `staging`, `demo`, `development`, `dev`, `ci` or `test`. `production` or `staging` turns production rules on even with SQLite; also labels telemetry and Sentry. The compose stack sets it for every backend container: `${APP_ENV:-production}`, so put `APP_ENV=staging` in `.env` on a staging box |
| `LOG_LEVEL` | `INFO` | `DEBUG` in production is a WARN finding |
| `LOG_FORMAT` | `json` | `json` or anything else for plain text. Both mask e-mail addresses, IBANs and credentials |
| `SENTRY_DSN` | (unset) | error tracking, **off unless set** (a third-party transfer: decide with the KVKK documents first). When on: no default PII, no request bodies, no cookies or credential headers, no local variables; e-mails, IBANs and bearer tokens in messages are masked before anything leaves (`services/sentry_monitoring.py`). Unset = errors only in the container log (WARN finding) |
| `SENTRY_ENVIRONMENT` | `APP_ENV`, else `production` | Sentry environment tag |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.05` | performance tracing sample rate |
| `GIT_SHA` | (unset) | commit of the image; shown on `/api/v1/version`, used as the Sentry release |
| `IMAGE_TAG` | (unset) | the compose stack tags images with it and passes it as the `GIT_SHA` build arg and runtime value (the deploy sets it to the commit); `/api/v1/version` reports it |
| `BUILD_TIME` | (unset) | build timestamp shown on `/api/v1/version` |
| `NEXTAUTH_SECRET` | (unset) | frontend session secret; the backend only refuses a template value when a shared `.env` carries it |
| `USE_SQLITE` | `true` | also read directly by `app/core/redis_client.py` to switch Redis off for development |
| `REDIS_URL` | `redis://localhost:6379/0` | also read directly by `app/services/agent_bus.py` |
| `DISABLE_REDIS` | (unset) | `true` runs with no broker (development, tests) |
| `AGENT_BUS_REDIS` | (unset) | agent bus backend switch (`app/services/agent_bus.py`) |
| `LANGGRAPH_CHECKPOINT` | follows `USE_SQLITE` | `memory`, `sqlite` or `postgres` checkpoint store |
| `OTEL_ENABLED`, `OTEL_ENDPOINT`, `OTEL_EXPORTER`, `JAEGER_HOST`, `JAEGER_PORT` | off | OpenTelemetry tracing (`app/services/telemetry.py`) |
| `LANGSMITH_ENABLED`, `LANGSMITH_API_KEY`, `LANGSMITH_ENDPOINT`, `LANGSMITH_PROJECT`, `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_ENDPOINT`, `LANGCHAIN_PROJECT` | off | LangSmith tracing. Sends prompts to a third party: leave off with company data |
| `CSUITE_URL`, `CSUITE_API_KEY` | (unset) | the MCP server's client (`app/mcp/server.py`), not the API |

## 3. Frontend and compose (not read by the backend)

| Variable | Where | Purpose |
|---|---|---|
| `NEXTAUTH_URL`, `NEXTAUTH_SECRET` | frontend, runtime | NextAuth. Secret: `openssl rand -base64 32` |
| `NEXT_PUBLIC_API_URL` | frontend, **build time** | public API URL baked into the browser bundle |
| `NEXT_PUBLIC_DEMO_MODE` | frontend, **build time** | `false` in production |
| `NEXT_PUBLIC_LEGACY_DASHBOARDS` | frontend, **build time** | `false` (default): placeholder dashboards stay hidden |
| `NEXT_PUBLIC_BRAND_NAME`, `NEXT_PUBLIC_BRAND_DOMAIN`, `NEXT_PUBLIC_BRAND_APP_URL`, `NEXT_PUBLIC_BRAND_CONTACT_EMAIL`, `NEXT_PUBLIC_BRAND_TWITTER_URL`, `NEXT_PUBLIC_BRAND_LINKEDIN_URL` | frontend, **build time** | brand strings; a runtime value changes nothing |
| `BACKEND_INTERNAL_URL` | frontend, runtime | server-side calls to the API inside the compose network |
| `BACKEND_PORT`, `FRONTEND_PORT`, `BACKEND_IMAGE`, `FRONTEND_IMAGE`, `GITHUB_REPOSITORY` | `docker-compose.yml` | ports and image names |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | compose and Settings | database name, user, password (the compose file hands them to the postgres container too) |
| `APP_DOMAIN`, `API_DOMAIN`, `ACME_EMAIL` | staging stack (`docker-compose.prod.yml`, required) | public hostnames of the frontend and the API; the Let's Encrypt account e-mail. The compose file derives `BACKEND_CORS_ORIGINS`, `FRONTEND_URL`, `BRAND_APP_URL`, `BACKEND_URL` and the frontend's `NEXTAUTH_URL`/`NEXT_PUBLIC_API_URL` from them |
| `AGE_RECIPIENT`, `BACKUP_RCLONE_REMOTE` | `scripts/backup.sh` (required) | the `age1...` public key and the rclone `remote:path` of the off-server copy |
| `BACKUP_RETENTION_DAYS`, `BACKUP_KEEP_LOCAL`, `BACKUP_LOCAL_DIR` | `scripts/backup.sh` | remote retention (default 14 days), newest archives kept on the server (default 2), staging directory (default `/var/backups/aicfo`) |
| `COMPOSE_FILE` | `scripts/backup.sh` | compose file the script talks to (default `docker-compose.prod.yml`) |


`NEXT_PUBLIC_*` values are inlined by `next build`: set them as build arguments, not on the running
container (the frontend `Dockerfile` takes `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_DEMO_MODE` and
`NEXT_PUBLIC_LEGACY_DASHBOARDS`; the compose stack passes the first two from `API_DOMAIN`/`false` and the
third from `.env`, default `false`).

**What each compose service sees.** The backend containers (`migrate`, `backend`, `worker`,
`worker-maintenance`) read the whole `.env` plus the fixed values the compose file sets (`APP_ENV`,
`USE_SQLITE=false`, `SCHEDULER_PROCESS=worker`, `TRUSTED_PROXY_COUNT=1`, `ALLOW_INLINE_JOB_FALLBACK=false`,
`GIT_SHA`, the Postgres/Redis hosts, the public URLs): a value of those in `.env` is ignored. Postgres gets
only `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`. Caddy gets `APP_DOMAIN`, `API_DOMAIN`, `ACME_EMAIL`.
The frontend gets exactly `NEXT_PUBLIC_API_URL`, `NEXTAUTH_URL` and `NEXTAUTH_SECRET` at runtime and no backend secret;
`scripts/check-prod-compose.sh` fails CI if that changes.

## 4. Read by nothing

Earlier `.env.example` files documented variables no code reads. They are gone from `.env.example`.
Setting them changes nothing:

| Variable | What it implied | Reality |
|---|---|---|
| `PILOT_REQUIRE_INVITE`, `PILOT_MODE`, `PILOT_MAX_USERS` | an invite requirement and a user cap | **Removed (PR #139).** They were read by nothing and registration was open. `REGISTRATION_MODE` replaces them and is enforced by `/auth/register`, SSO and `/org/create`; there is no user cap (the number of companies is the number of pilot invites an operator issues). The Kubernetes and Helm config maps no longer set them |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET`, `AWS_S3_REGION` | S3 storage | `STORAGE_BACKEND` is read by nothing; files go to `STORAGE_LOCAL_PATH` |
| `DEFAULT_COUNTRY_CODE`, `DEFAULT_BASE_CURRENCY`, `DEFAULT_LOCALE` | organisation defaults | not read |
| `EMAIL_INGEST_API_KEY`, `EMAIL_ALLOWED_DOMAINS`, `EMAIL_MAX_ATTACHMENT_MB` | inbound mail guard | the inbound webhook uses `EMAIL_INBOUND_SECRET`; the others are not read |
| `PARASUT_REDIRECT_URI` | callback address | built from `BACKEND_URL` (the compose stack sets `BACKEND_URL` from `API_DOMAIN`); setting this variable changes nothing |
