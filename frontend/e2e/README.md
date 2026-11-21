# Browser test: the pilot's core flow

One user journey in Chromium against the real stack: register and create a company, set-up page,
upload a bank statement and an invoice list, cash radar, Monday briefing, a category correction,
an accountant added by invitation, a held briefing released, a viewer refused, a plan change
approved, the decision records, an approved action that is not connected.

```bash
cd frontend
npm ci
npx playwright install chromium
npm run build                # CI builds; locally `next dev` is used unless E2E_FRONTEND_MODE=start
npm run e2e                  # starts the stub model, the API and the web app, then runs the journey
```

## What it starts (no Docker, no Redis, no keys, no mail)

| Piece | How |
| --- | --- |
| API | `support/start_backend.py` (port 8000): uvicorn on a fresh SQLite file in `e2e/.run/` (tables built on startup). With no broker an upload's analysis runs inline, which is the product's own fallback for SQLite. |
| Model | `support/llm_stub.py`: stands where the provider would, at `LLM_BASE_URL`. It answers the three structured calls of the boardroom debate (the only thing in the journey that needs a model) and answers every other call with 503. Only a second API process on port 8001 (same database, same folder) points at it; with a model key the first API's analyses change behaviour, so the journey runs on the key-less one and uses the second for the one boardroom step. |
| Web | `next start` (CI) or `next dev`, on `localhost:3000`, pointing at `localhost:8000`. |
| Mail | No SMTP. The e-mails the product writes stay in its outbox; `support/probe.py outbox` reads them. |

Set `E2E_REUSE=1` to attach to servers that are already running.

## What the test reads from the database, and why

`support/probe.py` is read-only except for one thing: `monday-tick` runs the scheduler's own Monday
job once (the product has no screen or endpoint that starts it). It also reads

- the invitation token, because the API only e-mails it and nothing on screen shows it;
- the outbox, because the briefing e-mail is never delivered here.

No role, company or document is created by writing to the database: people register, are invited and
accept through the API, and everything else is done in the browser.

## Failures

Playwright keeps the trace, video and screenshot of a failed step (`test-results/`) and an HTML
report (`playwright-report/`); CI uploads both, and the API log (`e2e/.run/api.log`), as artifacts.
Steps the product cannot do yet are `test.fixme` with the reason in a comment; they are written as
the test that should pass once it can.

The API allows five sign-ins a minute per address; the journey paces its own sign-ins (`support/api.ts`), which is most of its run time on a slow machine.
