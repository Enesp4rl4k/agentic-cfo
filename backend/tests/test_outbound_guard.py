"""app/core/outbound: every spelling of an internal address, rebinding, redirects, size caps.

No network and no DNS: a resolver and a MockTransport are injected (conftest installs a default
resolver that answers one public address)."""
from __future__ import annotations

import httpx
import pytest

from app.core import outbound
from app.core.outbound import OutboundBlocked, parse_target

PUBLIC = "93.184.216.34"


def _resolver(mapping: dict[str, list[str]]):
    async def resolve(host: str, port: int) -> list[str]:
        return mapping.get(host, [PUBLIC])

    return resolve


def _recorder(status: int = 200, body: bytes = b"ok", headers: dict[str, str] | None = None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, content=body, headers=headers or {})

    return seen, httpx.MockTransport(handler)


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/", "https://127.1/", "https://2130706433/", "https://0x7f.0.0.1/",
    "https://0177.0.0.1/", "https://017700000001/", "https://0/", "https://0.0.0.0/",
    "https://[::1]/", "https://[::]/", "https://[::ffff:127.0.0.1]/", "https://[::ffff:7f00:1]/",
    "https://10.0.0.5/", "https://172.16.0.1/", "https://192.168.1.1/", "https://169.254.169.254/",
    "https://169.254.169.254./", "https://100.64.0.1/", "https://[fd00::1]/", "https://[fe80::1]/",
    "https://[64:ff9b::7f00:1]/", "https://[2002:7f00:1::]/", "https://224.0.0.1/",
    "https://255.255.255.255/", "https://localhost/", "https://localhost./", "https://LOCALHOST/",
    "https://a.localhost/", "https://db.internal/", "https://printer.local/", "https://intranet/",
    "https://１２７.0.0.1/",  # full-width digits
    "https://127.0.0.1.:443/", "https://1.1/", "https://0x7f000001/",
])
def test_every_spelling_of_an_internal_host_is_refused(url):
    with pytest.raises(OutboundBlocked) as info:
        parse_target(url)
    assert info.value.reason in {"destination_is_internal", "destination_invalid"}


@pytest.mark.parametrize("url,reason", [
    ("http://example.com/", "destination_not_https"),
    ("ftp://example.com/", "destination_not_https"),
    ("file:///etc/passwd", "destination_not_https"),
    ("https:///path", "destination_not_https"),
    ("", "destination_invalid"),
    ("https://user:pw@example.com/", "destination_invalid"),
    ("https://example.com@127.0.0.1/", "destination_invalid"),
    ("https://example.com\\@127.0.0.1/", "destination_invalid"),
    ("https://exam ple.com/", "destination_invalid"),
    ("https://example.com/\r\nHost: x", "destination_invalid"),
    ("https://example.com:0/", "destination_invalid"),
    ("https://example.com:99999/", "destination_invalid"),
    ("https://[fe80::1%25eth0]/", "destination_invalid"),
])
def test_malformed_or_non_https_urls_are_refused(url, reason):
    with pytest.raises(OutboundBlocked) as info:
        parse_target(url)
    assert info.value.reason == reason


def test_a_plain_public_url_and_a_public_literal_pass():
    assert parse_target("https://hooks.slack.com/services/T/B/X").host == "hooks.slack.com"
    assert parse_target("https://93.184.216.34:8443/x").port == 8443
    assert parse_target("https://[2606:4700::1111]/").literal is not None
    assert outbound.static_problem("https://example.com/") is None
    assert outbound.static_problem("https://127.1/") == "destination_is_internal"


def test_http_is_an_explicit_exception_only():
    assert outbound.static_problem("http://example.com/") == "destination_not_https"
    assert outbound.static_problem("http://example.com/", allow_http=True) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("answers", [
    ["10.0.0.5"], ["127.0.0.1"], ["169.254.169.254"], ["::1"], ["::ffff:10.0.0.1"],
    ["fd12::1"], ["100.64.0.9"],
    [PUBLIC, "10.0.0.5"],  # one bad address among good ones refuses the whole destination
    ["10.0.0.5", PUBLIC],
])
async def test_a_name_that_resolves_to_an_internal_address_is_refused(answers):
    outbound.set_test_seams(_resolver({"evil.example.com": answers}), None)
    assert await outbound.destination_problem("https://evil.example.com/") == "destination_is_internal"
    seen, transport = _recorder()
    with pytest.raises(OutboundBlocked):
        await outbound.request("POST", "https://evil.example.com/hook", json={}, transport=transport)
    assert not seen  # nothing was sent


@pytest.mark.asyncio
async def test_an_unresolvable_name_is_refused():
    async def fail(host: str, port: int) -> list[str]:
        raise OSError("no such host")

    outbound.set_test_seams(fail, None)
    assert await outbound.destination_problem("https://nx.example.com/") == "destination_unresolvable"

    async def empty(host: str, port: int) -> list[str]:
        return []

    outbound.set_test_seams(empty, None)
    assert await outbound.destination_problem("https://nx.example.com/") == "destination_unresolvable"


