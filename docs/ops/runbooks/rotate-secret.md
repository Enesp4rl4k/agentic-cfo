# Rotate a secret

Rotate on suspicion of leak, when someone who knew a secret leaves, and on a schedule you choose (yearly is
reasonable for three companies). Never print a secret in a terminal that is logged; generate it straight into
the file.

| Secret | What changes when you rotate it | How |
|---|---|---|
| `BACKEND_SECRET_KEY` (signs JWTs) | **Every user is signed out** (access and refresh tokens stop verifying). Also: if `FIELD_ENCRYPTION_KEY` is empty, connector secrets are encrypted with a key *derived from this one* and become unreadable (`connectors/crypto.py:22-26`); users must reconnect the connector. Paraşüt OAuth states in flight fail once. | set `FIELD_ENCRYPTION_KEY` first if connectors exist and keep the old key to decrypt, then change this one |
| `NEXTAUTH_SECRET` | Every browser session ends; users sign in again | change in `.env`, rebuild is not needed (runtime) |
| `POSTGRES_PASSWORD` | The database role's password must be changed in Postgres **and** in `.env`, then every container restarted. `.env` alone breaks the app | see below |
| `SMTP_PASSWORD`, `OPENAI_API_KEY`, `STRIPE_*`, `WHATSAPP_*`, `SLACK_*`, `EMAIL_INBOUND_SECRET` | The integration stops until the new value is in place; provider-side first, then `.env` | change at the provider, edit `.env`, `dc up -d` |
| `FIELD_ENCRYPTION_KEY` | Stored connector secrets cannot be decrypted with the new key; there is no re-encryption tool | do not rotate until one exists; if you must, users reconnect every connector |
| age backup key | Archives made with the old public key need the old private key | generate a new pair, change `AGE_RECIPIENT`, keep the old private key for 14 days (the retention) |

## Procedure (the usual case: one value in `.env`)

```bash
cd /opt/agentic-cfo && cp .env /root/env.backup.$(date +%F) && chmod 600 /root/env.backup.*   # a copy outside the repo
# edit .env: replace the value (generate with: openssl rand -hex 32)
dc up -d                   # recreates containers whose environment changed
./scripts/smoke-test.sh --api https://<API_DOMAIN> --app https://<APP_DOMAIN>
```

Delete the copy of the old `.env` when you are sure; it holds every old secret.

## `POSTGRES_PASSWORD`

```bash
dc exec postgres psql -U aicfo -d aicfo -c "ALTER ROLE aicfo PASSWORD '<new>'"   # the password shows in the shell history: use a prompt (\password aicfo) instead
# then edit .env and:
dc up -d --force-recreate backend worker worker-maintenance
```

## Not verified

None of this has been run. The preflight refuses template values at startup, so a rotation to a weak value
fails fast in production.
