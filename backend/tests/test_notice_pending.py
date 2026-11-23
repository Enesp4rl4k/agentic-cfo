"""What the after-sign-in prompt relies on: the server alone says which notice versions are pending for a person.

`GET /privacy/notices` (`notices.status`) is the state the blocking prompt reads; `POST /privacy/notices/accept` records
only versions the server currently publishes. A client cannot accept a future, past or unknown version."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.config import get_settings
from app.models.erasure_record import OrgErasureRequest
from app.models.privacy_records import TermsAcceptance
from app.services.privacy import notices
from tests.api_helpers import kullanici
from tests.test_erasure_flow import _owner_company

NOTICES = "/api/v1/privacy/notices"


async def _status(client, hdr):
    return (await client.get(NOTICES, headers=hdr)).json()["data"]


async def _count(client, uid: str) -> int:
    async with client._maker() as db:
        return int((await db.execute(select(func.count()).select_from(TermsAcceptance)
                                     .where(TermsAcceptance.user_id == uid))).scalar_one())


async def test_a_new_person_has_both_documents_pending_and_pending_is_per_person(client) -> None:
    a, _, uid_a = await kullanici(client, "np-a@example.com", role="owner")
    b, _, _ = await kullanici(client, "np-b@example.com", role="owner")
    cur = get_settings()
    st = await _status(client, a)
    assert st["must_accept"] and st["privacy_notice"]["must_accept"] and st["terms"]["must_accept"]
    await client.post(NOTICES + "/accept", json={"privacy_notice": cur.privacy_notice_version, "terms": cur.terms_version}, headers=a)
    assert (await _status(client, a))["must_accept"] is False
    assert (await _status(client, b))["must_accept"] is True  # B accepted nothing: A's answer is not B's
    assert await _count(client, uid_a) == 2


async def test_accepting_one_document_leaves_the_other_pending(client) -> None:
    hdr, _, _ = await kullanici(client, "np-c@example.com", role="owner")
    cur = get_settings()
    await client.post(NOTICES + "/accept", json={"privacy_notice": cur.privacy_notice_version}, headers=hdr)
    st = await _status(client, hdr)
    assert st["must_accept"] is True
    assert st["privacy_notice"]["must_accept"] is False and st["terms"]["must_accept"] is True


async def test_a_client_cannot_accept_a_future_past_or_unknown_version(client, monkeypatch) -> None:
    hdr, _, uid = await kullanici(client, "np-d@example.com", role="owner")
    cur = get_settings()
    for bad in ({"privacy_notice": "taslak-99"}, {"terms": "v-from-the-future"}, {"privacy_notice": ""}):
        res = await client.post(NOTICES + "/accept", json=bad, headers=hdr)
        assert res.status_code in (409, 422), (bad, res.text)
    unknown = await client.post(NOTICES + "/accept", json={"cookie_policy": "1"}, headers=hdr)
    assert unknown.status_code == 422 or await _count(client, uid) == 0
    assert await _count(client, uid) == 0 and (await _status(client, hdr))["must_accept"] is True
    # A mixed request is refused whole: the valid half is not recorded beside the bad half.
    mixed = await client.post(NOTICES + "/accept", json={"privacy_notice": cur.privacy_notice_version, "terms": "taslak-99"}, headers=hdr)
    assert mixed.status_code == 409 and await _count(client, uid) == 0
    # After the owner publishes a new version, the OLD one is stale too.
    monkeypatch.setattr(cur, "privacy_notice_version", "taslak-2")
    old = await client.post(NOTICES + "/accept", json={"privacy_notice": "taslak-1"}, headers=hdr)
    assert old.status_code == 409 and await _count(client, uid) == 0


async def test_a_new_version_makes_only_that_document_pending_again(client, monkeypatch) -> None:
    hdr, _, _ = await kullanici(client, "np-e@example.com", role="owner")
    cur = get_settings()
    await client.post(NOTICES + "/accept", json={"privacy_notice": cur.privacy_notice_version, "terms": cur.terms_version}, headers=hdr)
    monkeypatch.setattr(cur, "terms_version", "taslak-2")
    st = await _status(client, hdr)
    assert st["must_accept"] and st["terms"]["must_accept"] and not st["privacy_notice"]["must_accept"]
    assert st["terms"]["version"] == "taslak-2" and st["terms"]["accepted_version"] == cur.privacy_notice_version
    ok = await client.post(NOTICES + "/accept", json={"terms": "taslak-2"}, headers=hdr)
    assert ok.status_code == 200 and (await _status(client, hdr))["must_accept"] is False


async def test_sign_up_staging_drops_a_version_the_server_does_not_publish(client) -> None:
    _, _, uid = await kullanici(client, "np-f@example.com", role="owner")
    async with client._maker() as db:
        kept = await notices.stage_at_signup(db, uid, {"privacy_notice": "taslak-99", "terms": get_settings().terms_version}, "invite")
        await db.commit()
    assert kept == ["terms"]
    st = await _status(client, (await kullanici(client, "np-g@example.com", role="owner"))[0])
    assert st["must_accept"]  # unrelated person untouched


async def test_blocked_and_failed_requests_stay_listed_for_the_owner_and_the_overview_names_the_support_contact(client, monkeypatch) -> None:
    hdr, org, _ = await _owner_company(client, "np-h@example.com")
    now = datetime.now(UTC)
    async with client._maker() as db:
        db.add(OrgErasureRequest(target_org_id=org, org_hash="h" * 64, mode="anonymise", status="blocked", blocked_reason="retries_exhausted",
                                 requested_by_hash="r" * 64, requested_at=now, expires_at=now + timedelta(days=7)))
        await db.commit()
    rows = (await client.get("/api/v1/privacy/erasure-requests", headers=hdr)).json()["data"]["requests"]
    blocked = [r for r in rows if r["status"] == "blocked"]
    assert len(blocked) == 1 and blocked[0]["blocked_reason"] == "retries_exhausted" and blocked[0]["cancellable"] is False
    monkeypatch.setattr(get_settings(), "support_contact", "  destek@example.test ")
    ov = (await client.get("/api/v1/privacy/overview", headers=hdr)).json()["data"]
    assert ov["support_contact"] == "destek@example.test"
    monkeypatch.setattr(get_settings(), "support_contact", "")
    assert (await client.get("/api/v1/privacy/overview", headers=hdr)).json()["data"]["support_contact"] is None
