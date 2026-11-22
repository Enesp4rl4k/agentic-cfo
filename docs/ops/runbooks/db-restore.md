# Restore the database

Two cases. The procedure itself is proven by CI (the `Migrations on Postgres` job of `.github/workflows/ci.yml` runs
`scripts/restore-roundtrip.sh`: dump, restore into a fresh database, same rows and files, schema check,
migrate down and up, smoke test). What CI cannot prove is your archive, your key and your host: do the
drill on the host before real data goes in.

## A. Drill (no impact on the live stack), monthly

PR #96 ships `scripts/restore-drill.sh`: fetch the newest archive, verify checksums, decrypt with the age
private key (brought for the drill, deleted after), restore into a throwaway Postgres on a throwaway
network, compare `alembic current`, row counts and the uploads count.

```bash
install -m 600 /dev/stdin /tmp/aicfo-backup.key      # paste the key from the password manager, Ctrl-D
AGE_IDENTITY_FILE=/tmp/aicfo-backup.key ./scripts/restore-drill.sh
shred -u /tmp/aicfo-backup.key
```

`RESULT: OK` or the drill did not pass. Write down the date and the archive name.

## B. Real restore (data corrupted or lost)

Full commands: PR #96 `docs/ops/runbook.md` section 5. In short:

1. Take a backup of the current state first (`./scripts/backup.sh`), even if it is broken: it is evidence.
2. Stop writers: `dc stop caddy frontend backend worker worker-maintenance`.
3. Decrypt the archive, `dropdb` / `createdb`, `pg_restore --no-owner --exit-on-error`, unpack `uploads.tar.gz`
   into the uploads volume, `dc up -d`.
4. If the archive's revision is older than the running image, `migrate` moves it forward; if newer, switch to
   the image of that revision ([deploy-and-rollback.md](deploy-and-rollback.md)).
5. **Verify:** `./scripts/smoke-test.sh --api https://<API_DOMAIN> --app https://<APP_DOMAIN> --strict`
   and `python -m app.core.preflight --db` inside the backend container
   (`dc run --rm --no-deps backend python -m app.core.preflight --db`). Then ask one company to open the
   Monday briefing page and compare with the last figure they remember.
6. Tell the companies what period of data may be missing (everything after the archive's timestamp). Uploads
   they made since must be repeated.

## Point-in-time recovery

There is none: backups are nightly dumps, so up to 24 hours of data can be lost. Say so to the pilot
companies. Continuous archiving is a later decision.

## Not verified

The age/rclone steps need the staging stack and a real key; they have not been run. The CI job restores an
unencrypted dump of a migrated, nearly empty database: it proves the mechanics, not the volume of real data.
