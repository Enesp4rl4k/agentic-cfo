# Who is asked, and above what: thresholds proportional to the company

Principle (owner, agreed 2026-11-22): the system proposes, humans decide; managers stay in the loop;
decisions are FEW and IMPORTANT. An approval that fires on trivia protects nothing, and a company with one
owner and an outside accountant must not be put through a large company's workflow. Every decision is still
recorded with who decided and on what basis. A fixed lira amount cannot serve both a 2 million and a
200 million lira company, so materiality is measured against the company itself.

## Inventory: every threshold and gate that decides whether a human is asked

| Where | Gate | Value | Unit | Who is asked | Scales with the company? |
|---|---|---|---|---|---|
| `platform/authority_matrix.py` `high_value` | an entry above the amount needs approval | was 100.000 fixed; now the organisation's materiality threshold | lira (kuruş) | owner | **now yes** (this change) |
| same, `low_confidence` | classification confidence below | 0.80 | share | smmm (owner/admin/cfo when there is none) | no: a quality gate |
| same, `unclassified`, `fixed_asset`, `related_party` | method "varsayılan"; fixed asset; related party | flags | n/a | smmm; smmm; owner | no: integrity / statute |
| `platform/policies.py` `CONFIDENCE_AUTO_PROCEED_MIN`, `config.agent_auto_proceed_min_confidence`, per-role run configs | an agent run waits for review below | 0.80 (CEO config 0.75) | share | the person on /onay | no: a quality gate (CLAUDE.md) |
| `platform/policies.py` reflection hold / warn | reflection holds / warns | 0.55 / 0.70 | share | owner | no: quality |
| `api/data_quality.py` `MIN_AUTO_PROCEED_SCORE` | file health score to auto-proceed | 40 | points | uploader | no: data quality |
| `agents/anomaly_agent.py` | z-score, IQR, duplicate window, vendor concentration, round numbers, spike | 2.5, 2.5, 3 days, 40%, 85%, 2x 3-month mean | statistics | nobody is asked: shown as notices | already relative to the company's own data |
| `api/alerts.py`, `services/alert_router.py` | aggregation, escalation, dedup | 3, 0.75, 4 h | counts / score | notices | not a decision |
| `services/briefing_held.py`, `config.radar_held_material_ratio` | the briefing's headline names the held documents | 10% of the week's outflow | share | owner reads | already proportional |
| `services/ledger_documents.py` | possible duplicate invoice held | 3 days; same number within 31 | days | the person on /onay | no: integrity, whatever the amount |
| `services/reconciliation.py` | a bank movement proposed as settling an invoice | not earlier than 3 days before it | days | the person on /onay | no: integrity |
| `services/held_rows.py`, `held_direction.py`, `account_identity.py`, `balance_reverify.py` | unreadable row, currency, direction, account identity, failed reconciliation | no amount | n/a | the person on /bekleyen-kayitlar, /onay | **never** scales away |
| `services/payment_plan.py` | every payment-date change needs an owner or admin | no amount; date within 366 days | days | owner or admin | no; but **self-approval** now reads the threshold |
| `services/donem_kilidi.py` / `api/smmm_onay.py` | month close | no amount; not future, not already closed | n/a | smmm (owner/admin/cfo when there is none) | no: accounting sign-off |
| `services/runway.py`, `config.radar_balance_stale_after_days` | months of history for a runway, "last known" balance | 3 months; 7 days | months / days | notices | no |

`services/ledger.py` and the parsers contain no approval amount. `double_entry.ONAY_LIMIT_TRY` is a dead
constant (the policy above is what runs).

## The proportional rule (`services/materiality.py`)

```
threshold = 5% x average monthly outflow of the last complete months in the ledger (3 to 6 months,
            months with no outflow ignored, a single headline currency required)
            rounded half up to two significant figures, never below 5.000 and never above 1.000.000
```

* **Fallback:** with fewer than 3 such months, or no single currency, the basis is the monthly outflow the
  company declared in the size answers (band middles 250.000 / 1.500.000 / 10.000.000), labelled "beyan
  edilen". With neither, there is no proposal and the old fixed 100.000 keeps applying.
* **Examples:** 2 million a year is 166.667 a month, 5% is 8.333, so **8.300**. 200 million a year is 16.67
  million a month, so **830.000**. A 500 million company would compute 2.08 million and be held to the
  ceiling, **1.000.000**. A 100.000 company would compute 417 and be raised to the floor, **5.000**.
* **Never silent:** the computed value is a proposal. `GET /org/me/materiality` shows it to an owner or admin
  with its basis ("Son 6 tam ayın aylık ortalama çıkışı X'in %5'i = Y"); until they acknowledge it
  (`POST .../acknowledge`, which must carry the exact amount they were shown) the fixed amount that always
  applied still does, for new and existing organisations alike. The acknowledged value is stored with its
  basis on the organisation (`materiality_applied`) and every acknowledgement is a decision record
  (`kind=materiality`).
* **Override:** the owner or admin can set their own amount (`PUT .../materiality`), recorded with the reason,
  before and after.
* **Where it applies:** the authority matrix's `high_value` rule in the default policy (its note carries the
  basis), and the self-approval rule. A policy the organisation saved itself is theirs and is not rewritten.
* **Only materiality.** Gates that protect the books (unreadable rows, currency, direction, account identity,
  reconciliation, possible duplicates) are questions about one upload; a test pins that their modules never
  read the threshold.
* The partial first or last month of a ledger can understate the average; the months used are shown in the
  basis, the floor protects the small end, and a person confirms before anything applies.

## Self-approval

See `docs/payment-plan-approval.md` ("When the proposer is also the decider").

## An outside accountant (smmm)

* `GET /org/me` carries `has_smmm` (an active user holds an smmm membership), `briefing_to_smmm` and the size
  profile's defaults, so screens adapt (no "send to the accountant" when there is none; a hint to invite one).
* **Month close** in an owner + smmm company: the accountant closes (it is their sign-off on the books); the
  owner may not while an accountant exists, sees the closed months, and the record names the accountant.
  With no accountant the owner closes. The accountant does not propose payment dates, decide the materiality
  threshold or the briefing's recipients: those are the company's.
* **Workload:** `GET /smmm/workload` lists the organisations where the caller holds an smmm membership with
  entries awaiting approval, last month's close and briefings held for their release. It reads memberships and
  every query is scoped to those organisation ids (tested with an accountant in two organisations, another
  accountant's, and one where the caller is only an analyst).
* **Briefing:** the owner can choose, as a recorded standing preference, that the Monday briefing also goes to
  the accountant. This only adds the recipient to the existing outbox flow (held until the accountant
  releases it); there is no new way to send.

## Profile defaults (`services/size_profile.profile_defaults`)

Defaults, never locks; nothing is removed from a larger profile. micro: the menu is simplified, the one-tap
button leads /onay, the briefing is suggested to the accountant. small: simplified menu with the finance
screens, one-tap first. medium: full menu, no suggestions. The proportional threshold itself is what makes the
owner of a small company be asked less often.
