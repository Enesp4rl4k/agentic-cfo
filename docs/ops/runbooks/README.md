# Runbooks

One short page per incident a pilot will actually have. Commands assume the single-VPS compose stack of
PR #96, run in `/opt/agentic-cfo` as the deploy user:

```bash
alias dc='docker compose -f docker-compose.prod.yml'
alias psql_app='dc exec -T postgres psql -U aicfo -d aicfo'    # add -c "..." or pipe SQL in
```

Conventions: **Check** says what to look at, **Fix** what to do, **Not verified** what was written from the
code and has never been run on a host. Nothing here has been run on a host yet. Never paste a user's
e-mail address, a token or a file's content into a ticket or chat; use the user id.

| Situation | Page |
|---|---|
| A user cannot log in, or did not get the e-mail | [login-and-email.md](login-and-email.md) |
| An upload is stuck, held or failed | [upload-stuck-or-held.md](upload-stuck-or-held.md) |
| The Monday briefing did not arrive | [briefing-not-sent.md](briefing-not-sent.md) |
| A customer says a number is wrong | [wrong-number.md](wrong-number.md) |
| Locked out by the IP allow-list | [ip-allowlist-lockout.md](ip-allowlist-lockout.md) |
| Disk is full | [disk-full.md](disk-full.md) |
| Restore the database | [db-restore.md](db-restore.md) |
| Rotate a secret | [rotate-secret.md](rotate-secret.md) |
| Add or remove a platform operator | [platform-operators.md](platform-operators.md) |
| Onboard a new pilot company | [onboard-company.md](onboard-company.md) |
| Offboard a company, erase its data | [offboard-and-erasure.md](offboard-and-erasure.md) |
| Deploy, roll back, smoke test | [deploy-and-rollback.md](deploy-and-rollback.md) |

First look at any incident: `curl -s https://<API_DOMAIN>/api/v1/ready` (503 = database, schema or Redis;
`degraded` = worker, outbox or scheduler; the `checks` object says which) and `dc ps`.