@pytest.mark.asyncio
async def test_the_connection_is_pinned_to_the_validated_address_with_the_original_host():
    outbound.set_test_seams(_resolver({"hooks.example.com": [PUBLIC]}), None)
    seen, transport = _recorder()
    response = await outbound.request(
        "POST", "https://hooks.example.com:8443/a/b?q=1", json={"x": 1}, transport=transport,
    )
    assert response.status_code == 200 and response.body is None  # body not read by default
    request = seen[0]
    assert request.url.host == PUBLIC and request.url.port == 8443
    assert request.url.path == "/a/b" and request.url.query == b"q=1"
    assert request.headers["host"] == "hooks.example.com:8443"
    assert request.extensions["sni_hostname"] == "hooks.example.com"


@pytest.mark.asyncio
async def test_dns_rebinding_the_second_answer_is_never_used():
    """The name answers public to the check and private afterwards: we resolve once and connect to that."""
    answers = iter([[PUBLIC], ["10.0.0.5"], ["10.0.0.5"]])
    calls: list[str] = []

    async def rebinding(host: str, port: int) -> list[str]:
        calls.append(host)
        return next(answers)

    outbound.set_test_seams(rebinding, None)
    seen, transport = _recorder()
    await outbound.request("POST", "https://rebind.example.com/", json={}, transport=transport)
    assert calls == ["rebind.example.com"]  # one resolution per request
    assert [r.url.host for r in seen] == [PUBLIC]
    # and the next request resolves again and is refused
    with pytest.raises(OutboundBlocked):
        await outbound.request("POST", "https://rebind.example.com/", json={}, transport=transport)
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_a_redirect_is_a_status_never_followed():
    outbound.set_test_seams(None, None)
    seen, transport = _recorder(302, headers={"Location": "https://127.0.0.1/admin"})
    response = await outbound.request("POST", "https://example.com/", json={}, transport=transport)
    assert response.status_code == 302 and not response.ok
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_the_body_is_returned_only_when_asked_and_only_up_to_the_cap():
    _seen, transport = _recorder(body=b"a,b\n1,2\n")
    ok = await outbound.request("GET", "https://example.com/x.csv", max_bytes=100, transport=transport)
    assert ok.body == b"a,b\n1,2\n"
    _seen, big = _recorder(body=b"x" * 500)
    with pytest.raises(OutboundBlocked) as info:
        await outbound.request("GET", "https://example.com/x.csv", max_bytes=100, transport=big)
    assert info.value.reason == "response_too_large"
    _seen, declared = _recorder(body=b"x", headers={"Content-Length": "999999"})
    with pytest.raises(OutboundBlocked):
        await outbound.request("GET", "https://example.com/x.csv", max_bytes=100, transport=declared)


@pytest.mark.asyncio
async def test_fetch_import_refuses_internal_urls_and_error_statuses(monkeypatch):
    with pytest.raises(OutboundBlocked):
        await outbound.fetch_import("https://2130706433/data.csv")
    _seen, transport = _recorder(404)
    outbound.set_test_seams(None, transport)
    with pytest.raises(OutboundBlocked) as info:
        await outbound.fetch_import("https://example.com/missing.csv")
    assert info.value.reason == "http_404"


def test_the_test_seams_are_refused_outside_pytest(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    with pytest.raises(RuntimeError):
        outbound.set_test_seams(_resolver({}), None)
    with pytest.raises(RuntimeError):
        import asyncio

        asyncio.run(outbound.request("GET", "https://example.com/", transport=httpx.MockTransport(lambda r: httpx.Response(200))))


@pytest.mark.asyncio
async def test_slack_and_webhook_dispatch_report_a_refused_destination_and_send_nothing():
    from app.services.alert_dispatcher import AlertDispatcher

    seen, transport = _recorder()
    AlertDispatcher.transport = transport
    slack = await AlertDispatcher.dispatch_slack("https://127.1/hook", "t", "m")
    hook = await AlertDispatcher.dispatch_webhook("https://0/", "e", {})
    assert slack.delivered is False and slack.blocked_reason == "destination_is_internal"
    assert hook.delivered is False and hook.blocked_reason == "destination_is_internal"
    assert not seen


@pytest.mark.asyncio
async def test_the_csv_connectors_use_the_guard():
    from app.services.connectors.crm_export import pull_crm_export_csv
    from app.services.connectors.hr_export import pull_hr_export_csv

    seen, transport = _recorder(body=b"x")
    outbound.set_test_seams(None, transport)
    for pull in (pull_crm_export_csv, pull_hr_export_csv):
        assert await pull({"csv_url": "https://169.254.169.254/latest/meta-data/"}) == (b"", "")
        assert await pull({"csv_url": "http://example.com/a.csv"}) == (b"", "")
    assert not seen
