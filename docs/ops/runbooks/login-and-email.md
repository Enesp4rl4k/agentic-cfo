# A user cannot log in, or did not get the e-mail

Code: `api/auth.py`, `services/email_verification.py`, `services/password_reset.py`, `services/outbox.py`.

## Check

1. **Is mail configured at all?** `curl -s https://<API_DOMAIN>/api/v1/ready`: `checks.outbox` with
   `failed_24h > 0`, or `dc logs backend | grep -i 'no mail sender'` (startup warning `no_mail_sender`).
   Without `SMTP_USER` and `SMTP_PASSWORD` every invitation, verification, reset and briefing ends as a
   failed outbox row, and the user was still told "check your e-mail" (that answer is identical for every
   address on purpose). This is the usual cause.
2. **What happened to this user's mail?** The outbox keeps the reason; look up by the user's address
   (this is operator access to personal data: do it, do not copy it anywhere):
   ```bash
   psql_app -c "select created_at, kind, status, attempts, last_error from outbox_messages
                where recipient = '<address>' order by created_at desc limit 5;"
   ```
   `smtp_not_configured` = item 1. `destination_*` = the receiving server refused the address.
   `pending` older than 15 minutes = the sender is not running (`degraded` scheduler on `/ready`; see
   [briefing-not-sent.md](briefing-not-sent.md)). `sent` = it left; ask the user to check spam; see
   [mail.md](../mail.md) for SPF/DKIM.
3. **Account state:**
   ```bash
   psql_app -c "select id, is_active, email_verified_at is not null as verified, last_login_at
                from users where email = '<address>';"
   ```
   Not verified and `EMAIL_VERIFICATION_REQUIRED=true`: the account cannot sign in or act.
4. **Wrong password / locked by the rate limit:** login is limited to 5 requests a minute per client
   (`middleware/rate_limit.py`); wait a minute. Behind the proxy, `TRUSTED_PROXY_COUNT=1` must be set or
   every user shares one bucket (startup warns `no_trusted_proxy`).
5. **Locked out of one company only** (403 mentioning the IP address): [ip-allowlist-lockout.md](ip-allowlist-lockout.md).

## Fix

- Mail now configured: the user asks again on the sign-in page (`POST /auth/resend-verification` or
  `/auth/forgot-password`). At most one mail per address and kind every 15 minutes (`AUTH_MAIL_COOLDOWN_MINUTES`);
  the earlier link stays valid (reset 30 minutes, verification 48 hours).
- Mail cannot be configured today and the person must work: mark the address verified by hand (an operator
  decision; the account then signs in with its own password):
  ```bash
  psql_app -c "update users set email_verified_at = now() where id = '<user id>' and email_verified_at is null;"
  ```
  For a reset with no mail the user must wait for mail; there is no operator-set password.
- Never edit `hashed_password`.

## Not verified

The SQL was written from the models (`models/user.py`, `models/outbox_message.py`) and has not been run.
