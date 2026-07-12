# CLAUDE.md — AI CFO project laws

Laws, not tips. Every rule has a number, a "never", or a command that checks it.

## NEVER

1. Never report a task done without a passing check command. Done = `./verify.sh` exits 0.
2. Never add a dependency without listing it in `requirements.txt` or `package.json` first.
3. Never commit `.env` — only `.env.example` with placeholder values.
4. Never write raw SQL — use SQLAlchemy ORM exclusively.
5. Never add `any` type in TypeScript without an `// eslint-disable` comment explaining why.
6. Never touch `backend/app/agents/` orchestration logic without running `pytest tests/test_agents/ -q` after.
7. Never modify DB models without creating an Alembic migration.
8. Never call the OpenAI API directly from frontend — route through backend only.
9. Never accept file uploads without validating: extension in {pdf, xlsx, csv}, size ≤ 10 MB.
10. Never skip the confidence gate in `runAgent` — an agent that always auto-proceeds is a bug.

## DISPATCH (route these to humans before acting)

- Any change to `backend/app/api/` auth or rate-limiting logic
- Any Alembic migration that drops a column or table
- Any change to the `CFOState` TypedDict that removes a field
- Docker Compose changes that affect port bindings in production

## PRINCIPLES

- Nothing grades its own homework. The agent that computed a result is never
  the one that verifies it — the verifier node runs in a separate LangGraph step.
- Confidence gate is load-bearing. `awaitingReview=True` when confidence < 0.80
  or when any skill sets `needs_review=True`. The UI holds the run until a human approves.
- One skill, one responsibility. A skill that does two things must be split into two.
- Audit trail is mandatory. Every agent run writes a `JobLog` row. No silent failures.

## VERIFY COMMAND

```bash
./verify.sh
```

Exits 0 = safe to ship. Non-zero = do not proceed.

## PROJECT CONVENTIONS

- Backend: `backend/` — FastAPI + LangGraph, Python 3.11+
- Frontend: `frontend/` — Next.js 14 App Router, TypeScript strict
- All financial amounts stored as `INTEGER` (kuruş/cents), displayed divided by 100
- Dates stored as UTC, displayed in user's local timezone
- Job IDs are UUIDs, never sequential integers
- API responses always: `{ data: T, error: string | null, meta?: object }`
