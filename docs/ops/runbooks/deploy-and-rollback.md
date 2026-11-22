# Deploy, roll back, smoke test

The authoritative steps are PR #96's `docs/ops/runbook.md` sections 1 and 2 (backup first, tag images by commit,
`migrate` one-shot gates the API, rollback with the migration case). This page adds what that PR does not have.

## Before every deploy

1. `./scripts/backup.sh` (the runbook already says so). Do not deploy after a failed backup.
2. Read the migration list: `git diff --stat <running commit> <new commit> -- backend/alembic/versions`.
   A migration that drops a column or table is a DISPATCH item (CLAUDE.md): ask the owner first. At the time
   of this audit none of the 74 migrations drops anything in `upgrade()`.
3. Deploy outside working hours: `up -d` recreates containers, so there is a short outage (audit 10.5).

## Build arguments

The backend image reports its commit on `/api/v1/version` from `GIT_SHA` (a build argument) or, when that is
empty, from `IMAGE_TAG` in the compose `.env` (the deploy step already writes it). The frontend reads
`NEXT_PUBLIC_*` at **build time** only; changing them on a running container changes nothing.

## After every deploy (and after every restore)

```bash
./scripts/smoke-test.sh --api https://<API_DOMAIN> --app https://<APP_DOMAIN> --expect-commit "$(git rev-parse --short HEAD)"
```

It checks liveness, readiness (503 = database, schema or Redis), the running commit, that an anonymous call is
refused, the security headers, CORS for the app origin and not for a stranger, and the
frontend. Add `--strict` to also fail on `degraded` (worker, outbox, scheduler). The first run after a deploy
is often `degraded` for up to five minutes until the scheduler's first outbox pass.

## Roll back

1. Did the deploy run a migration? If not: set `IMAGE_TAG` to the previous commit, `git checkout` it, `up -d`.
2. If yes: the old image does not know the new revision. Downgrade with the **new** image first
   (`dc run --rm migrate alembic downgrade <old head>`), then switch the tag. Every migration has a
   `downgrade()` and CI runs the full rollback on Postgres, but a downgrade that drops a column loses that
   column's data.
3. If the downgrade fails or the data is wrong: restore the pre-deploy backup ([db-restore.md](db-restore.md)).
4. Run the smoke test with the old commit as `--expect-commit`, and `python -m app.core.preflight --db`.

## Not verified

Nothing here has been run on a host. The rollback is the steps of #96 with the added checks.
