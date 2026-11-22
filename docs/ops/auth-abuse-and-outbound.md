# Auth abuse, client address, outbound URLs

Operational notes for three controls. Code: `backend/app/core/client_ip.py`,
`backend/app/core/outbound.py`, `backend/app/services/password_reset.py`,
`backend/app/services/email_verification.py`, `backend/app/api/auth.py`.

## 1. Which address is the client? (`TRUSTED_PROXY_CIDRS` / `TRUSTED_PROXY_COUNT`)

`X-Forwarded-For` is written first by the client, so its first value is whatever an attacker
types. One helper, `app.core.client_ip.client_ip(request_or_websocket)`, is used by the rate
limiter, the audit log, the password-reset / verification limits and anything else that needs an
address.

| Setting | Meaning |
|---|---|
| neither set (default) | Trust no proxy. The socket peer address is the client; the header is ignored. |
| `TRUSTED_PROXY_CIDRS=10.0.0.0/8,fd00::/8` | The header is read only when the socket peer is inside one of these networks. Hops inside them are skipped from the right; the first address outside is the client. Wins over the count when both are set. |
| `TRUSTED_PROXY_COUNT=1` | Exactly N proxies sit in front of the app. The chain is `X-Forwarded-For` entries followed by the peer; the client is the N+1-th from the right. |

An entry that is not an IP address ends the walk (the hop to its right is used). A malformed
CIDR in the setting is an error, not skipped.

**Behind the planned reverse proxy (one hop: Caddy / nginx / an ingress controller):** set
`TRUSTED_PROXY_COUNT=1` if the proxy is the only thing that can reach the app port, or
`TRUSTED_PROXY_CIDRS=<the proxy's network>` if other hosts can too. The proxy must *append*
(not forward untouched) the address it sees: Caddy and nginx (`$proxy_add_x_forwarded_for`) do;
a proxy configured to pass the client's header through unchanged must be fixed. Leaving the
default behind a proxy makes every request come from the proxy's address (one shared rate-limit
bucket), which is safe but coarse. Never expose the app port to the internet when a count is set.

## 2. Mail flooding and enumeration

**Cool-down.** At most one mail per address and kind in `AUTH_MAIL_COOLDOWN_MINUTES` (default
15) for: password reset, e-mail verification (resend) and "you already have an account"
(register). Any number of requests, from any number of IPs, produce at most 4 mails an hour per
kind per victim. A request inside the cool-down gets the same answer and sends nothing; the
earlier mail's link is still valid (reset 30 minutes, verification 48 hours), so the real owner
is not locked out by someone else's requests. The cool-down must stay below the reset lifetime.

**Per (address, IP) allowance.** `PASSWORD_RESET_PER_EMAIL_PER_HOUR` (default 3) is counted per
address *and* client IP: one IP cannot use up an address's allowance for others. Per-IP limits
of the middleware still apply (forgot-password / resend 10 per hour, register and login 5 per
minute).

**Register.** With e-mail verification required (default): `201 {accepted, verification_required}`,
identical body, status and a 0.5 s minimum duration (and the same bcrypt work) for new and
existing addresses. A new address is mailed the verification link; an existing, active address
is mailed (once per cool-down) "you already have an account" with the sign-in and forgot-password
pages (no token; never a verification link, which would verify a squatter's account). A
deactivated account gets nothing. Login runs a bcrypt comparison against a dummy hash for an
unknown address. With `EMAIL_VERIFICATION_REQUIRED=false` (a deployment with no mail) there is
no private channel, so register still answers "already registered" with 400.

## 3. What a password reset ends

* every session (`users.token_version` +1), every other reset link;
* the user's personal API key (`users.api_key`, one per user, used as `X-API-Key`).

The audit row `auth.password_reset_completed` carries counts only:
`api_keys_revoked` (0 or 1), `sessions_ended: "all"` (sessions are stateless JWTs, there is no
list to count), never a key or token.

**Not revoked (not tied to the person):** organisation credentials: ERP tokens
(`erp_integrations.access_token_enc`), connector secrets (`connector_connections.secret_enc`),
the organisation's Slack and webhook URLs, the accountant portal. A person leaving is handled by
deactivating the member and rotating those in the integrations screens.

## 4. Outbound requests to a user-supplied URL (`app.core.outbound`)

All of these go through `outbound.request` (or `fetch_import`): https only; strict parse (no
user-info, whitespace, backslash, zone id); numeric host spellings that are not a canonical
dotted quad / IPv6 refused (`127.1`, `2130706433`, `0x7f.0.0.1`, `0177.0.0.1`, `0`); the name is
resolved and every address must be public (loopback, RFC 1918, link-local incl. 169.254.169.254,
CGNAT, unique-local, IPv4-mapped / NAT64 / 6to4, unspecified, multicast, broadcast, reserved);
the connection is pinned to a validated address with the original Host and TLS SNI/certificate
name (DNS rebinding); no redirects; no proxy from the environment; 5 s connect, 15 s total
(30 s for an import); response body not read unless an import asks, then capped at 10 MB.

| Call site | URL from | Status |
|---|---|---|
| `AlertDispatcher.dispatch_slack` / `dispatch_webhook` (outbox sender; Slack alerts, trigger webhooks, notification Slack, connection tests) | org preference, trigger rule | guarded |
| `connectors/crm_export.py` `csv_url` | integration config | guarded (`fetch_import`) |
| `connectors/hr_export.py` `csv_url` | integration config | guarded (`fetch_import`) |
| `api/org.py` `logo_url` | org settings | stored only, never fetched by the server |
| Teams / custom webhook URLs in `api/integrations_extended.py` | settings | stored/previewed only, no request made |
| ERP (Paraşüt), banks, SSO providers, GIB, TCMB, GitHub, WhatsApp/Slack bot APIs, LLM base URL, MCP client | code constants or operator environment | not user URLs; listed in `_FIXED_HOST_HTTP_CLIENTS` of `tests/test_architecture_fitness.py`, which fails for any new httpx module not classified |
