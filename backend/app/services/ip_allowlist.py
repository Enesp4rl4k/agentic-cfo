"""The organisation's IP allow-list: parse it strictly, decide who may act in the organisation.

Enforced where an organisation is ACTED IN: `api/auth.get_current_user` (every HTTP request, JWT or
API key) and `api/ws_auth.websocket_caller` (every WebSocket connect and message), using the one
client-address helper (`app.core.client_ip`). Login is not organisation-scoped and is never
refused here; neither are the calls that let a person with two organisations move to the other
(`EXEMPT_PATHS`). The list applies when it is enabled AND non-empty.

Never lock the owner out:
* saving a list that does not contain the caller's current address is refused (409) unless the
  caller sets `confirm_lockout`;
* enabling is refused while the client address cannot be trusted (a proxy header arrives and no
  trusted-proxy setting is configured: the "client" would be the proxy), see `activation_problem`;
* break-glass: a platform operator (`PLATFORM_OPERATOR_EMAILS`) clears the list with
  `DELETE /api/v1/platform/orgs/{org_id}/ip-whitelist`; it is recorded as a decision.
"""
from __future__ import annotations

import ipaddress
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MAX_ENTRIES = 50
def recovery_sentence() -> str:
    """How a locked-out person gets back in (tr + en), from configuration."""
    from app.config import get_settings

    contact = get_settings().support_contact.strip()
    tr_who = f"destek: {contact}" if contact else "platform yöneticinize başvurun"
    en_who = f"contact {contact}" if contact else "contact your platform administrator"
    return (
        "Şirketin sahibi (owner) listeyi izin verilen bir adresten değiştirebilir. Sahip de dışarıda kaldıysa "
        f"listenin kaldırılmasını platform tarafından isteyin ({tr_who}). "
        "/ The company owner can change the list from an allowed address. If the owner is locked out too, "
        f"ask the platform to remove it ({en_who})."
    )


def refusal_text() -> str:
    """The 403 text: what happened, why, who can change it, how to recover. Never the list itself."""
    return (
        "Bu şirket erişimi IP adresine göre kısıtlıyor ve şu anki adresiniz izin listesinde değil. "
        "/ This company restricts access by IP address and your current address is not on the list. "
        + recovery_sentence()
    )


# Calls a person needs to reach ANOTHER organisation or read who they are; never org-scoped data.
EXEMPT_PATHS = ("/api/v1/org/memberships", "/api/v1/org/switch", "/api/v1/auth/me")

_Net = ipaddress.IPv4Network | ipaddress.IPv6Network
_FORWARDING_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip")


class AllowListError(ValueError):
    """A list that cannot be saved; the message says which entry and why."""


def normalise(cidrs: list[str]) -> list[str]:
    """Strict: IPv4/IPv6 addresses or networks, no host bits, no catch-all, at most MAX_ENTRIES, no duplicates."""
    out: list[str] = []
    for raw in cidrs:
        text = raw.strip()
        if not text:
            continue
        try:
            net = ipaddress.ip_network(text, strict=True)
        except ValueError:
            raise AllowListError(f"Geçersiz CIDR formatı: '{text[:60]}'") from None
        if net.prefixlen == 0:
            raise AllowListError("0.0.0.0/0 ve ::/0 herkese izin verir; listeyi kapatın.")
        if isinstance(net, ipaddress.IPv6Network) and net.network_address.ipv4_mapped is not None:
            raise AllowListError("IPv4 adresini IPv4 olarak yazın (::ffff: biçimi kabul edilmez).")
        if str(net) not in out:
            out.append(str(net))
    if len(out) > MAX_ENTRIES:
        raise AllowListError(f"En fazla {MAX_ENTRIES} adres/ağ girilebilir.")
    return out


def parse(stored: str | None) -> list[_Net]:
    """The saved comma-separated list as networks (an entry that no longer parses is dropped)."""
    nets: list[_Net] = []
    for part in (stored or "").split(","):
        try:
            if part.strip():
                nets.append(ipaddress.ip_network(part.strip(), strict=False))
        except ValueError:
            continue
    return nets


