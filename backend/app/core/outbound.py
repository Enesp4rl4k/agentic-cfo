"""The one client for a URL a user typed (webhook, Slack, CSV import ...).

A configured URL is attacker-controlled input to a server that sits inside a private network and
next to a cloud metadata service. Judging the literal host is not enough (`https://127.1/`,
`https://2130706433/`, `https://0/`, a name whose DNS record is 10.0.0.5, a name that answers a
public address to the check and a private one to the connection). Rules, all enforced here:

* Strict parse; `https` only (`allow_http=True` is a documented, per-call exception); no user-info,
  no whitespace/control characters, no backslashes, no IPv6 zone ids.
* A host written as a number in any form other than a canonical dotted quad / IPv6 (short `127.1`,
  decimal `2130706433`, octal `0177.0.0.1`, hex `0x7f.0.0.1`, `0`) is refused outright.
* The name is resolved and EVERY address must be public: loopback, RFC 1918, link-local (incl.
  169.254.169.254), CGNAT, unique-local, IPv4-mapped / NAT64 / 6to4 wrappers of those, unspecified,
  multicast, broadcast and reserved ranges are refused. One bad address refuses the destination.
* The connection is pinned: we connect to a validated address, with the original Host header and
  TLS SNI / certificate name, so a second DNS answer cannot redirect it (DNS rebinding).
* Redirects are never followed (a 3xx is just a status); environment proxies are ignored (they
  would defeat the pinning); connect/total timeouts; the response body is not read unless the
  caller asks for it with a byte cap, and a body over the cap is an error.
* The caller gets a status (and, for an explicit import, the capped bytes), never a response
  object to echo back.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

_IP = ipaddress.IPv4Address | ipaddress.IPv6Address

CONNECT_TIMEOUT = 5.0
TOTAL_TIMEOUT = 15.0
MAX_ADDRESSES_TRIED = 3

_INTERNAL_SUFFIXES = (
    ".localhost", ".local", ".internal", ".localdomain", ".lan", ".intranet", ".corp", ".home.arpa",
)
_FORBIDDEN_CHARS = re.compile(r"[\s\x00-\x1f\x7f\\]")
_NUMERIC_LABEL = re.compile(r"^(0x[0-9a-f]*|[0-9]+)$", re.IGNORECASE)
_EXTRA_DENY = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8", "100.64.0.0/10", "192.0.0.0/24", "192.0.2.0/24", "198.18.0.0/15",
        "198.51.100.0/24", "203.0.113.0/24", "240.0.0.0/4", "255.255.255.255/32",
        "64:ff9b:1::/48", "100::/64", "2001:db8::/32", "fc00::/7", "fe80::/10", "ff00::/8",
    )
)


PUBLIC_REASON = "destination_unreachable_or_refused"


def public_reason(reason: str) -> str:
    """What a person sees synchronously, whatever the precise reason (refused, internal, port, DNS).

    One class, so a connection test cannot be used to ask the server what is on its network. The
    precise reason stays in the admin-only delivery status and the audit log."""
    return PUBLIC_REASON


class OutboundBlocked(Exception):
    """The destination is refused by policy; `reason` is a stable word the screens may show."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class OutboundResponse:
    status_code: int
    body: bytes | None  # None unless the caller asked for a capped body
    headers: dict[str, str] = field(default_factory=dict)  # lower-cased names; never forwarded to a caller

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


Resolver = Callable[[str, int], Awaitable[list[str]]]
_resolver: Resolver | None = None  # test seam: tests never touch DNS
_transport: httpx.AsyncBaseTransport | None = None  # test seam: tests never touch the network


def set_test_seams(resolver: Resolver | None, transport: httpx.AsyncBaseTransport | None) -> None:
    """Install (or clear) the resolver and transport a test uses; refused outside pytest."""
    global _resolver, _transport
    if (resolver or transport) and "PYTEST_CURRENT_TEST" not in os.environ:
        raise RuntimeError("outbound test seams are refused outside pytest")
    _resolver, _transport = resolver, transport


