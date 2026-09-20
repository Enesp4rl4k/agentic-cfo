# CI secrets: none needed

CI runs without any repository secret. It used to require `CI_PG_PASS`,
`CI_BACKEND_SECRET` and `CI_NEXTAUTH_SECRET`; none was ever added, so every job
would have stopped at its first step.

Those values were never credentials:

- The Postgres service container exists only on the runner for the length of
  the job and is reachable only from it, so it runs with no password
  (`POSTGRES_HOST_AUTH_METHOD: trust`). A literal password, however harmless,
  was reported as a leaked credential by GitGuardian and SonarCloud.
- The backend signing key and the NextAuth secret sign test tokens in a test
  run. Each job generates fresh random ones (`openssl rand`) into `$GITHUB_ENV`
  and masks them in the log.

`backend/tests/test_ci_database.py` fails if the workflow starts reading a
repository secret other than `GITHUB_TOKEN`, or reads a context where GitHub
does not provide it (the reason every run of the workflow failed in 0 seconds
with no jobs).

The **Migrations on Postgres** job applies every Alembic migration to the
service container, checks the result against the models (`alembic check`),
rolls everything back, and applies the chain again — the only place the chain
runs before production.

Settings reads `DATABASE_URL_OVERRIDE` and `USE_SQLITE`; a bare `DATABASE_URL`
is ignored, and the same test file fails if a job sets it again.

Production secrets are a different matter and are never put in this workflow.
