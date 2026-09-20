"""Product identity, in one place.

The name and domain used to be typed directly into report footers, alert
templates, Slack messages and — worst of all — the KVKK/GDPR processing-activity
record, which published `privacy@clevelai.com` as the data controller's contact
address for a domain the project does not own. A compliance module that states a
contact nobody reads is worse than one that admits it is unconfigured.

So: every user-visible mention of the product resolves through here, and the
contact addresses default to *empty* rather than to a plausible-looking lie.
Renaming the product is an env change, not a grep.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.config import get_settings


@dataclass(frozen=True)
class Brand:
    """Resolved product identity for one running instance."""

    name: str
    domain: str
    app_url: str
    contact_email: str
    privacy_email: str
    dpo_email: str

    @property
    def has_domain(self) -> bool:
        """False when no real domain is configured.

        Callers that would otherwise print a contact address must check this and
        say "not configured" instead of inventing one.
        """
        return bool(self.domain)

    @property
    def legal_name(self) -> str:
        """Name for document footers and compliance records."""
        return f"{self.name} Platform" if self.name else "Platform"


def _address(local: str, domain: str) -> str:
    return f"{local}@{domain}" if domain else ""


@lru_cache
def get_brand() -> Brand:
    s = get_settings()
    domain = (s.brand_domain or "").strip().lower()
    return Brand(
        name=(s.brand_name or "").strip(),
        domain=domain,
        app_url=(s.brand_app_url or "").strip().rstrip("/"),
        contact_email=(s.brand_contact_email or "").strip() or _address("hello", domain),
        privacy_email=(s.brand_privacy_email or "").strip() or _address("privacy", domain),
        dpo_email=(s.brand_dpo_email or "").strip() or _address("dpo", domain),
    )
