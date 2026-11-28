# First real deployment: the ordered checklist

One person, one server, in this order. Every line says whether the CI job `Production stack (compose)`
(`.github/workflows/stack.yml`) already proves it on a clean runner (**verified in CI**) or whether only you can
(**cannot be verified in CI: verify by hand**). "Verified in CI" means the mechanism works with throw-away values;
it never means your server, your DNS or your provider's account works. Background and the reasons are in
[staging.md](staging.md), [runbook.md](runbook.md) and [configuration.md](configuration.md).

## 1. Decisions and accounts (before the server exists)

| # | Item | Status |
|---|---|---|
| 1.1 | A VPS in Turkey, **4 vCPU / 12 GB RAM / 160 GB SSD**, Ubuntu 24.04, fixed IPv4, ports 22, 80, 443 (tcp) and 443 (udp) reachable. The 12 GB come from the memory limits in `docker-compose.prod.yml`: backend 2560m, worker 2g, postgres 2g, redis 640m, maintenance 768m, frontend 512m, caddy 256m = about 8.8 GB, plus the host. | Limits **verified in CI** (`docker inspect` shows exactly these numbers, the backend sees 2560m in its cgroup, the parser runs under it). The host itself: **cannot be verified in CI: verify by hand** (`free -h`, `nproc`). |
| 1.2 | Domain with DNS you control: two names, `app.<domain>` and `api.<domain>`, both A records (AAAA if the server has IPv6) to the server. They must resolve **before** the first `up` (`dig +short api.<domain>`), or Let's Encrypt rate limits you. | **cannot be verified in CI: verify by hand** |
| 1.3 | Mail provider (SMTP) and its DNS (SPF, DKIM, DMARC) for the `NOTIFICATION_FROM` domain: [mail.md](mail.md). | **cannot be verified in CI: verify by hand** (CI proves what the application does when mail cannot leave, not that your provider delivers). |
| 1.4 | Backup storage in Turkey, separate from the VPS provider, reachable by `rclone`. | **cannot be verified in CI: verify by hand** |
| 1.5 | Operator e-mail addresses (two) and a support contact. | Not needed to start (WARN only). |
| 1.6 | Public `https` links of the privacy notice and the terms of use (published by your lawyer). | Must be https URLs: **verified in CI** (the preflight refuses anything else). That they open: **cannot be verified in CI: verify by hand**. |

## 2. The server (once, as `deploy`)