def _unwrap(address: _IP) -> list[_IP]:
    """An address and every IPv4 address it wraps (mapped, NAT64, 6to4, Teredo)."""
    found: list[_IP] = [address]
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            found.append(address.ipv4_mapped)
        if address in ipaddress.ip_network("64:ff9b::/96"):
            found.append(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
        if address.sixtofour is not None:
            found.append(address.sixtofour)
        if address.teredo is not None:
            found.extend(address.teredo)
    return found


def address_is_blocked(address: _IP) -> bool:
    """True for anything that is not an ordinary public unicast address."""
    for candidate in _unwrap(address):
        if (
            not candidate.is_global
            or candidate.is_multicast
            or candidate.is_unspecified
            or candidate.is_loopback
            or candidate.is_link_local
            or candidate.is_reserved
            or any(candidate in net for net in _EXTRA_DENY)
        ):
            return True
    return False


@dataclass(frozen=True)
class Target:
    host: str  # ASCII (IDNA) host, no brackets, no trailing dot
    port: int
    scheme: str
    literal: _IP | None  # set when the host is an IP literal


def parse_target(url: str, *, allow_http: bool = False) -> Target:
    """The syntactic half of the check (no DNS). Raises OutboundBlocked."""
    if not isinstance(url, str) or not url or len(url) > 2048 or _FORBIDDEN_CHARS.search(url):
        raise OutboundBlocked("destination_invalid")
    try:
        parts = urlsplit(url)
        port = parts.port
        hostname = parts.hostname
    except ValueError:
        raise OutboundBlocked("destination_invalid") from None
    allowed = {"https", "http"} if allow_http else {"https"}
    if parts.scheme not in allowed or not hostname:
        raise OutboundBlocked("destination_not_https")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise OutboundBlocked("destination_invalid")
    if port == 0 or "%" in hostname:
        raise OutboundBlocked("destination_invalid")
    # Only the default port: an internal service on a public name would otherwise be probeable by
    # port. 8443 etc. are not allowed (no documented need); http (allow_http) keeps its own 80.
    if port is not None and port != (443 if parts.scheme == "https" else 80):
        raise OutboundBlocked("destination_port_not_allowed")
    try:
        host = hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError:
        raise OutboundBlocked("destination_invalid") from None
    if not host or ".." in host or len(host) > 253:
        raise OutboundBlocked("destination_invalid")
    effective_port = port or (443 if parts.scheme == "https" else 80)
    try:
        literal: _IP | None = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if address_is_blocked(literal):
            raise OutboundBlocked("destination_is_internal")
        return Target(str(literal), effective_port, parts.scheme, literal)
    # Not a canonical address. A final label that is a number (127.1, 2130706433, 0x7f.1, 0) is an
    # address in a legacy spelling some clients accept: refuse, never guess.
    if _NUMERIC_LABEL.match(host.rsplit(".", 1)[-1]) or ":" in host:
        raise OutboundBlocked("destination_is_internal")
    if host == "localhost" or host.endswith(_INTERNAL_SUFFIXES) or "." not in host:
        raise OutboundBlocked("destination_is_internal")
    return Target(host, effective_port, parts.scheme, None)


def static_problem(url: str, *, allow_http: bool = False) -> str | None:
    """`parse_target` as a reason word or None: for places that cannot await (no DNS here)."""
    try:
        parse_target(url, allow_http=allow_http)
    except OutboundBlocked as exc:
        return exc.reason
    return None


async def _system_resolve(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def resolve_public(target: Target) -> list[str]:
    """The addresses to connect to, every one validated; raises when any is not public."""
    if target.literal is not None:
        return [str(target.literal)]
    if _resolver is None and "PYTEST_CURRENT_TEST" in os.environ:
        raise RuntimeError("a test reached real DNS: install a resolver with set_test_seams")
    resolver = _resolver or _system_resolve
    try:
        raw = await asyncio.wait_for(resolver(target.host, target.port), timeout=CONNECT_TIMEOUT)
    except (OSError, TimeoutError, UnicodeError):
        raise OutboundBlocked("destination_unresolvable") from None
    addresses: list[str] = []
    for text in raw:
        try:
            address = ipaddress.ip_address(text.split("%", 1)[0])
        except ValueError:
            raise OutboundBlocked("destination_unresolvable") from None
        if address_is_blocked(address):
            raise OutboundBlocked("destination_is_internal")
        if str(address) not in addresses:
            addresses.append(str(address))
    if not addresses:
        raise OutboundBlocked("destination_unresolvable")
    return addresses


async def destination_problem(url: str, *, allow_http: bool = False) -> str | None:
    """Full check including DNS, as a reason word or None (for refusing at configuration time)."""
    try:
        await resolve_public(parse_target(url, allow_http=allow_http))
    except OutboundBlocked as exc:
        return exc.reason
    return None


def _host_header(target: Target) -> str:
    default_port = 443 if target.scheme == "https" else 80
    host = f"[{target.host}]" if target.literal is not None and target.literal.version == 6 else target.host
    return host if target.port == default_port else f"{host}:{target.port}"


async def _send(
    method: str, url: str, target: Target, address: str, *, headers: dict[str, str],
    json: Any, data: dict[str, str] | None, max_bytes: int, timeout: float,
    transport: httpx.AsyncBaseTransport | None,
) -> OutboundResponse:
    pinned = httpx.URL(url).copy_with(host=address)
    sent = {**headers, "Host": _host_header(target)}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=CONNECT_TIMEOUT),
        follow_redirects=False, trust_env=False, transport=transport,
    ) as client:
        built = client.build_request(
            method, pinned, headers=sent, json=json, data=data,
            extensions={"sni_hostname": target.host},
        )
        response = await client.send(built, stream=True)
        try:
            if max_bytes <= 0:
                return OutboundResponse(response.status_code, None, dict(response.headers))
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise OutboundBlocked("response_too_large")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise OutboundBlocked("response_too_large")
                chunks.append(chunk)
            return OutboundResponse(response.status_code, b"".join(chunks), dict(response.headers))
        finally:
            await response.aclose()


