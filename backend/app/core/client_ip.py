"""One answer to "which address is this request from?".

The rate limiter, the audit log, the password-reset limits and the organisation IP allow-list
all call `client_ip`. `X-Forwarded-For` is a header the *client* writes first, so its first
value is whatever an attacker types; only the entries appended by proxies we operate can be
believed. Rule:

* No trusted proxy configured (the default): the socket peer address, and the header is ignored.
* `TRUSTED_PROXY_CIDRS` (comma separated networks; wins when both are set) or
  `TRUSTED_PROXY_COUNT` (number of proxies in front of the app): the header is read only when the socket peer is one of ours.
  The chain is `X-Forwarded-For` entries followed by the peer; walking from the right, trusted
  hops are skipped (by network, or by count) and the first untrusted address is the client.
  An entry that is not an IP address ends the walk: the hop to its right (one a trusted proxy
  wrote) is used, never the garbage.
"""
from __future__ import annotations

import ipaddress
import logging
from functools import lru_cache

from starlette.requests import HTTPConnection

_IP = ipaddress.IPv4Address | ipaddress.IPv6Address
_Net = ipaddress.IPv4Network | ipaddress.IPv6Network
UNKNOWN = "unknown"


@lru_cache(maxsize=16)
def parse_networks(spec: str) -> tuple[_Net, ...]:
    """'10.0.0.0/8, fd00::/8' -> networks. Strict: a bad entry is an error, never skipped."""
    nets: list[_Net] = []
    for part in spec.split(","):
        part = part.strip()
        if part:
            nets.append(ipaddress.ip_network(part, strict=False))
    return tuple(nets)


def _parse(value: str) -> _IP | None:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def resolve_client_ip(
    peer: str | None, forwarded_for: str | None, *, proxy_count: int = 0, proxy_cidrs: str = ""
) -> str:
    """The pure rule (see module docstring); the peer's text is returned when nothing is trusted."""
    peer_text = peer or UNKNOWN
    nets = parse_networks(proxy_cidrs) if proxy_cidrs.strip() else ()
    if proxy_count <= 0 and not nets:
        return peer_text
    peer_ip = _parse(peer_text)
    if peer_ip is None:
        return peer_text
    # The header is believed only when it arrived through one of our own proxies.
    if nets and not any(peer_ip in n for n in nets):
        return str(peer_ip)
    if not forwarded_for:
        return str(peer_ip)
    chain = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    chain.append(str(peer_ip))
    best = str(peer_ip)
    for skipped, entry in enumerate(reversed(chain)):
        address = _parse(entry)
        if address is None:
            return best
        best = str(address)
        trusted = any(address in n for n in nets) if nets else skipped < proxy_count
        if not trusted:
            return best
    return best  # every hop was ours: the left-most address is the origin


_WATCH_AFTER = 20  # requests, all from private/loopback peers, before the warning
_private_peers = 0
_public_peer_seen = False
_warned = False


def reset_peer_watch() -> None:
    """Test hook: forget what the watch has seen."""
    global _private_peers, _public_peer_seen, _warned
    _private_peers, _public_peer_seen, _warned = 0, False, False


def observe_peer(peer: str | None, *, production: bool, configured: bool) -> bool:
    """Warn (once, loudly, never fail) when a production deployment with no trusted-proxy setting only
    ever sees private or loopback peers: that is a reverse proxy, every client would share one
    rate-limit bucket (login 5/min: a self-inflicted lockout) and the audit log would record the
    proxy. Returns True on the call that logs the warning."""
    global _private_peers, _public_peer_seen, _warned
    if not production or configured or _warned or _public_peer_seen:
        return False
    address = _parse(peer or "")
    if address is None:
        return False
    if not (address.is_private or address.is_loopback or address.is_link_local):
        _public_peer_seen = True
        return False
    _private_peers += 1
    if _private_peers < _WATCH_AFTER:
        return False
    _warned = True
    logging.getLogger(__name__).error(
        "All %d requests so far came from a private or loopback address (%s) and neither "
        "TRUSTED_PROXY_COUNT nor TRUSTED_PROXY_CIDRS is set. Behind a reverse proxy this makes every "
        "client share one rate-limit bucket (login 5/min locks everyone out) and the audit log records "
        "the proxy. Set TRUSTED_PROXY_COUNT=1 (see docs/ops/auth-abuse-and-outbound.md).",
        _private_peers, peer,
    )
    return True


def client_ip(connection: HTTPConnection) -> str:
    """The client address of a request or WebSocket, by the deployment's trusted-proxy setting."""
    from app.config import get_settings

    settings = get_settings()
    peer = connection.client.host if connection.client else None
    observe_peer(
        peer, production=not settings.use_sqlite,
        configured=bool(settings.trusted_proxy_count > 0 or settings.trusted_proxy_cidrs.strip()),
    )
    return resolve_client_ip(
        peer,
        connection.headers.get("X-Forwarded-For"),
        proxy_count=settings.trusted_proxy_count,
        proxy_cidrs=settings.trusted_proxy_cidrs,
    )
