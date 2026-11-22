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


def client_ip(connection: HTTPConnection) -> str:
    """The client address of a request or WebSocket, by the deployment's trusted-proxy setting."""
    from app.config import get_settings

    settings = get_settings()
    peer = connection.client.host if connection.client else None
    return resolve_client_ip(
        peer,
        connection.headers.get("X-Forwarded-For"),
        proxy_count=settings.trusted_proxy_count,
        proxy_cidrs=settings.trusted_proxy_cidrs,
    )
