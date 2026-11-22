# Locked out by the IP allow-list (break-glass)

A company's owner can restrict access to listed addresses (`PUT /api/v1/security/ip-whitelist`). Someone
outside the list gets a 403 that says the company restricts access by IP address. If the owner is locked
out too, the platform removes the list. Details: [auth-abuse-and-outbound.md](../auth-abuse-and-outbound.md) section 6.

## Check

- The user's current public address (ask them: "what is my IP" in a browser) is not on the list.
- Behind the proxy, `TRUSTED_PROXY_COUNT=1` (or the CIDRs) must be set, or the app sees the proxy's address
  for everyone. Enabling a list is refused in that state, but a later proxy change can break it.
- `SUPPORT_CONTACT` is what the 403 tells people to write to. Unset it says "platform yöneticinize başvurun".

## Fix (platform operator only: your e-mail is in `PLATFORM_OPERATOR_EMAILS`)

1. Confirm the request comes from the company's owner (call back on a number you already hold).
2. Log in as the operator and call:
   ```bash
   curl -X DELETE -H "Authorization: Bearer <your access token>" \
        https://<API_DOMAIN>/api/v1/platform/orgs/<org id>/ip-whitelist
   ```
   The list is cleared and a `security_setting_change` decision records who, before and after
   (`break_glass: true`). The owner then sets a correct list from an allowed address.
3. If no operator exists (`PLATFORM_OPERATOR_EMAILS` empty) add one first: [platform-operators.md](platform-operators.md).

## Not verified

The route and its record are covered by `tests/test_ip_allowlist.py`; not exercised through the proxy.
