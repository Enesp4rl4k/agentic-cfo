# Offboard a company, erase its data

Code: `api/org_erasure.py`, `services/org_erasure.py`, `tests/test_org_erasure.py`. KVKK Md. 7.

## What the erasure does

Two steps and a cooling-off. **Request** (`POST /compliance/org-erasure/request`, owner or admin of the company, body
`{"mode": "anonymise"}`) records the intent and returns a phrase; nothing is touched. **Confirm**
(`POST /compliance/org-erasure/{request_id}/confirm`, the company's **owner**, body `{"confirmation_phrase": ...}`)
re-checks role, company and phrase and **schedules** the erasure: it runs when the cooling-off ends
(`ERASURE_COOLING_OFF_DAYS`, default 7; the scheduler's `erasure_executor` job, hourly), and the owner can
**cancel** until then (`POST .../{request_id}/cancel`). Every step writes an `erasure` decision record. A request expires
after 7 days if nobody confirms. When it runs, a proof record (hash-chained, no personal data) is written.

**The operator** can schedule an erasure on a verified request: `POST /compliance/operator/org-erasure`
`{"org_id", "verification_ref": "<ticket id>"}` (platform operator only). The cooling-off is never skipped (at least a day),
the company gets an in-app notice, and the owner can cancel. Record the ticket number, never a name.

**One person** (a member leaves or asks): `POST /privacy/member-erasure` (the person, with their e-mail typed back) or
`POST /privacy/org/members/{user_id}/erasure` (owner/admin, for a member of no other company). The account stays usable during
the cooling-off; it then becomes a tombstone under a stable pseudonym and the company's decision record keeps pointing at it
(`docs/kvkk/avukata-sorular.md` Q4). A sole owner is refused (`sole_owner`): transfer ownership or erase the company.

- `anonymise` (the only mode on): deletes everything except the books (transactions, canonical transactions,
  journal, open items, matches, approvals, analysis jobs) and the audit log; the retained rows keep amounts,
  dates and account codes, and the personal-data columns are overwritten. Uploaded files are deleted. Users of
  the company are deleted; the organisation row is anonymised.
- `hard_delete`: refused with 422 unless `ORG_ERASURE_HARD_DELETE_ENABLED=true`. Do not switch it on until the
  retention question (plan G19) is answered by the owner and a lawyer (audit D7).

## Steps

1. Get the request in writing from the company's owner. Check the legal basis for what is retained with the
   lawyer if the company asks for *everything* to go.
2. Offer an export first: only a per-user export exists (`GET /compliance/data-export`); a whole-company
   export is not in this change (audit item 9.3). Ledger and decision records can be read out in the app.
3. The owner (or admin) requests; the owner confirms with the phrase. You do not do it for them.
4. **Backups still contain the data** until the retention window passes (14 days remote, 2 local archives).
   Say so to the company (wording: `docs/kvkk/yedek-ve-silme.md`). Do not edit old archives.
5. Verify: the confirm call answers with the proof record; the company's users cannot sign in; the files
   directory for its jobs is gone from the volume (`ls /app/uploads/uploads/<job id>` inside a backend container).
6. If a restore is later needed from a backup older than an erasure, the erased company comes back: before restoring run
   `python scripts/reapply_erasures.py --export > erased.json`, after it `--apply erased.json` (hashes only, idempotent).
7. **Copies at third parties.** The proof record's counts say how many remain: `_external_followup.stripe_customer` (delete
   or anonymise the customer in Stripe), `erp_integrations` / `connector_connections` (the grants are gone here but still
   valid at the provider: revoke them there), and the LLM provider keeps prompts under its own terms (Q1).
8. **Caches.** The erasure also removes the company's Redis keys, chat history and agent memory; `_ephemeral.redis_failed: 1`
   in the record means Redis was down: those keys expire by themselves within 7 days.

## Where personal data lives

Table by table: `docs/kvkk/veri-envanteri-uretilen.md` (generated from the registry, test-enforced) and, by hand,
`docs/kvkk/veri-envanteri.md` (PR #68; differences in `veri-envanteri-farklar.md`). The erasure derives its scope from the
schema and a test fails on an unclassified table; `tests/test_erasure_end_to_end.py` proves files, Redis and agent memory.

## Not verified

The erasure is tested on SQLite fixtures (`tests/test_org_erasure.py`), not on Postgres at volume and not
through the proxy. Whether the volume's file removal matches `STORAGE_LOCAL_PATH` on the compose stack
(`/app/uploads/uploads/<job id>`) was read, not run.
