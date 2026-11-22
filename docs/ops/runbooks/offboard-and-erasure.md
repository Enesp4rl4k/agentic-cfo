# Offboard a company, erase its data

Code: `api/org_erasure.py`, `services/org_erasure.py`, `tests/test_org_erasure.py`. KVKK Md. 7.

## What the erasure does

Two steps. **Request** (`POST /compliance/org-erasure/request`, owner or admin of the company, body
`{"mode": "anonymise"}`) records the intent and returns a phrase; nothing is touched. **Confirm**
(`POST /compliance/org-erasure/{request_id}/confirm`, the company's **owner**, body `{"confirmation_phrase": ...}`)
re-checks role, company and phrase, then runs the erasure in one transaction. A request expires after 7 days.
A proof record (hash-chained, no personal data) is written.

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
   export does not (audit item 9.3). Ledger and decision records can be read out in the app.
3. The owner (or admin) requests; the owner confirms with the phrase. You do not do it for them.
4. **Backups still contain the data** until the retention window passes (14 days remote, 2 local archives).
   Say so to the company. Do not edit old archives.
5. Verify: the confirm call answers with the proof record; the company's users cannot sign in; the files
   directory for its jobs is gone from the volume (`ls /app/uploads/uploads/<job id>` inside a backend container).
6. If a restore is later needed from a backup older than an erasure, the erased company comes back: re-run the
   erasure after any restore (keep the list of erased company ids outside the database).

## Where personal data lives

Table by table: `docs/kvkk/veri-envanteri.md` (PR #68). That inventory lists 33 of the 64 tables as rows; the
audit lists the rest (item 9.5). The erasure itself does not depend on the inventory: it derives scope from the
schema and a test fails on an unclassified table.

## Not verified

The erasure is tested on SQLite fixtures (`tests/test_org_erasure.py`), not on Postgres at volume and not
through the proxy. Whether the volume's file removal matches `STORAGE_LOCAL_PATH` on the compose stack
(`/app/uploads/uploads/<job id>`) was read, not run.
