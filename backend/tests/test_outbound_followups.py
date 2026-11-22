"""Follow-ups to the outbound guard: Shopify/Trendyol hosts, ports, one public reason, delivery status."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core import outbound
from app.models.audit_log import AuditLog
from app.models.in_app_notification import InAppNotification
from app.services import delivery_status, outbox
from app.services.alert_dispatcher import AlertDispatcher
from app.services.integrations import ShopifyConnector, TrendyolConnector
from tests.api_helpers import bellek_istemcisi, kullanici

API = "/api/v1"


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


# ── Shopify / Trendyol: the host or path segment comes from input ────────────

@pytest.mark.parametrize("domain", [
    "evil.com", "x.myshopify.com.evil.com", "127.0.0.1", "a b", "shop/../x", "shop@evil.com", "-bad", "bad-",
    "a" * 70, "", "shop.myshopify.com/admin", "https://shop.myshopify.com", "shop:443",
])
def test_shopify_refuses_a_domain_that_is_not_a_shop_label(domain):
    with pytest.raises(ValueError):
        ShopifyConnector(domain, "token")


@pytest.mark.parametrize("domain", ["my-shop", "my-shop.myshopify.com", " My-Shop.MyShopify.com "])
def test_shopify_accepts_only_the_provider_pattern(domain):
    assert ShopifyConnector(domain, "t").base == "https://my-shop.myshopify.com/admin/api/2024-01"


@pytest.mark.asyncio
async def test_shopify_goes_through_the_guard_pinned_and_without_redirects():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"orders": []}, headers={"link": '<x>; rel="next"'})

    outbound.set_test_seams(_public_resolver, httpx.MockTransport(handler))
    result = await ShopifyConnector("my-shop", "tok").get_orders("2026-01-01", "2026-01-31")
    assert not result.failed
    request = seen[0]
    assert request.url.host == "93.184.216.34" and request.headers["host"] == "my-shop.myshopify.com"
    assert request.headers["x-shopify-access-token"] == "tok" and request.url.params["status"] == "any"

    async def internal(host: str, port: int) -> list[str]:
        return ["10.0.0.5"]

    seen.clear()
    outbound.set_test_seams(internal, httpx.MockTransport(handler))
    refused = await ShopifyConnector("my-shop", "tok").get_orders("2026-01-01", "2026-01-31")
    assert refused.failed and not seen  # a name that resolves inside is refused, nothing sent


def test_trendyol_supplier_id_is_a_number():
    TrendyolConnector("12345", "k", "s")
    for bad in ("12/../x", "1 2", "abc", "", "9" * 30):
        with pytest.raises(ValueError):
            TrendyolConnector(bad, "k", "s")


async def test_the_sync_route_answers_400_for_a_bad_domain(client):
    headers, _, _ = await kullanici(client, "own@example.com")
    body = {"channel": "shopify", "from_date": "2026-01-01", "to_date": "2026-01-31",
            "credentials": {"shop_domain": "169.254.169.254", "access_token": "t"}}
    assert (await client.post(f"{API}/integrations/ecommerce/sync", headers=headers, json=body)).status_code == 400


# ── ports ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", ["https://example.com:8443/x", "https://example.com:80/x", "https://93.184.216.34:22/"])
def test_only_the_default_port_is_allowed(url):
    assert outbound.static_problem(url) == "destination_port_not_allowed"


def test_the_default_port_written_out_is_fine():
    assert outbound.static_problem("https://example.com:443/x") is None


# ── one public reason, the precise one in the audit log ──────────────────────

async def test_every_refused_connection_test_gets_the_same_sentence_and_the_audit_log_keeps_the_reason(client):
    headers, _org_id, _ = await kullanici(client, "own@example.com")

    async def unresolvable(host: str, port: int) -> list[str]:
        raise OSError("nx")

    async def internal(host: str, port: int) -> list[str]:
        return ["10.0.0.5"]

    attempts = [
        ("slack", "https://127.0.0.1/x", None, "destination_is_internal"),
        ("custom", "https://example.com:8443/x", None, "destination_port_not_allowed"),
        ("custom", "https://nx.example.com/x", unresolvable, "destination_unresolvable"),
        ("custom", "https://sneaky.example.com/x", internal, "destination_is_internal"),
        ("custom", "http://example.com/x", None, "destination_not_https"),
        ("email", "stranger@example.org", None, "recipient_not_allowed"),
    ]
    details = set()
    for channel, target, resolver, _ in attempts:
        outbound.set_test_seams(resolver, None) if resolver else outbound.set_test_seams(
            lambda h, p: _public(), None
        )
        res = await client.post(f"{API}/integrations/webhook/test", headers=headers,
                                json={"channel": channel, "target": target})
        assert res.status_code == 400, (target, res.text)
        details.add(res.json()["error"])
    assert len(details) == 1 and "ulaşılamadı veya izin verilmiyor" in details.pop()
    async with client._maker() as db:
        rows = (await db.execute(select(AuditLog).where(AuditLog.action == "integrations.connection_test_refused"))).scalars().all()
    assert [r.request_body["reason"] for r in rows] == [a[3] for a in attempts]


async def _public() -> list[str]:
    return ["93.184.216.34"]


async def _public_resolver(host: str, port: int) -> list[str]:
    return ["93.184.216.34"]


# ── delivery status and the one-time notification ────────────────────────────

async def _failing_row(client, org_id: str, key: str, url: str = "https://127.0.0.1/hook"):
    async with client._maker() as db:
        row = await outbox.enqueue_webhook(
            db, key=key, org_id=org_id, url=url, event_type="e", data={}, source="t", source_ref=key
        )
        await outbox.deliver_pending(db)
        await db.commit()
        return row.status, row.last_error


async def test_the_delivery_status_is_for_owner_and_admin_only_and_shows_words_not_urls(client):
    owner, org_id, _ = await kullanici(client, "own@example.com")
    analyst, _, _ = await kullanici(client, "an@example.com", role="analyst")
    assert (await _failing_row(client, org_id, "k1")) == ("failed", "destination_is_internal")
    assert (await client.get(f"{API}/notifications/delivery-status", headers=analyst)).status_code == 403
    got = (await client.get(f"{API}/notifications/delivery-status", headers=owner)).json()["data"]["destinations"]
    assert len(got) == 1 and got[0]["destination"] == "127.0.0.1" and got[0]["failing"] is True
    assert got[0]["last_failure"]["tr"] == "hedef adres iç ağa işaret ediyor"
    assert got[0]["last_failure"]["en"] == "the address points to an internal network"
    assert got[0]["last_success_at"] is None
    assert "/hook" not in str(got) and "https://" not in str(got)  # no URL, no path, no secret


async def test_a_timeout_is_named(client):
    owner, org_id, _ = await kullanici(client, "own@example.com")

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    AlertDispatcher.transport = httpx.MockTransport(timeout)
    for i in range(outbox.MAX_ATTEMPTS):
        await _failing_row(client, org_id, f"t{i}", url="https://hooks.example.com/x")
    got = (await client.get(f"{API}/notifications/delivery-status", headers=owner)).json()["data"]["destinations"]
    assert got[0]["last_failure"]["code"] == "timeout" and got[0]["last_failure"]["tr"] == "zaman aşımı"


async def test_one_notification_when_a_destination_starts_failing_and_again_only_after_a_success(client):
    _owner, org_id, _ = await kullanici(client, "own@example.com")

    async def notes() -> list[InAppNotification]:
        async with client._maker() as db:
            return list((await db.execute(select(InAppNotification).where(InAppNotification.org_id == org_id))).scalars())

    await _failing_row(client, org_id, "a")
    await _failing_row(client, org_id, "b")  # still failing: nothing more
    first = await notes()
    assert len(first) == 1
    # every member can read it: one generic sentence, no host, no reason, no URL, nothing in `source`
    text = first[0].message + first[0].source
    assert "ulaşılamıyor" in first[0].message and "yöneticinize danışın" in first[0].message
    assert "127.0.0.1" not in text and "iç ağa" not in text and "https://" not in text and "internal" not in text
    # recovery, then a new outage: one more
    async with client._maker() as db:
        await outbox.enqueue_webhook(db, key="ok", org_id=org_id, url="https://127.0.0.1/hook", event_type="e",
                                     data={}, source="t", source_ref="ok")
        row = (await db.execute(select(outbox.OutboxMessage).where(outbox.OutboxMessage.key == "ok"))).scalar_one()
        row.status, row.sent_at, row.recipient = "sent", __import__("datetime").datetime.now(__import__("datetime").UTC), "127.0.0.1"
        await db.commit()
    await _failing_row(client, org_id, "c")
    assert len(await notes()) == 2


def test_every_reason_the_sender_can_write_has_words():
    for code in ("destination_is_internal", "destination_not_https", "destination_invalid", "destination_port_not_allowed",
                 "destination_unresolvable", "response_too_large", "timeout", "connection_failed", "slack_not_configured"):
        assert delivery_status.describe(code)["tr"] != delivery_status.describe("zzz")["tr"], code
    assert delivery_status.describe("http_503")["tr"] == "hedef 503 yanıtı verdi"
    assert delivery_status.describe(None)["code"] == "failed"
