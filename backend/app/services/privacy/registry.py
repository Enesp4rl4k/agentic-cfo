"""The personal-data registry: what personal data this system holds, why, where it goes, how long.

This is the machine-readable source of `docs/kvkk/veri-envanteri-uretilen.md` (rendered by
`app.services.privacy.inventory_doc`) and of the "what is sent to third parties" view in the product.
Nothing here is legal advice: the legal bases, the retention periods and the cross-border position are
OPEN QUESTIONS for a lawyer (`docs/kvkk/avukata-sorular.md`); this module records what the CODE does and
the conservative default chosen meanwhile.

Three tests keep it honest (`tests/test_privacy_registry.py`):

* every table in the models is either described in `registry_tables.TABLES` or declared free of personal
  data (`NO_PERSONAL_DATA`, with a reason): a new table fails by name;
* every column whose name looks personal (email, phone, iban, tckn, vkn, name, address, ip, ...) is
  registered or declared `NOT_PERSONAL` with a reason: a new column fails by name;
* every registered column exists, and every personal column of an organisation's table is erased or
  scrubbed by `org_erasure` (the erasure proof test then checks the rows really are gone).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Subject(StrEnum):
    """Whose data it is."""

    MEMBER = "member"                # a person with an account in the product
    COUNTERPARTY = "counterparty"    # a supplier / customer / payee in the company's records; may be a natural person
    COMPANY = "company"              # the customer company; a sole trader's company name is a person's name
    ACCOUNTANT = "accountant"        # an external accountant (SMMM) using the portal
    ANYONE = "anyone"                # free text and uploaded documents: whoever appears in them


class Category(StrEnum):
    """What kind of personal data a column holds (ranking them legally is the lawyer's job)."""

    IDENTITY = "identity"            # a name
    CONTACT = "contact"              # e-mail, phone, WhatsApp
    NETWORK = "network"              # IP address, browser string
    TAX_ID = "tax_id"                # VKN / TCKN (a sole trader's VKN is their TCKN), IBAN
    FREE_TEXT = "free_text"          # descriptions, notes, messages: may contain any of the above
    DOCUMENT = "document"            # raw text or file of an uploaded document
    PSEUDONYM = "pseudonym"          # an id that names a person only through another table
    CREDENTIAL = "credential"        # a secret tied to a person (hash, token, key): never exported


class Retention(StrEnum):
    BOOKS = "books"              # accounting record: statutory period, kept by default (lawyer question Q2)
    ACCOUNT = "account"          # lives while the account / organisation lives; erased on request
    OPERATIONAL = "operational"  # operating record: a retention job purges it by age
    EPHEMERAL = "ephemeral"      # lives in a cache with a time-to-live
    PROOF = "proof"              # evidence of an erasure or a purge; carries no personal data


class Flow(StrEnum):
    """A third party the data can reach."""

    LLM = "llm_provider"
    SMTP = "smtp_provider"
    SLACK = "slack_webhook"
    WHATSAPP = "whatsapp_twilio"
    STRIPE = "stripe"
    SSO = "sso_provider"
    SENTRY = "sentry"


@dataclass(frozen=True)
class ThirdParty:
    name: str
    sends: str
    masked: bool
    where: str
    switch: str  # how it is off / on, in the code's own terms
    question: str


THIRD_PARTIES: dict[Flow, ThirdParty] = {
    Flow.LLM: ThirdParty(
        "LLM provider (default DeepSeek, an OpenAI-compatible endpoint set by LLM_BASE_URL)",
        "counterparty/vendor names, transaction descriptions, uploaded-document text (up to 8,000 characters per "
        "extraction call, and 1,800-character chunks for embeddings), the company name and the user's free-text "
        "questions with the chat history",
        False,
        "app/platform/model_gateway.py, app/services/rag_service.py (PR #68 section 4 lists every call)",
        "no key, or a `llm-placeholder-*` key, makes no network call; there is no per-organisation switch",
        "Q1: cross-border transfer basis (KVKK Art. 9) for the provider chosen, and whether names, tax numbers and "
        "IBANs must be masked before the call. No masking exists on master.",
    ),
    Flow.SMTP: ThirdParty(
        "SMTP provider (default smtp.gmail.com)",
        "recipient address, subject and body of every outbox e-mail: alerts, briefings, invitations, reset links",
        False, "app/services/outbox_transport.py", "SMTP settings; unset means nothing is sent",
        "Q1: provider location; whether a Turkish SMTP provider is required.",
    ),
    Flow.SLACK: ThirdParty(
        "Slack / Teams / custom webhook (only when the company configures one)",
        "alert text, which may name a counterparty", False, "app/services/outbox_transport.py",
        "a webhook URL set by the company in its alert preferences", "Q1: processor terms; the customer's own choice.",
    ),
    Flow.WHATSAPP: ThirdParty(
        "WhatsApp (Meta) / Twilio (only when the company configures a number)",
        "the recipient's phone number and the alert text", False, "app/services/notification_service.py",
        "a WhatsApp number in alert preferences plus provider credentials", "Q1: processor terms; the customer's own choice.",
    ),
    Flow.STRIPE: ThirdParty(
        "Stripe (billing)", "organisation name, billing contact, customer and subscription ids", True,
        "app/services/stripe_billing.py", "STRIPE_* settings", "Q1: cross-border basis; Stripe's own controller role.",
    ),
    Flow.SSO: ThirdParty(
        "Microsoft / Google / GitHub sign-in (only when a person signs in with it)",
        "the provider authenticates the person and returns their id, e-mail and name", True, "app/services/sso.py",
        "SSO_* settings", "Q1: none beyond the provider's own role.",
    ),
    Flow.SENTRY: ThirdParty(
        "Sentry error tracking (off unless SENTRY_DSN is set)",
        "error events with keys scrubbed; log lines at ERROR level may name a counterparty", True,
        "app/services/sentry_monitoring.py", "SENTRY_DSN; unset means no events leave",
        "Q1: EU region and a processing agreement before it is turned on.",
    ),
}


@dataclass(frozen=True)
class Table:
    purpose: str
    subject: Subject
    retention: Retention
    columns: dict[str, Category]
    flows: tuple[Flow, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class Store:
    """A place that is not a database table."""

    key: str
    holds: str
    where: str
    subject: Subject
    retention: Retention
    ttl: str
    erased_by: str
    flows: tuple[Flow, ...] = ()


# A column whose name looks personal but is not, with the reason. Every other personal-looking column is
# registered in `registry_tables.TABLES`.
NOT_PERSONAL: dict[str, str] = {
    "alert_rules.name": "a label the user gives a threshold rule",
    "trigger_definitions.name": "a label the user gives an automation rule",
    "connector_connections.display_name": "a label for the connection (a repository or shop name)",
    "erp_integrations.display_name": "a label for the integration",
    "organizations.ip_whitelist_enabled": "a switch, not an address",
    "pilot_invites.code": "a random invite code",
    "email_ingest_messages.address_id": "a foreign key to the company's inbound address row",
    "users.email_verified_at": "a timestamp",
}

PERSONAL_NAME_TOKENS = frozenset({
    "email", "emails", "phone", "telefon", "whatsapp", "iban", "tckn", "vkn", "name", "names", "address",
    "adres", "ip", "unvan", "vergi", "sender", "recipient", "recipients", "counterparty", "vendor",
    "firma", "whitelist", "tax",
})


def looks_personal(column: str) -> bool:
    """True when a column name carries a token that usually means personal data."""
    return any(tok in PERSONAL_NAME_TOKENS for tok in re.split(r"[_\W]+", column.lower()) if tok)