def allows(stored: str | None, ip: str) -> bool:
    """Whether `ip` is inside the saved list. An address that is not an IP is outside it."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address in net for net in parse(stored) if net.version == address.version)


def activation_problem(headers: Mapping[str, str], *, ip: str, proxy_configured: bool) -> str | None:
    """Why the list may not be switched on now, or None.

    Behind a reverse proxy with no trusted-proxy setting the client address is the proxy's: every
    user would be refused (or, with the proxy in the list, every outsider let in)."""
    lowered = {k.lower() for k in headers}
    if not proxy_configured and any(h in lowered for h in _FORWARDING_HEADERS):
        return (
            "İstek bir ters vekil (reverse proxy) üzerinden geliyor ama TRUSTED_PROXY_COUNT / "
            "TRUSTED_PROXY_CIDRS ayarlı değil: istemci adresi güvenilir biçimde bilinemez. "
            "Önce bu ayarı yapın (docs/ops/auth-abuse-and-outbound.md)."
        )
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return "İstemci adresi belirlenemedi; izin listesi etkinleştirilemez."
    return None


def exempt(path: str) -> bool:
    return path.rstrip("/") in EXEMPT_PATHS


def refusal_for(stored: str | None, ip: str) -> str | None:
    """The refusal text for a saved list (already known enabled) that does not contain `ip`."""
    if not parse(stored):
        return None
    return None if allows(stored, ip) else refusal_text()


async def org_refusal(db: AsyncSession, org_id: str | None, ip: str) -> str | None:
    """The refusal sentence when `org_id` has an enabled, non-empty list that does not contain `ip`."""
    if not org_id:
        return None
    from app.models.organization import Organization

    row = (
        await db.execute(
            select(Organization.ip_whitelist_enabled, Organization.ip_whitelist).where(
                Organization.id == str(org_id)
            )
        )
    ).first()
    if row is None or not row[0] or not parse(row[1]):
        return None
    return None if allows(row[1], ip) else refusal_text()


async def lockout_preview(db: AsyncSession, org_id: str, new_stored: str, *, caller_outside: bool, caller_ip: str) -> str:
    """Who the new list would lock out, for the confirmation step (before anything is saved).

    Only data the app already stores: the address of each member's latest audit-log row. Counts and
    roles only, never an address of another person. A member with no known address is counted as unknown."""
    from app.models.audit_log import AuditLog
    from app.models.organization import OrgMembership

    members = (await db.execute(
        select(OrgMembership.user_id, OrgMembership.role).where(OrgMembership.org_id == org_id)
    )).all()
    roles = {str(u): str(r) for u, r in members}
    latest: dict[str, str] = {}
    if roles:
        rows = (await db.execute(
            select(AuditLog.user_id, AuditLog.ip_address)
            .where(AuditLog.user_id.in_(list(roles)), AuditLog.ip_address.is_not(None))
            .order_by(AuditLog.created_at.desc()).limit(5000)
        )).all()
        for uid, address in rows:
            latest.setdefault(str(uid), str(address))
    outside: dict[str, int] = {}
    unknown = 0
    for uid, role in roles.items():
        if uid not in latest:
            unknown += 1
        elif not allows(new_stored, latest[uid]):
            outside[role] = outside.get(role, 0) + 1
    parts = []
    if caller_outside:
        parts.append(f"Siz kilitlenirsiniz (şu anki adresiniz {caller_ip} listede değil) / You would be locked out (your address {caller_ip} is not on the list)")
    if outside:
        detail = ", ".join(f"{role}: {n}" for role, n in sorted(outside.items()))
        parts.append(f"son bilinen adresi listenin dışında kalan üyeler / members whose last known address is outside: {sum(outside.values())} ({detail})")
    if unknown:
        parts.append(f"adresi bilinmeyen üyeler / members with no known address: {unknown}")
    if not outside and not unknown:
        parts.append("diğer üyelerin erişimi de kesilebilir / other members may lose access too")
    return "; ".join(parts) + ". " + recovery_sentence()
