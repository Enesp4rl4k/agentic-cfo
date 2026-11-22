# Payment plan changes need a senior executive's approval

Decision (owner, 2026-11-20): nobody changes a payment plan alone. Moving a payable's date needs
approval from a senior executive, and the senior executives are **the owner and the people assigned
the admin role**.

## The rule

- A member with write access (owner, admin, CFO, analyst) may **propose** a new date for a payable.
  A viewer may not.
- The company's **accountant (`smmm`) does not propose**: moving a payment date is the company's commercial decision, so the accountant advises and the company proposes. The screen lets the accountant try dates in the scenario, but the send button is inert and says why; the API answers 403 (`PROPOSER_ROLES`, mirrored in `frontend/src/lib/roles.ts` and checked by a test).
- Only an **owner or an admin** may **decide**. Everyone else's proposal waits for someone with the role.
- **When the proposer is also the decider** (`app/services/self_approval.py`; owner decision, agreed
  2026-11-22: the system proposes, humans decide, and a decision that fires on trivia protects nothing):
  - the proposer is the **only** owner or admin of the company: they decide their own proposal in **one
    honest step**. They confirm the sentence "Öneren ve onaylayan aynı kişi …"; the server compares it
    exactly, and the approval is recorded with `self_decided: true` and `self_decision_ack` (the sentence).
    A company with one owner would otherwise never be able to move a payment, and making them "approve"
    as if a second person existed would be a ritual.
  - **another** active owner or admin exists and the amount still owed is **above the company's
    materiality threshold** (`docs/approval-thresholds.md`): the proposer may **not** approve it (403, with
    the threshold and its basis in the sentence). The proposal waits for the other decider, who decides it
    like anyone's (`self_decided: false`). The proposer may still withdraw it, or reject it.
  - another decider exists and the amount is **at or below** the threshold: the proposer may decide, with
    the same one-step confirmation, recorded the same way. A trivial amount does not need a colleague.
  - an amount in a currency other than the threshold's cannot be compared (no exchange rate is kept) and
    counts as above it.
  - rejecting one's own proposal needs no confirmation and is recorded with `self_decided: true`.
- Until it is approved nothing changes: the radar, the base forecast and the reports keep the date the
  documents gave. A rejected or withdrawn proposal changes nothing and keeps its reason.
- Only the person who proposed may withdraw, and only while it waits. A decision is made once.
- One open proposal per payment. Only payables with a due date and money still owed can be moved,
  to a date from today to one year ahead. Receivables are never moved: their date is not ours to set.
- Every proposal and decision is the row itself: who, when, for which date, and why. Each step also leaves a decision record (`kind=plan_change`, outcome `proposed`, `approved`, `rejected` or `withdrawn`); an owner or admin who decides their own proposal leaves `proposed` and `approved`, both theirs, and the approval carries `self_decided: true` and the confirmed sentence.

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
  button is "Planı değiştir" (propose and approve in one step), with the line that proposer and approver
  being the same person is recorded. When the server says another decider must approve (above the
  threshold), the proposal is left waiting and the page says so. The server's own refusal sentence is
  shown as it is.
- `/onay`: a third list, the proposals waiting. An owner or admin approves or rejects with an optional
  reason; for their own proposal the approve button reads "Öneren ve onaylayan aynı kişi: onaylıyorum"
  (or is replaced by the explanation, above the threshold with a second decider); anyone else sees that the
  decision belongs to an owner or admin, and the proposer may withdraw.
- The list route also tells the caller, per proposal, what they may do with their own (`self_decision`:
  `acknowledge`, `blocked` or null) and carries the sentence to confirm (`meta.self_decision_ack`).

## The same rule elsewhere

The self-approval rule is for approve-type decisions with a separate proposer. Today that is only this one.
Category rules and month close are decided by the one person who acts (`require_decider_or_smmm`,
`require_smmm`: there is no proposal step to approve), held ledger entries have the system as proposer and the
authority matrix as decider, and a held row, document or account question is an answer, not a proposal. A new
decision with a proposer must call `self_approval.assess`.

## Needs a human review (CLAUDE.md DISPATCH)

The role checks are access logic under `backend/app/`. A person must review them before they ship.
