# Add or remove a platform operator

A platform operator is a user whose e-mail is in `PLATFORM_OPERATOR_EMAILS` (comma separated). They issue
and list pilot invites (the only way a new company gets in, [onboard-company.md](onboard-company.md)), read every
company's pilot feedback, see the detail of `/api/v1/ready` (revision, outbox counts, last backup) and clear an
IP allow-list lock-out
(`api/access.py` `require_platform_operator`). They are **not** members of any company and see no company's
data through these routes. An empty list means nobody can do any of it.

## Add

1. The person gets an account with that address: with registration closed, through a pilot invitation (the first
   operator: `scripts/issue_pilot_invite.py` on the host, see onboard-company.md). An unverified account cannot act.
2. Edit `.env`: `PLATFORM_OPERATOR_EMAILS=owner@example.com.tr,new@example.com.tr`.
3. `dc up -d backend` (the setting is read at process start; no migration).
4. The person signs in and calls a platform route, for example `GET /api/v1/pilot/invites`: 200 = operator,
   403 = the address does not match (case and spaces are normalised; check the spelling).

## Remove

1. Remove the address from `PLATFORM_OPERATOR_EMAILS`, `dc up -d backend`. Their next platform call is a 403.
2. Their existing tokens still work for ordinary routes until they expire (30 minutes access token); to end
   the session at once, rotate `BACKEND_SECRET_KEY` ([rotate-secret.md](rotate-secret.md)) only if the
   departure is hostile (it signs everyone out).
3. If they also owned a company, change that company's owner through the owner's own settings; do not edit
   membership rows by hand.

## Notes

- Operators also receive the **operator alerts** by e-mail (failed backup, failing destination, a job that keeps
  failing, a caught-up briefing, startup warnings): one mail per alert and window (`OPERATOR_ALERT_COOLDOWN_MINUTES`).
  Fixed text, identifiers only. See [briefing-not-sent.md](briefing-not-sent.md) and [../mail.md](../mail.md).

- Keep at least two operators, so one person on holiday cannot block a lock-out recovery.
- Operator actions that change a company are recorded as decisions (IP allow-list break-glass records who).
- Access to the server and the database is a separate, larger power: whoever can run `docker compose` can read
  everything. Keep that list shorter than the operator list.

## Not verified

The 403 check depends on the route's guard (`dependencies=[Depends(require_platform_operator)]` in `api/pilot.py`);
no real operator has been added on a host.
