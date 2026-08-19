# CI Repository Secrets

GitHub Actions CI uses **repository secrets** so no credentials are stored in workflow YAML.

Add these under: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Purpose | Example (generate your own) |
|--------|---------|----------------------------|
| `CI_PG_PASS` | Ephemeral Postgres password for CI service container | random 32-char string |
| `CI_BACKEND_SECRET` | Backend JWT/signing key for CI tests | random 32+ char string |
| `CI_NEXTAUTH_SECRET` | NextAuth secret for frontend build in CI | random 32+ char string |

These are **throwaway CI-only values** — not production credentials. Use any random strings; they never leave GitHub Actions.

Generate locally (do not commit output):

```bash
openssl rand -base64 32
```

After adding secrets, re-run the failed workflow or push a new commit.
