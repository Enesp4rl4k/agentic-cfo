# Onboard a new pilot company

Before the first company only: [pilot-acceptance-checklist.md](../pilot-acceptance-checklist.md) is fully ticked.

Registration is **closed** for the pilot (`REGISTRATION_MODE=invite_only`, the default): nobody can create an
account or a company by themselves, on the register page, through the API or through SSO. A new company
gets in by exactly one route: a platform operator invites its owner. Code: `services/pilot_invites.py`.

## Before the call

1. The owner of the company (name, e-mail address) and the accountant (SMMM), if any.
2. Mail works: a received verification/invitation mail on a real mailbox (checklist section D). With no mail
   sender configured the invitation is **not created** (the API answers 503 "davet iletilemedi") and the
   server refuses to start in production in the first place ([mail.md](../mail.md)).
3. You are a platform operator (`PLATFORM_OPERATOR_EMAILS`, [platform-operators.md](platform-operators.md)).

## Steps

1. **Issue the invitation** (operator): `POST /api/v1/pilot/invite/generate` with
   `{"email": "<owner's address>", "company_name": "<legal or trade name>"}`. The answer says
   `mail_delivery` (`live`, or `dev_recorded` on a development machine). The link is e-mailed to that address
   and is **not shown to you**: it is stored only as a digest, so nobody (you included) can register in the
   owner's name. Valid 14 days (`PILOT_INVITE_EXPIRE_DAYS`), single use. A second invitation to the same
   address replaces the first. List and revoke: `GET /api/v1/pilot/invites`, `DELETE /api/v1/pilot/invite/{id}`
   (states: valid, used, expired).
2. **The owner opens the link** (`/auth/pilot-invite?token=...`), sees the company name and their address,
   chooses a name and a password and presses the button. In one step they get the account (e-mail already
   proven: the link came to it), become the **owner of a new company** named in the invitation, and are
   signed in. No separate "create workspace" step; `POST /org/create` is refused to everyone but operators.
3. Base currency is asked before the first upload completes (`/org/base-currency`).
4. **The owner invites the team** from the company settings (`POST /org/invite`: roles admin, cfo, analyst,
   viewer, smmm; one owner per company). An invitation e-mail the system cannot send is refused, not faked.
   The accountant joins the *client's* company with role `smmm`; they do not become owner.
5. Briefing recipients: `PUT /org/me/briefing-recipients`. With an accountant on the company, briefing mail is
   held until the accountant releases it: explain that.
6. IP allow-list: leave off at first. If the owner wants it, they set it from the office address and read
   [ip-allowlist-lockout.md](ip-allowlist-lockout.md).
7. First upload: a bank statement (`.xlsx`, `.csv`, `.pdf`) or an e-Fatura `.xml`. Maximum 10 MB. Sit with
   them until the radar shows a number and the held rows (if any) are answered.
8. Tell them: what is held and why; that numbers older than seven days are labelled "last known"; where to
   write when something looks wrong ([wrong-number.md](wrong-number.md)); that backups are nightly (up to a
   day of data can be lost in a restore); who to call (`SUPPORT_CONTACT`, also shown on the register page).
9. KVKK: the privacy notice and processing agreement documents are in PR #68 (drafts, need a lawyer). Do not
   hand them over as final. Tell them the LLM provider question ([audit D6](../operational-readiness-2026-11.md)).

## The very first operator

The operator list is an e-mail list; the account must exist. With registration closed nobody can create it,
so on the host, once: `dc exec backend python scripts/issue_pilot_invite.py --email you@example.com.tr
--company "Tiphys Operasyon"`, then open the mailed link. (This makes you the owner of an operations company,
which is also where you can try the product. Host access is a larger power than an operator's.)

## A stranger finds the register page

They see "Tiphys şu an yalnızca davetle kullanılabiliyor" and, when `SUPPORT_CONTACT` is set, where to ask.
The API refuses `POST /auth/register` with 403 and creates nothing, whatever the address. To watch for
anything unexpected: `select email, created_at from users order by created_at desc limit 20;`.

## After

- Note the company's id and the date; add them to your pilot list (not in the repository).
- Day 2 and day 7: check `/api/v1/ready` and that the first Monday briefing arrived
  ([briefing-not-sent.md](briefing-not-sent.md)).

## Not verified

The sequence is covered by `backend/tests/test_pilot_onboarding.py` (API level, no real mail) and has not been
walked through on a running host with a real mailbox.
