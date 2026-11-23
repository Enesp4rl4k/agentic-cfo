# Pilot acceptance checklist

Tick every line before inviting the first company. Each line names its evidence; a line you cannot show
evidence for is not ticked. The audit ([operational-readiness-2026-11.md](operational-readiness-2026-11.md))
explains the reasons and ratings. "Blocker" lines are the ones the audit rated GAP, blocker.

## A. Decisions the owner makes

- [ ] Hosting provider chosen and the VPS exists in Turkey (D8). Evidence: the contract.
- [ ] Domain, `APP_DOMAIN` and `API_DOMAIN` resolve to the VPS (`dig +short`). Evidence: command output.
- [x] Registration policy decided and applied (D1: closed, invitation only; `REGISTRATION_MODE=invite_only`, PR #139). Evidence: `POST /auth/register` without an invite answers 403 on the host; the register page says "yalnızca davetle".
- [ ] The first operator account exists (`scripts/issue_pilot_invite.py`, [runbooks/onboard-company.md](runbooks/onboard-company.md)). Evidence: the operator signs in and `GET /api/v1/pilot/invites` answers 200.
- [ ] Mail provider chosen, SPF, DKIM and DMARC pass (D2). Evidence: "show original" of a received invitation ([mail.md](mail.md)).
- [ ] Backup destination chosen, in Turkey, separate from the VPS provider (D3). Evidence: `rclone lsd` output.
- [ ] Alert channel chosen: an uptime monitor on `/api/v1/ready` and a backup heartbeat ping (D4). Evidence: a test alert received.
- [ ] LLM provider decided with a lawyer, or the narrative features switched off (D6). Evidence: the decision note.
- [ ] Erasure retention decided (D7) and the KVKK documents of PR #68 reviewed by a lawyer. Evidence: the lawyer's reply.

## B. The host is configured

- [ ] `APP_ENV` is set (production) and `REGISTRATION_MODE` is not `open` (the host says so on `/api/v1/version` and `/auth/registration`). Evidence: both responses.
- [ ] `.env` is mode 600, not in git, and passes the preflight: `dc run --rm --no-deps backend python -m app.core.preflight --db`
      exits 0 with no `FATAL`. Evidence: output ([configuration.md](configuration.md)).
- [ ] No `WARN` left that you have not decided to accept: mail sender, LLM key, `SENTRY_DSN`, `TRUSTED_PROXY_COUNT=1`,
      `FIELD_ENCRYPTION_KEY`, `ERASURE_PSEUDONYM_SECRET` (own random value, never rotated), `PRIVACY_NOTICE_URL` and `TERMS_URL` (required in production: public https links that open; a missing or malformed value is FATAL), `PLATFORM_OPERATOR_EMAILS` (two operators), `SUPPORT_CONTACT`. Evidence: the same output.
- [ ] `APP_ENV=production`, `DEMO_MODE` unset, `NEXT_PUBLIC_DEMO_MODE=false`, `NEXT_PUBLIC_LEGACY_DASHBOARDS=false` (built, not just set). Evidence: `.env`; `/cto` shows "not found" when signed in.
- [ ] The host holds the parser memory minimum: API container (`backend`) **>= 2.5 GB** (`mem_limit: 2560m`), worker **>= 2 GB** (`2g`), plus Postgres and Redis (about 8.8 GB of limits in all: plan a 12 GB host). On Kubernetes the backend limit is `2560Mi` (`k8s/20-backend.yaml`, Helm `backend.resources.limits.memory`). Evidence: `docker inspect -f '{{.HostConfig.Memory}}' <backend and worker>` and no `parser_memory_exceeds_container` in the preflight output ([parser-sizing.md](parser-sizing.md)).
- [ ] Only ports 22, 80, 443 are reachable from outside; Postgres and Redis are not (`nmap` from another host). Evidence: scan output.
- [ ] `./scripts/smoke-test.sh --api ... --app ... --expect-commit <sha> --strict` ends `SMOKE TEST PASSED`. Evidence: output.
- [ ] `GET /api/v1/ready` says `ready`, not `degraded`, five minutes after start. Evidence: response.

## C. Backups

- [ ] **Blocker:** the nightly backup ran at least three nights and the newest remote archive is under 24 hours old. Evidence: `rclone lsl` ([runbooks/db-restore.md](runbooks/db-restore.md)).
- [ ] **Blocker:** a restore drill on the host ended `RESULT: OK` with the owner's real key, before real data. Evidence: drill output and date.
- [ ] The age private key is in the owner's password manager and not on the server. Evidence: the owner confirms.
- [ ] CI is green on the "Backup and restore roundtrip" step of the `Migrations on Postgres` job (the mechanics of dump, restore, migrate, health). Evidence: [ci.yml](../../.github/workflows/ci.yml).

## D. Operations

- [ ] **Blocker:** an alert actually reaches the owner when `/api/v1/ready` fails (external monitor) and when the backup does not run (`OPS_REPORT_TOKEN` set, `scripts/report-backup.sh failed` called once on purpose: an `[Tiphys] Yedekleme başarısız` mail arrives at an operator). Evidence: a deliberate test.
- [ ] The Monday briefing arrived by e-mail at a test company, on a Monday, from the scheduler (not by hand) ([runbooks/briefing-not-sent.md](runbooks/briefing-not-sent.md)). Evidence: the mail and `worker` log line.
- [ ] A worker restart at 07:00 UTC does not lose the briefing: restart the worker on a Monday between 07:00 and 07:10 and see the briefing arrive within about 11 minutes (catch-up; audit 6.3; ledger `scheduled_job_runs`). Evidence: the mail and the `catch-up` log line.
- [ ] Verification, reset, organisation-invitation and pilot-invitation mail each reached a real mailbox ([runbooks/login-and-email.md](runbooks/login-and-email.md)). Evidence: three received mails.
- [ ] The IP allow-list break-glass was run once on a test company ([runbooks/ip-allowlist-lockout.md](runbooks/ip-allowlist-lockout.md)). Evidence: the decision record.
- [ ] The owner has read every page in [runbooks/](runbooks/) and knows where the commands are.

## E. Data and security

- [ ] A test company's upload to briefing ran end to end on the host with a real-shaped file (the Playwright "Pilot flow" job covers the code, not the host). Evidence: screenshots.
- [ ] A test company's organisation erasure was requested, confirmed and verified ([runbooks/offboard-and-erasure.md](runbooks/offboard-and-erasure.md)). Evidence: the proof record.
- [ ] Cookie flags checked once in the browser (`Secure`, `HttpOnly`, `SameSite`) for the NextAuth session (audit 1.13). Evidence: devtools screenshot.
- [ ] Response headers of API and app checked by the smoke test; the missing frontend CSP is accepted knowingly (audit 8.3).
- [ ] The accepted GAPs in the audit (8.6 upload limits, 8.10 dependency audit, 8.12 database role, 9.3 export, 9.4 retention) were read and accepted by the owner. Evidence: initials and date on this page.

## F. The first company

- [ ] [runbooks/onboard-company.md](runbooks/onboard-company.md) done with them, not for them.
- [ ] They know: who to write to (`SUPPORT_CONTACT`), that backups are nightly, what a held row is, and that numbers older than seven days say "last known".
