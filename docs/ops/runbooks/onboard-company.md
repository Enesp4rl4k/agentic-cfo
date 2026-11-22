# Onboard a new pilot company

Before the first company only: [pilot-acceptance-checklist.md](../pilot-acceptance-checklist.md) is fully ticked.

## Before the call

1. The owner of the company (name, address) and the accountant (SMMM), if any.
2. Registration is open today (audit item 1.11): anyone can create an account. Until that is closed, the
   invite does not restrict anything; it only tells you who you expect. Watch `select email, created_at
   from users order by created_at desc limit 20;` for addresses you do not know.
3. Optional invite code: as a platform operator `POST /api/v1/pilot/invite/generate` (`{email, note, count,
   expire_days}`); `GET /api/v1/pilot/invite/validate?code=` checks it. List: `GET /api/v1/pilot/invites`.

## Steps with the owner

1. The owner registers on the sign-in page, opens the verification e-mail (check [login-and-email.md](login-and-email.md)
   if it does not come within a minute; mail must be configured first).
2. They create the company (`POST /org/create`), which makes them its owner. Base currency is asked before the first
   upload completes (`/org/base-currency`).
3. Invite colleagues from the company settings (`POST /org/invite`: roles owner, admin, cfo, analyst, viewer,
   smmm). The accountant joins the *client's* company with role `smmm`; they do not become owner.
4. Briefing recipients: `PUT /org/me/briefing-recipients`. With an accountant on the company, briefing mail is
   held until the accountant releases it: explain that.
5. IP allow-list: leave off at first. If the owner wants it, they set it from the office address and read
   [ip-allowlist-lockout.md](ip-allowlist-lockout.md).
6. First upload: a bank statement (`.xlsx`, `.csv`, `.pdf`) or an e-Fatura `.xml`. Maximum 10 MB. Sit with
   them until the radar shows a number and the held rows (if any) are answered.
7. Tell them: what is held and why; that numbers older than seven days are labelled "last known"; where to
   write when something looks wrong ([wrong-number.md](wrong-number.md)); that backups are nightly (up to a
   day of data can be lost in a restore); who to call (`SUPPORT_CONTACT`).
8. KVKK: the privacy notice and processing agreement documents are in PR #68 (drafts, need a lawyer). Do not
   hand them over as final. Tell them the LLM provider question ([audit D6](../operational-readiness-2026-11.md)).

## After

- Note the company's id and the date; add them to your pilot list (not in the repository).
- Day 2 and day 7: check `/api/v1/ready` and that the first Monday briefing arrived
  ([briefing-not-sent.md](briefing-not-sent.md)).

## Not verified

The endpoint names are from the routers (`api/org.py`, `api/pilot.py`, `api/briefing_recipients.py`); the
sequence was not walked through on a running stack.
