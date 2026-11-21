# Payment plan changes need a senior executive's approval

Decision (owner, 2026-11-20): nobody changes a payment plan alone. Moving a payable's date needs
approval from a senior executive, and the senior executives are **the owner and the people assigned
the admin role**.

## The rule

- A member with write access (owner, admin, CFO, analyst) may **propose** a new date for a payable.
  A viewer may not.
- The company's **accountant (`smmm`) does not propose**: moving a payment date is the company's commercial decision, so the accountant advises and the company proposes. The screen lets the accountant try dates in the scenario, but the send button is inert and says why; the API answers 403 (`PROPOSER_ROLES`, mirrored in `frontend/src/lib/roles.ts` and checked by a test).
- Only an **owner or an admin** may **decide**. An owner or admin who proposes holds that authority
  themselves, so they may decide their own proposal: a company with one owner would otherwise never be
  able to move a payment. Everyone else's proposal waits for someone with the role.
- Until it is approved nothing changes: the radar, the base forecast and the reports keep the date the
  documents gave. A rejected or withdrawn proposal changes nothing and keeps its reason.
- Only the person who proposed may withdraw, and only while it waits. A decision is made once.
- One open proposal per payment. Only payables with a due date and money still owed can be moved,
  to a date from today to one year ahead. Receivables are never moved: their date is not ours to set.
- Every proposal and decision is the row itself: who, when, for which date, and why. Each step also leaves a decision record (`kind=plan_change`, outcome `proposed`, `approved`, `rejected` or `withdrawn`); an owner or admin who decides their own proposal leaves `proposed` and `approved`, both theirs, and the approval carries `self_decided: true`.

## What is built (backend, `app/api/plan_changes.py`, `app/services/payment_plan.py`)

- Table `payment_plan_changes` (migration 053): organisation, open item, from and to date, status,
  requester and time and note, decider and time and note. No amount is stored; the open item holds it.
- An approved change tells the radar when the payment is expected (`RadarItem.expected_date`, with
  `rescheduled: true`); the document's own `due_date` on the open item is never overwritten.
- `POST /ledger/plan-changes`, `GET /ledger/plan-changes?status=`, `POST …/{id}/approve | reject |
  withdraw`. Every route is scoped to the caller's organisation: another organisation's proposal is a
  404. `tests/test_payment_plan_changes.py` walks the role matrix and the organisation boundary.

## What is built (frontend)

- `/takvim`: a payment moved in the scenario becomes "Onaya gönder"; for an owner or admin the same
  button is "Planı değiştir" (propose and approve in one step). The server's own refusal sentence is
  shown as it is.
- `/onay`: a third list, the proposals waiting. An owner or admin approves or rejects with an optional
  reason; anyone else sees that the decision belongs to an owner or admin, and the proposer may
  withdraw.

## Needs a human review (CLAUDE.md DISPATCH)

The role checks are access logic under `backend/app/`. A person must review them before they ship.
