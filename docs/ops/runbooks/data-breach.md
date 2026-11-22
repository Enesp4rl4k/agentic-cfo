# Personal-data breach (KVKK Md. 12)

Code: `api/compliance_extended.py` (`POST /compliance/gdpr/breach-notification`, `GET /compliance/gdpr/breaches`,
`POST /compliance/gdpr/breach/{id}/notify`), `services/compliance_filing_decision.py`, `services/privacy/breach_scope.py`,
`GET /privacy/operator/breach-scope`. Registry: `docs/kvkk/veri-envanteri-uretilen.md`. Not legal advice: who tells the
Board and the people, and what, is the owner's and a lawyer's call (`docs/kvkk/avukata-sorular.md` Q10).

## What the product already does

- A company's **owner or admin** records a breach in the product (`breach-notification`): description, severity, an
  estimate of people affected. The record starts a 72-hour deadline and writes a `compliance_filing` decision
  ("breach_recorded"); marking it notified writes another ("marked_notified"). The decision record holds no free text
  (the description stays in `breach_notifications`).
- The record is **per company**. A breach of the platform touches many companies, and the platform operator has no
  route to record on their behalf: step 4 below is manual until the owner decides otherwise.

## Steps (a platform-wide incident)

1. **Stop it.** Rotate the secret that leaked ([rotate-secret.md](rotate-secret.md)); take the host off the network if
   needed. Note the time you learned of it: the 72 hours run from awareness.
2. **Say what was reachable**, in registry terms. Ask the product which companies and categories a store or table holds:

   ```bash
   # as a platform operator (your token), keys are registry tables or stores
   curl -s -H "Authorization: Bearer $TOKEN" \
     "https://$API_DOMAIN/api/v1/privacy/operator/breach-scope?keys=uploads,outbox_messages,audit_logs,users"
   # or with the production database URL: dc exec backend python -m app.services.privacy.breach_scope uploads users
   ```

   The answer lists, per key, the categories (identity, contact, network, tax_id, free_text, document), whose data it is
   (member, counterparty, company, accountant), the third parties it can reach and **row counts per company** (counts
   only, no content). Typical keys: a stolen disk or volume is `uploads`, `report_files`, `board_decks`, `agent_memory`
   plus every table; a leaked mail credential is `outbox_messages`; a stolen API token is whatever that user's role
   could read. Chat history lives in Redis (`chat_history`, `redis_derived`): 7 days at most.
3. **Fix the number.** The count of *people* is an estimate: members per company from `users`, counterparties from the
   rows of the exposed tables. Write the estimate and its basis down; do not wait for a precise figure to start.
4. **Tell the companies** (processors tell controllers "without delay"): the owner of each affected company, with the
   categories and the time. Each owner records the breach in the product from their own account; offer to do it together.
5. **The notification to the Board** (and to the people when the risk is high) is made by the controller, normally the
   company, within 72 hours of awareness; whether the platform also notifies for its own data (accounts, billing) is Q10.
   Mark each record notified in the product when it is done (`breach/{id}/notify`).
6. **Afterwards**: the incident note (what, when, which keys, which companies, what was told to whom), a copy of the
   `compliance_filing` decisions, and the fix. If a restore was needed, re-apply erasures
   ([offboard-and-erasure.md](offboard-and-erasure.md), `scripts/reapply_erasures.py`).

## Check

`GET /compliance/gdpr/breaches` (as the company's owner) shows the open records with the countdown. The registry answers
"which data": `breach_scope` refuses a key it does not know (422), so a typo is not an empty answer.

## Not verified

Run only on SQLite fixtures (`tests/test_privacy_breach_and_restore.py`); never against production. The Board's notification
form and procedure are outside this repository.
