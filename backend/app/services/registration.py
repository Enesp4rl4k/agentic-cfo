"""Who may create an account: one policy, read by every door (register, SSO sign-up, workspace creation).

`REGISTRATION_MODE` (config.py): `open`, `invite_only` (default) or `closed`. In the two restricted modes
an account comes only from an invitation: an organisation invite (`POST /org/invite/accept`, a company
adding a person) or a pilot invite (`POST /auth/register` with its token, a platform operator adding a new
company). Nothing else creates a user or a company, so the answer to "can a stranger who found the domain
sign up" is the same in every door: no.

The refusal is a fact about the deployment, independent of the address, so it can be stated plainly
without telling anybody which accounts exist. `access_request_hint` names where to ask (`SUPPORT_CONTACT`).
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings

CLOSED_MESSAGE = "Tiphys şu an yalnızca davetle kullanılabiliyor."


def mode() -> str:
    return str(get_settings().registration_mode)


def is_open() -> bool:
    return mode() == "open"


def access_request_hint() -> str | None:
    """The contact to ask for an invitation (an address or a URL), when the operator configured one."""
    contact = get_settings().support_contact.strip()
    return contact or None


def refusal_message() -> str:
    hint = access_request_hint()
    return f"{CLOSED_MESSAGE} Erişim için: {hint}" if hint else CLOSED_MESSAGE


def public_view() -> dict[str, Any]:
    """What the sign-up page needs before anybody types anything."""
    current = mode()
    return {
        "mode": current,
        "open": current == "open",
        "invite_only": current != "open",
        "message": None if current == "open" else CLOSED_MESSAGE,
        "contact": None if current == "open" else access_request_hint(),
    }
