"""E-postayla veri: an address per organisation, a provider's webhook, files put in place.

The mail is built the way it arrives: a forwarded bank statement with the
address in Delivered-To while To still names the original recipient, the
same file sent twice, a staff list beside it.
"""
from __future__ import annotations

import base64
from email.message import EmailMessage

import pytest
from sqlalchemy import select

from tests.test_ingest import BANKA, PERSONEL, XLSX, _login, client  # noqa: F401 — fixture

SECRET = "s3cret-for-tests"


@pytest.fixture
def inbox(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "email_ingest_domain", "veri.example.com")
    monkeypatch.setattr(s, "email_inbound_secret", SECRET)


def _mail(to: str, *attachments: tuple[str, bytes, str], delivered_to: str | None = None,
          subject: str = "Ocak ekstresi") -> bytes:
    m = EmailMessage()
    m["From"] = "ekstre@banka.example"
    m["To"] = to
    if delivered_to:
        m["Delivered-To"] = delivered_to
    m["Subject"] = subject
    m.set_content("Ekte hesap hareketleriniz.")
    for name, data, ctype in attachments:
        main, sub = ctype.split("/")
        m.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return m.as_bytes()


async def _address(client, h) -> str:
    r = await client.get("/api/v1/email/ingest-address", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["data"]["adres"]


@pytest.mark.asyncio
async def test_off_until_the_operator_configures_it(client):
    h = await _login(client)
    d = (await client.get("/api/v1/email/ingest-address", headers=h)).json()["data"]
    assert d["acik"] is False and d["adres"] is None and "Verilerimi Bağla" in d["mesaj"]
    # And the webhook refuses everything, even a well-formed request.
    r = await client.post("/api/v1/email/inbound", content=b"x", headers={"X-Inbound-Secret": ""})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_an_address_is_stable_until_it_is_renewed(client, inbox):
    h = await _login(client)
    first = await _address(client, h)
    assert first.startswith("veri+") and first.endswith("@veri.example.com")
    assert await _address(client, h) == first
    renewed = (await client.post("/api/v1/email/ingest-address/yenile", headers=h)).json()["data"]["adres"]
    assert renewed != first and await _address(client, h) == renewed

    # Mail to the replaced address is answered 200, so the provider does not retry, and dropped.
    r = await client.post("/api/v1/email/inbound", content=_mail(first, ("e.xlsx", BANKA, XLSX)),
                          headers={"X-Inbound-Secret": SECRET})
    assert r.status_code == 200 and r.json()["data"]["kabul"] is False
    assert (await client.get("/api/v1/email/history", headers=h)).json()["data"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("secret", ["", "wrong"])
async def test_the_webhook_needs_the_secret(client, inbox, secret):
    r = await client.post("/api/v1/email/inbound", content=b"From: a\r\n\r\nx", headers={"X-Inbound-Secret": secret})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_a_forwarded_statement_and_staff_list_are_put_in_place(client, inbox):
    from app.models.analysis_job import AnalysisJob
    from app.models.data_source import DataSource

    h = await _login(client)
    adres = await _address(client, h)
    # A forwarding rule keeps the original To; the provider delivers to our address.
    raw = _mail("muhasebe@firma.example", ("ekstre.xlsx", BANKA, XLSX), ("personel.csv", PERSONEL, "text/csv"),
                delivered_to=adres)
    basic = base64.b64encode(f"inbound:{SECRET}".encode()).decode()
    r = await client.post("/api/v1/email/inbound", content=raw, headers={"Authorization": f"Basic {basic}"})
    assert r.status_code == 200 and r.json()["data"]["kabul"] is True

    hist = (await client.get("/api/v1/email/history", headers=h)).json()["data"]
    assert len(hist) == 1 and hist[0]["konu"] == "Ocak ekstresi"
    by = {d["dosya"]: d for d in hist[0]["dosyalar"]}
    assert (by["ekstre.xlsx"]["durum"], by["personel.csv"]["durum"]) == ("eklendi", "eklendi")
    assert by["personel.csv"]["etiket"] == "Personel listesi"

    async with client._maker() as db:
        job = (await db.execute(select(AnalysisJob))).scalar_one()
        src = (await db.execute(select(DataSource))).scalar_one()
    assert (src.job_id, src.source_type) == (job.id, "headcount")
    # Filed under the organisation, and under the person who set the address up.
    assert job.org_id and job.user_id

    # The same statement forwarded again is not a second analysis.
    r = await client.post("/api/v1/email/inbound", content=_mail(adres, ("ekstre.xlsx", BANKA, XLSX)),
                          headers={"X-Inbound-Secret": SECRET})
    assert r.status_code == 200
    hist = (await client.get("/api/v1/email/history", headers=h)).json()["data"]
    assert hist[0]["dosyalar"][0]["durum"] == "onceden_alindi"
    async with client._maker() as db:
        assert len((await db.execute(select(AnalysisJob))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_a_provider_that_posts_a_form(client, inbox):
    h = await _login(client)
    adres = await _address(client, h)
    raw = _mail(adres, ("ekstre.xlsx", BANKA, XLSX))
    r = await client.post("/api/v1/email/inbound", data={"to": adres}, files={"email": ("m.eml", raw, "message/rfc822")},
                          headers={"X-Inbound-Secret": SECRET})
    assert r.status_code == 200 and r.json()["data"]["kabul"] is True


@pytest.mark.asyncio
async def test_nobody_can_answer_which_kind_so_it_is_recorded_not_guessed(client, inbox):
    h = await _login(client)
    adres = await _address(client, h)
    karisik = b"Politika,Durum,Bulgu,Onem\nKVKK,aktif,x,yuksek\n"
    await client.post("/api/v1/email/inbound", content=_mail(adres, ("ekstre.xlsx", BANKA, XLSX), ("k.csv", karisik, "text/csv")),
                      headers={"X-Inbound-Secret": SECRET})
    d = {x["dosya"]: x for x in (await client.get("/api/v1/email/history", headers=h)).json()["data"][0]["dosyalar"]}
    assert d["k.csv"]["durum"] == "secim_gerekli" and "Verilerimi Bağla" in d["k.csv"]["mesaj"]


@pytest.mark.asyncio
async def test_one_organisation_never_sees_anothers_mail(client, inbox):
    a = await _login(client, "a@example.com")
    adres = await _address(client, a)
    await client.post("/api/v1/email/inbound", content=_mail(adres, ("ekstre.xlsx", BANKA, XLSX)),
                      headers={"X-Inbound-Secret": SECRET})
    b = await _login(client, "b@example.com")
    assert (await client.get("/api/v1/email/history", headers=b)).json()["data"] == []
    assert await _address(client, b) != adres
