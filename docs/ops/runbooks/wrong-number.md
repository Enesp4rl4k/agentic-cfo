# A customer says a number is wrong

Principle: every number on a screen comes from ledger rows that came from a file, and every change to
those rows has a decision record. Trace it backwards before anyone says the number is right or wrong.

## Collect (from the customer, not from the database)

Which screen, which figure, which date or week, which company. Ask for a screenshot. Do not open their
data before you know what you are looking for.

## Trace

1. **Which data is it based on?** Cash radar and briefing show an "as of" date and the bank balance they
   rest on. A statement balance older than `RADAR_BALANCE_STALE_AFTER_DAYS` (7) is shown as "last known",
   not as today's cash. `GET /data/freshness` says which upload each figure used.
2. **Which rows add up to it?** `GET /ledger/summary?start=...&end=...` and `GET /analysis/{job_id}/transactions`
   (members of the company, or you as the user). A number held back is absent on purpose: rows held as
   possible duplicates, an unknown currency or an unreadable row are *not* in the radar; the briefing says so
   in its headline when the amount is material (`RADAR_HELD_MATERIAL_RATIO`). `GET /analyses/held` lists them.
3. **What changed the rows?** `GET /decision-records` (owner, admin, cfo, smmm) is the company-wide log of who
   decided what, when, on which evidence: corrections, releases, plan changes, matches. One object's history
   is open to members. `GET /analysis/{job_id}/decision-packet` is the packet for one run.
4. **Was the file read correctly?** Compare a few rows with the customer's original file
   (`/app/uploads/uploads/<job id>/document.<ext>`). A row the parser could not read is held, never guessed.
5. **Was a correction applied?** Corrections and releases appear in the decision records of step 3; compare the
   row before and after (not verified here whether a correction can ever change an amount: read
   `api/corrections.py` before answering the customer).
6. **Foreign currency:** a total in a currency other than the company's base currency is shown per
   currency, not converted; an unknown currency is labelled unknown.

## Decide

- Number follows from the rows: show the customer the rows (screen share) and the decision record.
- The file was read wrongly: keep the job id, the file and the row; this is a bug, not a data fix. Do not edit
  `transactions` by hand.
- The customer's file was incomplete or old: say which date the data runs to.

## Not verified

The endpoints are real (`api/ledger.py`, `api/analysis.py`, `api/decision_records.py`, `api/data_freshness.py`);
the walk-through has not been done with a customer. There is no single "explain this figure" endpoint.
