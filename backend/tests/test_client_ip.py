"""Client address derivation: a spoofed X-Forwarded-For must not choose the rate-limit bucket."""
from __future__ import annotations

import pytest
from starlette.requests import Request

from app.core.client_ip import client_ip, resolve_client_ip
from app.middleware.rate_limit import _get_client_key


def _request(peer: str | None, xff: str | None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({
        "type": "http", "method": "GET", "path": "/", "headers": headers,
        "client": (peer, 1234) if peer else None, "query_string": b"",
    })


def test_default_ignores_the_header_entirely():
    assert resolve_client_ip("203.0.113.9", "1.2.3.4") == "203.0.113.9"
    assert resolve_client_ip(None, "1.2.3.4") == "unknown"


def test_count_mode_takes_the_hop_the_proxy_saw_not_the_first_value():
    # attacker sends "6.6.6.6"; our one proxy appends the real address
    assert resolve_client_ip("10.0.0.5", "6.6.6.6, 198.51.100.7", proxy_count=1) == "198.51.100.7"
    # two proxies: client, proxy1 (seen by proxy2), peer = proxy2
    assert resolve_client_ip("10.0.0.6", "6.6.6.6, 198.51.100.7, 10.0.0.5", proxy_count=2) == "198.51.100.7"
    assert resolve_client_ip("10.0.0.5", None, proxy_count=1) == "10.0.0.5"


def test_cidr_mode_skips_trusted_hops_from_the_right():
    cidrs = "10.0.0.0/8, fd00::/8"
    assert resolve_client_ip("10.0.0.5", "9.9.9.9, 198.51.100.7, 10.1.1.1", proxy_cidrs=cidrs) == "198.51.100.7"
    assert resolve_client_ip("10.0.0.5", "198.51.100.7", proxy_cidrs=cidrs) == "198.51.100.7"


def test_header_from_an_untrusted_peer_is_ignored():
    assert resolve_client_ip("203.0.113.9", "1.1.1.1", proxy_cidrs="10.0.0.0/8") == "203.0.113.9"


def test_garbage_entry_never_becomes_the_address():
    assert resolve_client_ip("10.0.0.5", "not-an-ip, 10.0.0.9", proxy_cidrs="10.0.0.0/8") == "10.0.0.9"
    assert resolve_client_ip("10.0.0.5", "<script>", proxy_count=1) == "10.0.0.5"


def test_ipv4_mapped_peer_is_normalised():
    assert resolve_client_ip("::ffff:10.0.0.5", "198.51.100.7", proxy_cidrs="10.0.0.0/8") == "198.51.100.7"


def test_bad_cidr_setting_is_an_error_not_a_silent_skip():
    with pytest.raises(ValueError):
        resolve_client_ip("10.0.0.5", "1.1.1.1", proxy_cidrs="10.0.0.0/8, nonsense")


def test_rate_limit_bucket_cannot_be_chosen_by_the_client(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_COUNT", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        a = _get_client_key(_request("203.0.113.9", "1.1.1.1"))
        b = _get_client_key(_request("203.0.113.9", "2.2.2.2"))
        assert a == b == "ip:203.0.113.9"
        assert client_ip(_request("203.0.113.9", "1.1.1.1")) == "203.0.113.9"
    finally:
        get_settings.cache_clear()


def test_configured_proxy_count_is_read_from_settings(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        assert client_ip(_request("10.0.0.5", "6.6.6.6, 198.51.100.7")) == "198.51.100.7"
    finally:
        monkeypatch.delenv("TRUSTED_PROXY_COUNT")
        get_settings.cache_clear()