| # | Item | Status |
|---|---|---|
| 2.1 | User, firewall (`ufw`: 22, 80, 443/tcp, 443/udp), SSH keys only: [staging.md section 4](staging.md#4-kurulum-bir-kez) steps 1-2. | **cannot be verified in CI: verify by hand** |
| 2.2 | Docker Engine with the compose plugin; `sudo apt install -y git age rclone python3 jq`. | The job installs `age`, `rclone`, `jq` the same way and uses the compose plugin: **verified in CI**. |
| 2.3 | `git clone <repo> /opt/agentic-cfo && cd /opt/agentic-cfo`; `cp .env.example .env && chmod 600 .env`. | **verified in CI** (the job starts from a clean checkout and `.env.example`). |
| 2.4 | A backup key pair **on your laptop**: `age-keygen -o aicfo-backup.key`. The private key goes into your password manager, never onto the server; the public key (`age1...`) is `AGE_RECIPIENT`. | Encrypt and decrypt with a generated pair: **verified in CI**. Keeping the private key safe: **cannot be verified in CI: verify by hand**. |
| 2.5 | `rclone config` for the backup storage; test with `rclone lsd <remote>:`. | **cannot be verified in CI: verify by hand** (CI uses a local directory as the rclone destination). |

## 3. The `.env` (the minimal production configuration)

Fill these in `.env`. The list is what the CI job has to set to start the stack in production mode; the job fails if this
page stops naming one of them. Where each value comes from:

| Key | Where it comes from | Status |
|---|---|---|
| `APP_DOMAIN`, `API_DOMAIN` | the two hostnames of 1.2 | Used by Caddy, CORS, e-mailed links: **verified in CI** with `app.ci.internal` / `api.ci.internal` |
| `ACME_EMAIL` | your address, for certificate expiry mail | **verified in CI** (required by compose); issuance itself: **cannot be verified in CI: verify by hand** |
| `POSTGRES_PASSWORD` | `openssl rand -hex 24` | **verified in CI** |
| `BACKEND_SECRET_KEY` | `openssl rand -hex 32` (at least 32 characters) | **verified in CI** |
| `NEXTAUTH_SECRET` | `openssl rand -base64 32` | **verified in CI** |
| `ERASURE_PSEUDONYM_SECRET` | `openssl rand -hex 32`, set once, **never rotated** | **verified in CI** (a start without it is refused) |
| `PRIVACY_NOTICE_URL`, `TERMS_URL` | the links of 1.6 | **verified in CI** (https required) |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFICATION_FROM` | the mail provider of 1.3 | A configured sender is required to start: **verified in CI** (a start without `SMTP_USER` is refused). Real delivery: **cannot be verified in CI: verify by hand** |
| `PLATFORM_OPERATOR_EMAILS`, `SUPPORT_CONTACT` | your operator addresses, a support address | Optional to start; without them the preflight warns |
| `AGE_RECIPIENT`, `BACKUP_RCLONE_REMOTE`, `BACKUP_LOCAL_DIR` | 2.4, 2.5, a directory such as `/var/backups/aicfo` | The backup script with these: **verified in CI** (local target). The real remote: **cannot be verified in CI: verify by hand** |

Optional but expected for the pilot: `OPENAI_API_KEY` (and `LLM_*`) once the LLM decision is made, `SENTRY_DSN`,
`FIELD_ENCRYPTION_KEY`, `BRAND_*`. The compose file sets everything else (`APP_ENV=production`, the database, Redis, the
public URLs from the two domains, `SCHEDULER_PROCESS=worker`, `TRUSTED_PROXY_COUNT=1`).
Do not write `PILOT_*` variables; nothing reads them. Registration is invite-only by default (`REGISTRATION_MODE=invite_only`).

## 4. Bring it up

| # | Item | Status |
|---|---|---|
| 4.1 | `./scripts/up-prod.sh`: sets `IMAGE_TAG` to the commit, builds, runs `migrate` (Alembic, then the preflight with `--db`), starts the stack and waits until every service is healthy. | **verified in CI** (the job runs this very script on a clean runner; real timing is in the job summary) |
| 4.2 | `migrate` exited 0 and Alembic is at head; the production preflight prints `PREFLIGHT ok (production)`; the same preflight fails when `ERASURE_PSEUDONYM_SECRET`, `SMTP_USER` or `PRIVACY_NOTICE_URL` is removed, and a backend container without a required value refuses to start. | **verified in CI** |
| 4.3 | Read every `WARN` line of the preflight (`dc run --rm --no-deps backend python -m app.core.preflight --db`) and decide each. | **cannot be verified in CI: verify by hand** |
| 4.4 | TLS: `https://api.<domain>/api/v1/ready` and `https://app.<domain>` open in a browser with a valid Let's Encrypt certificate. | Caddy, routing, HTTP-to-HTTPS redirect and both hostnames work with Caddy's internal CA (CI adds the one override `docker-compose.ci.yml`, which only sets `local_certs`; never use it on the server): **verified in CI**. Certificate issuance from Let's Encrypt: **cannot be verified in CI: verify by hand** |
| 4.5 | `/api/v1/ready` and `/api/v1/version` answer through Caddy; the landing page and `/api/health` of the frontend answer; both ARQ workers are seen; a job enqueued by the API side is completed by the maintenance worker; the scheduler runs only in the worker and writes its heartbeat. | **verified in CI** |
| 4.6 | Parser: Tesseract with the Turkish model is in the image; a text PDF and a scanned PDF (OCR, `tur+eng`) parse inside the backend container under its real 2560m limit. | **verified in CI** |
| 4.7 | `./scripts/smoke-test.sh --api https://api.<domain> --app https://app.<domain> --expect-commit "$(git rev-parse --short HEAD)"` ends `SMOKE TEST PASSED`; again with `--strict` after five minutes (`ready`, not `degraded`). | The script against the stack: **verified in CI** (not `--strict`: CI has no mail server). On your domain: **cannot be verified in CI: verify by hand** |
| 4.8 | Only ports 22, 80, 443 reachable from outside (`nmap` from another host). | **cannot be verified in CI: verify by hand** |

## 5. The first operator and the first invitation

| # | Item | Status |
|---|---|---|
| 5.1 | `dc exec backend python scripts/issue_pilot_invite.py --email you@<domain> --company "Tiphys Operasyon"`: the invitation is mailed to you through the outbox. | The script runs in the image and queues the invitation: **verified in CI**. Mail arriving: **cannot be verified in CI: verify by hand** |
| 5.2 | Open the mailed link, choose a password: you own the new company. Registration without an invitation answers 403. | Redeeming an invitation through the API, the 403 without it, and single use: **verified in CI**. The browser page and your mail: **cannot be verified in CI: verify by hand** |
| 5.3 | With no mail server the application does not crash: the outbox row stays `pending` with the error and is retried every five minutes up to five attempts, then `failed` ([mail.md](mail.md)). | **verified in CI** (a first attempt is recorded, the API stays ready) |
| 5.4 | Your address is in `PLATFORM_OPERATOR_EMAILS` (two operators); `GET /api/v1/pilot/invites` answers 200 for you. | **cannot be verified in CI: verify by hand** |

## 6. Backups, before any real data

| # | Item | Status |
|---|---|---|
| 6.1 | `./scripts/backup.sh` once by hand: an `aicfo-*.tar.age` appears at the remote and `last-success` is written. Then the cron line of [staging.md section 4](staging.md#4-kurulum-bir-kez) step 10. | The script against the running stack (pg_dump, uploads, age, rclone copy and check, marker): **verified in CI** with a local target. Your remote and your cron: **cannot be verified in CI: verify by hand** |
| 6.2 | Restore drill with your private key: `AGE_IDENTITY_FILE=/tmp/aicfo-backup.key ./scripts/restore-drill.sh` ends `RESULT: OK` ([runbook.md section 4](runbook.md#4-geri-yükleme-tatbikatı)). | The drill restores the stack's own archive into a fresh Postgres and the restored database holds the pilot company, its owner and the uploaded file: **verified in CI**. With your key and your remote: **cannot be verified in CI: verify by hand** |
| 6.3 | Uptime monitor on `/api/v1/ready` and a backup heartbeat (the alert must reach you once on purpose). | **cannot be verified in CI: verify by hand** |

## 7. Retention: switch deletion on after the first report

The retention job ships in dry run (`RETENTION_DRY_RUN=true`, the default in `.env.example`, `docker-compose.prod.yml`
and the Helm values): it only COUNTS outbox bodies, notifications, alert history, expired tokens and invitations,
audit-log addresses (and raw uploads if `RETENTION_UPLOAD_DAYS` > 0). Until you switch it off, those retention periods
are not in effect, and the preflight says so (`WARN [retention_dry_run]`, deliberately not fatal so this first deploy
starts). LangGraph checkpoints, orphaned checkpoint threads and erasure leftovers are deleted from the first run
whatever the flag says: nothing reads them ([configuration.md](configuration.md), `docs/kvkk/veri-envanteri-uretilen.md`).

| # | Item | Status |
|---|---|---|
| 7.1 | After the first night (the job runs at 03:30 UTC in the worker): `dc logs worker \| grep "retention report:"` shows one line per store, `due=<n> action=counted` (dry run) or `action=deleted` (always enforced); the same counts are in the table `retention_runs` and, for an operator, under `retention.last_run` of `/api/v1/ready`. | Counted-but-kept versus deleted, per store, on Postgres: **verified in CI** (`tests/test_retention_postgres.py` in the job "Migrations on Postgres"). Your numbers: **cannot be verified in CI: verify by hand** |
| 7.2 | Read the counts. Nothing surprising (a store you expected to keep, a number far larger than the company's history)? Then turn dry run off after reviewing the first dry-run report: `RETENTION_DRY_RUN=false` in `.env`, `./scripts/up-prod.sh`. The preflight no longer prints `retention_dry_run`, and the next night's report says `action=deleted` for every store. | **cannot be verified in CI: verify by hand** |

When every line is ticked, continue with [pilot-acceptance-checklist.md](pilot-acceptance-checklist.md) and
[runbooks/onboard-company.md](runbooks/onboard-company.md).
