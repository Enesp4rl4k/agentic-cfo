# Payment plan changes need a senior executive's approval

Decision (owner, 2026-11-20): nobody changes another person's payment plan alone. Moving a payable's
date needs approval from a senior executive ("üst yönetici").

Today `/takvim` is a scenario only: moves live in the page, nothing is written. This note is the design
for making a moved payment real under that rule. It is **not built yet**.

## The rule

- Any member of the organisation may **propose** a date change for a payable.
- Only the organisation's **owner or an admin** may **approve** it. The proposer never approves their
  own proposal, even when they hold the role (a second person signs).
- Until it is approved nothing changes: the radar, the base forecast and the reports keep the date the
  documents gave. A rejected proposal changes nothing and keeps its reason.
- Every proposal, approval and rejection is written with who, when and why. No silent change.

## Shape

- Model `PaymentPlanChange`: `id` (UUID), `org_id`, `open_item_id`, `from_date`, `to_date`,
  `requested_by`, `requested_at`, `status` (`pending | approved | rejected | withdrawn`), `decided_by`,
  `decided_at`, `reason`. Dates are UTC; no amount is stored, the open item holds it.
- Alembic migration for the table (CLAUDE.md rule 7). It adds a table, drops nothing.
- Approval applies the new date to the open item as an *override* beside the document's own due date,
  so the original stays visible and a rejection or withdrawal restores it.
- Endpoints under `/ledger/plan-changes` (propose, list, approve, reject, withdraw), every one scoped to
  the caller's organisation through `app/api/access.py`; approve and reject check the role and that the
  approver is not the proposer. Test the role matrix route by route.
- UI: `/takvim` gets "Onaya gönder" per moved payment; the owner or admin sees the proposals as a third
  list in `/onay` (the same screen as match approvals), with the old and the new date and the radar's
  lowest cash before and after.

## Needs a human review (CLAUDE.md DISPATCH)

The role check is access logic under `backend/app/api/`. It must be reviewed by a person before it ships.

## Open question

Which roles count as "üst yönetici": owner only, or owner and admin?
