# Outgoing mail: configuration and DNS

Everything the application sends (verification, password reset, invitations, the Monday briefing, delivery-failure
notices) goes through the outbox (`services/outbox.py`) and one SMTP sender (`services/outbox_transport.py`).
Nothing is configured by default: with no `SMTP_USER` and `SMTP_PASSWORD` every message ends as a failed outbox row
with the reason `smtp_not_configured`. Because registration is by invitation and verification is required, the
server **refuses to start** under `APP_ENV=production|staging` without a sender (`mail_required_no_sender`); under
other environments it warns. In development the sender is a recorded no-op and every answer says
`mail_delivery: dev_recorded`. See [runbooks/login-and-email.md](runbooks/login-and-email.md).

## Settings

| Variable | Meaning |
|---|---|
| `SMTP_HOST`, `SMTP_PORT` | provider's submission endpoint (default `smtp.gmail.com`, 587; set your provider's) |
| `SMTP_USER`, `SMTP_PASSWORD` | provider credentials; both must be set or the sender is "not configured" |
| `NOTIFICATION_FROM` | the From address; must be on a domain you control (default `noreply@aicfo.app` is not yours) |
| `EMAIL_VERIFICATION_REQUIRED` | `true` (default) needs a working sender; `false` lets people sign in unverified |
| `OUTBOX_TRANSPORT` | `auto` (live on Postgres, a recorded no-op on SQLite), `live`, `noop` |
| `FRONTEND_URL`, `BRAND_APP_URL` | the links inside every mail; must be the public app URL (preflight refuses localhost) |

## DNS for the sending domain (decision D2: the domain and the provider are the owner's)

Do these for the domain in `NOTIFICATION_FROM` before the first invitation. Exact values come from the provider.

1. **SPF**: a TXT record on the domain listing the provider, e.g. `v=spf1 include:<provider> -all` (one SPF record only).
2. **DKIM**: the provider gives one or more selector records (CNAME or TXT) that sign the mail; add them as given.
3. **DMARC**: a TXT record at `_dmarc.<domain>`. Start with monitoring, tighten after a week of clean reports:
   `v=DMARC1; p=none; rua=mailto:<an address you read>`, later `p=quarantine`.
4. **Return-Path / bounce domain** if the provider offers a custom one (better alignment).
5. Test: send an invitation to a Gmail and an Outlook address; open "show original" and read `spf=pass dkim=pass dmarc=pass`.

## What the application does not do

- It does not see bounces or spam complaints. SMTP accepts the message and the outbox marks it `sent`; a later
  bounce is visible only in the provider's dashboard. Read it weekly during the pilot (audit item 7.3).
- It retries a failing send every five minutes up to five attempts, then marks it `failed` with the reason and
  notifies the company once per outage.
- Messages are written with a unique key, so a restart or a second scheduler cannot send the same message twice.

## Provider location

A provider outside Turkey receives every recipient address and message body (briefings contain figures of the
company). That is a transfer under KVKK: a decision for the owner and a lawyer, recorded with D2.