async def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: Any = None,
    data: dict[str, str] | None = None,
    max_bytes: int = 0,
    timeout: float = TOTAL_TIMEOUT,
    allow_http: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OutboundResponse:
    """One guarded request to a user-supplied URL. Raises OutboundBlocked or an httpx error.

    `transport` is a test seam (an httpx.MockTransport); it is refused outside pytest."""
    if transport is not None and "PYTEST_CURRENT_TEST" not in os.environ:
        raise RuntimeError("outbound transport is a test seam; refused outside pytest")
    target = parse_target(url, allow_http=allow_http)
    addresses = await resolve_public(target)
    last: Exception | None = None
    async with asyncio.timeout(timeout + CONNECT_TIMEOUT):
        for address in addresses[:MAX_ADDRESSES_TRIED]:
            try:
                return await _send(
                    method, url, target, address, headers=headers or {}, json=json, data=data,
                    max_bytes=max_bytes, timeout=timeout, transport=transport or _transport,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last = exc
    assert last is not None
    raise last


MAX_IMPORT_BYTES = 10 * 1024 * 1024  # the upload limit (CLAUDE.md law 9) applies to an import by URL too


async def fetch_import(url: str) -> bytes:
    """GET a file a user pointed us at (CSV import): https, public host, no redirects, <= 10 MB.

    The bytes go to a parser, never back to the caller of an API; a non-2xx status is an error."""
    response = await request("GET", url, max_bytes=MAX_IMPORT_BYTES, timeout=30.0)
    if not response.ok or response.body is None:
        raise OutboundBlocked(f"http_{response.status_code}")
    return response.body
