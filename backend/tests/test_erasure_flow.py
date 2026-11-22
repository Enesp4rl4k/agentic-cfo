"""Cooling-off, cancellation, the operator route and member erasure (pseudonymous retention)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.decision import Decision, DecisionKind
from app.models.erasure_record import OrgErasureRequest
from app.models.in_app_notification import InAppNotification
from app.models.organization import Organization, OrgMembership
from app.models.user import User
from app.services.privacy import erasure_flow
from app.services.privacy.member_erasure import MEMBER_MODE, TOMBSTONE_DOMAIN, pseudonym
from tests.api_helpers import PAROLA, kullanici
from tests.test_org_erasure import _membership

ORG = "/api/v1/compliance/org-erasure"
OP = "/api/v1/compliance/operator/org-erasure"
MEMBER = "/api/v1/privacy/member-erasure"


async def _owner_company(client: Any, email: str) -> tuple[dict[str, str], str, str]:
    hdr, org, uid = await kullanici(client, email, role="owner")
    await _membership(client, uid, org, "owner")
    return hdr, org, uid


async def _scheduled(client: Any, hdr: dict[str, str]) -> tuple[str, dict[str, Any]]:
    r = await client.post(f"{ORG}/request", json={}, headers=hdr)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    c = await client.post(f"{ORG}/{d['request_id']}/confirm", json={"confirmation_phrase": d["confirmation_phrase"]}, headers=hdr)
    assert c.status_code == 200, c.text
    return d["request_id"], c.json()["data"]


async def test_confirm_schedules_and_nothing_is_destroyed_during_cooling_off(client) -> None:
    hdr, org, _ = await _owner_company(client, "o1@example.com")
    assert get_settings().erasure_cooling_off_days == 7  # the default
    rid, data = await _scheduled(client, hdr)
    assert data["status"] == "scheduled" and data["cancellable"] and data["irreversible"]
    assert "record" not in data
    async with client._maker() as db:
        assert (await db.get(Organization, org)).is_active is not False
        req = await db.get(OrgErasureRequest, rid)
        assert req.execute_after - req.confirmed_at >= timedelta(days=6, hours=23)
        rec = (await db.execute(select(Decision).where(Decision.org_id == org, Decision.kind == DecisionKind.ERASURE))).scalars().all()
        assert [d.outcome for d in rec] == ["scheduled"]
        assert await erasure_flow.execute_due(db) == {"executed": 0, "blocked": 0, "failed": 0, "expired": 0}
        assert (await db.get(Organization, org)).name != "[erased]"


async def test_the_executor_erases_only_what_is_due_and_is_idempotent(client) -> None:
    hdr_a, org_a, _ = await _owner_company(client, "a@example.com")
    hdr_b, org_b, _ = await _owner_company(client, "b@example.com")
    rid_a, _ = await _scheduled(client, hdr_a)
    await _scheduled(client, hdr_b)
    later = datetime.now(UTC) + timedelta(days=8)
    async with client._maker() as db:
        req_a = await db.get(OrgErasureRequest, rid_a)
        req_a.execute_after = datetime.now(UTC) - timedelta(minutes=1)  # only A's window is over
        await db.commit()
        assert (await erasure_flow.execute_due(db))["executed"] == 1
        assert (await db.get(Organization, org_a)).name == "[erased]"
        assert (await db.get(Organization, org_b)).name != "[erased]"
        assert (await db.get(OrgErasureRequest, rid_a)).status == "executed"
        assert (await db.get(OrgErasureRequest, rid_a)).target_org_id is None
        assert (await erasure_flow.execute_due(db))["executed"] == 0  # again: nothing
        assert (await erasure_flow.execute_due(db, now=later))["executed"] == 1  # B's turn
        assert (await db.get(Organization, org_b)).name == "[erased]"


async def test_the_owner_cancels_and_no_one_else_may(client) -> None:
    hdr, org, _ = await _owner_company(client, "own@example.com")
    adm, _, uid_adm = await kullanici(client, "adm@example.com", attach_org=False, role="admin")
    other, _, _ = await _owner_company(client, "other@example.org")
    async with client._maker() as db:
        (await db.get(User, uid_adm)).org_id = org
        await db.commit()
    await _membership(client, uid_adm, org, "admin")
    rid, _ = await _scheduled(client, hdr)
    assert (await client.post(f"{ORG}/{rid}/cancel", headers=adm)).status_code == 403
    assert (await client.post(f"{ORG}/{rid}/cancel", headers=other)).status_code == 404
    ok = await client.post(f"{ORG}/{rid}/cancel", headers=hdr)
    assert ok.status_code == 200 and ok.json()["data"]["status"] == "cancelled"
    assert (await client.post(f"{ORG}/{rid}/cancel", headers=hdr)).status_code == 409
    async with client._maker() as db:
        req = await db.get(OrgErasureRequest, rid)
        req.execute_after = datetime.now(UTC) - timedelta(days=1)
        await db.commit()
        assert (await erasure_flow.execute_due(db))["executed"] == 0
        assert (await db.get(Organization, org)).name != "[erased]"
        outcomes = (await db.execute(select(Decision.outcome).where(
            Decision.org_id == org, Decision.kind == DecisionKind.ERASURE).order_by(Decision.decided_at))).scalars().all()
        assert outcomes == ["scheduled", "cancelled"]


async def test_zero_cooling_off_runs_at_once(client, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "erasure_cooling_off_days", 0)
    hdr, _, _ = await _owner_company(client, "now@example.com")
    _, data = await _scheduled(client, hdr)
    assert data["status"] == "executed" and data["record"]["counts"]["organizations"]["anonymised"] == 1


async def test_the_operator_route_needs_an_operator_and_never_skips_the_window(client, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "platform_operator_emails", "ops@example.com")
    monkeypatch.setattr(get_settings(), "erasure_cooling_off_days", 0)
    owner, org, _ = await _owner_company(client, "company@example.com")
    ops, _, _ = await kullanici(client, "ops@example.com", attach_org=False, role="analyst")
    body = {"org_id": org, "verification_ref": "TICKET-42"}
    assert (await client.post(OP, json=body, headers=owner)).status_code == 403
    assert (await client.post(OP, json={**body, "org_id": "nope"}, headers=ops)).status_code == 404
    ok = await client.post(OP, json=body, headers=ops)
    assert ok.status_code == 200 and ok.json()["data"]["status"] == "scheduled"  # not executed although the window is 0
    rid = ok.json()["data"]["request_id"]
    async with client._maker() as db:
        req = await db.get(OrgErasureRequest, rid)
        assert req.initiated_by == "operator" and req.verification_ref == "TICKET-42"
        assert req.execute_after - req.confirmed_at >= timedelta(hours=23)
        note = (await db.execute(select(InAppNotification).where(InAppNotification.org_id == org))).scalars().all()
        assert note and "iptal" in note[0].message
    listing = (await client.get("/api/v1/privacy/erasure-requests", headers=owner)).json()["data"]["requests"]
    assert [r["request_id"] for r in listing] == [rid]
    assert (await client.post(f"{ORG}/{rid}/cancel", headers=owner)).status_code == 200  # the owner can stop it


async def test_hard_delete_switched_off_after_scheduling_blocks_the_run(client, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "org_erasure_hard_delete_enabled", True)
    hdr, org, _ = await _owner_company(client, "hd@example.com")
    r = await client.post(f"{ORG}/request", json={"mode": "hard_delete"}, headers=hdr)
    d = r.json()["data"]
    await client.post(f"{ORG}/{d['request_id']}/confirm", json={"confirmation_phrase": d["confirmation_phrase"]}, headers=hdr)
    monkeypatch.setattr(settings, "org_erasure_hard_delete_enabled", False)
    async with client._maker() as db:
        req = await db.get(OrgErasureRequest, d["request_id"])
        req.execute_after = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
        assert (await erasure_flow.execute_due(db))["blocked"] == 1
        assert (await db.get(OrgErasureRequest, d["request_id"])).blocked_reason == "hard_delete_disabled"
        assert (await db.get(Organization, org)) is not None


# ── member erasure ───────────────────────────────────────────────────────────

async def _member(client: Any, email: str, org: str, role: str) -> tuple[dict[str, str], str]:
    hdr, _, uid = await kullanici(client, email, attach_org=False, role=role)
    async with client._maker() as db:
        (await db.get(User, uid)).org_id = org
        await db.commit()
    await _membership(client, uid, org, role)
    return hdr, uid


async def _decide(client: Any, org: str, uid: str) -> str:
    from app.models.decision import DecidedVia
    from app.services.decisions import record_decision

    async with client._maker() as db:
        row = await record_decision(db, org_id=org, kind=DecisionKind.CATEGORY_CORRECTION, target_type="ledger_row",
                                    target_id="r1", outcome="applied", decided_via=DecidedVia.HUMAN, decided_by=uid,
                                    reason="Ayşe Hanım istedi")
        await db.commit()
        return str(row.id)


async def test_a_member_is_pseudonymised_the_company_and_its_audit_trail_stay(client, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "erasure_cooling_off_days", 0)
    _, org, _ = await _owner_company(client, "boss@example.com")
    me, uid = await _member(client, "leaver@example.com", org, "analyst")
    decision_id = await _decide(client, org, uid)
    from app.models.audit_log import AuditLog

    async with client._maker() as db:
        db.add(AuditLog(user_id=uid, user_email="leaver@example.com", user_role="analyst", action="POST /x",
                        resource="/x", ip_address="10.1.2.3", user_agent="UA", request_body={"n": "Ayşe"}, reason="why"))
        await db.commit()
    assert (await client.post(MEMBER, json={"confirmation": "someone@else.com"}, headers=me)).status_code == 422
    done = await client.post(MEMBER, json={"confirmation": "Leaver@Example.com"}, headers=me)
    assert done.status_code == 200 and done.json()["data"]["status"] == "executed", done.text
    handle = pseudonym(uid)
    async with client._maker() as db:
        u = await db.get(User, uid)
        assert u.email == f"{handle}@{TOMBSTONE_DOMAIN}" and u.full_name == handle
        assert u.is_active is False and u.org_id is None and u.api_key is None
        assert (await db.execute(select(OrgMembership).where(OrgMembership.user_id == uid))).first() is None
        d = await db.get(Decision, decision_id)
        assert d.decided_by == uid  # the trail still says one consistent someone decided
        audit = (await db.execute(select(AuditLog).where(AuditLog.user_id == uid))).scalar_one()
        assert audit.user_email == u.email and audit.ip_address is None and audit.user_agent is None
        assert audit.request_body is None and audit.reason is None and audit.action == "POST /x"
        assert (await db.get(Organization, org)).is_active is not False  # the company is untouched
        kinds = (await db.execute(select(Decision.outcome).where(Decision.org_id == org, Decision.kind == DecisionKind.MEMBER_CHANGE))).scalars().all()
        assert "member_erased" in kinds
        from app.models.erasure_record import OrgErasureRecord
        from app.services.org_erasure import verify_chain

        recs = (await db.execute(select(OrgErasureRecord))).scalars().all()
        assert [r.mode for r in recs] == [MEMBER_MODE] and "leaver" not in repr(recs[0].counts)
        assert await verify_chain(db) == []
    # signing in is over
    assert (await client.post("/api/v1/auth/login", json={"email": "leaver@example.com", "password": PAROLA})).status_code in (401, 403)


async def test_a_sole_owner_cannot_be_erased_and_a_member_can_cancel(client) -> None:
    owner, org, _ = await _owner_company(client, "solo@example.com")
    r = await client.post(MEMBER, json={"confirmation": "solo@example.com"}, headers=owner)
    assert r.status_code == 409 and "sole_owner" in r.text
    hdr, uid = await _member(client, "changed@example.com", org, "viewer")
    ok = await client.post(MEMBER, json={"confirmation": "changed@example.com"}, headers=hdr)
    assert ok.status_code == 200 and ok.json()["data"]["status"] == "scheduled"
    rid = ok.json()["data"]["request_id"]
    assert (await client.post(MEMBER, json={"confirmation": "changed@example.com"}, headers=hdr)).status_code == 409
    assert (await client.post(f"{MEMBER}/{rid}/cancel", headers=owner)).status_code == 404  # not the owner's request
    assert (await client.post(f"{MEMBER}/{rid}/cancel", headers=hdr)).status_code == 200
    async with client._maker() as db:
        assert (await db.get(User, uid)).email == "changed@example.com"


async def test_an_owner_erases_a_member_who_left_only_within_the_rules(client, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "erasure_cooling_off_days", 0)
    owner, org, uid_owner = await _owner_company(client, "own2@example.com")
    admin, uid_admin = await _member(client, "adm2@example.com", org, "admin")
    _, uid_a = await _member(client, "a2@example.com", org, "analyst")
    _, uid_two = await _member(client, "two@example.com", org, "analyst")
    other_owner, other_org, _ = await _owner_company(client, "otherco@example.org")
    await _membership(client, uid_two, other_org, "analyst")
    url = "/api/v1/privacy/org/members"
    body = {"confirmation": "a2@example.com"}
    assert (await client.post(f"{url}/{uid_a}/erasure", json=body, headers=other_owner)).status_code == 404  # another company
    assert (await client.post(f"{url}/{uid_owner}/erasure", json={"confirmation": "own2@example.com"}, headers=owner)).status_code == 409
    assert (await client.post(f"{url}/{uid_owner}/erasure", json={"confirmation": "own2@example.com"}, headers=admin)).status_code == 403
    assert (await client.post(f"{url}/{uid_two}/erasure", json={"confirmation": "two@example.com"}, headers=owner)).status_code == 409
    assert (await client.post(f"{url}/{uid_a}/erasure", json={"confirmation": "wrong@x.com"}, headers=owner)).status_code == 422
    ok = await client.post(f"{url}/{uid_a}/erasure", json=body, headers=admin)
    assert ok.status_code == 200 and ok.json()["data"]["status"] == "executed"
    async with client._maker() as db:
        assert (await db.get(User, uid_a)).email.endswith("@" + TOMBSTONE_DOMAIN)
        assert (await db.get(User, uid_admin)).email == "adm2@example.com"
        assert (await db.get(User, uid_two)).email == "two@example.com"


async def test_the_erased_member_leaves_no_address_in_recipient_lists_or_the_outbox(client, monkeypatch) -> None:
    import json

    from app.models.alert_preference import AlertPreference
    from app.models.outbox_message import OutboxMessage

    monkeypatch.setattr(get_settings(), "erasure_cooling_off_days", 0)
    _, org, _ = await _owner_company(client, "o5@example.com")
    hdr, _ = await _member(client, "gone@example.com", org, "analyst")
    async with client._maker() as db:
        db.add(AlertPreference(org_id=org, email_recipients=json.dumps(["gone@example.com", "keep@example.com"])))
        db.add(OutboxMessage(key="k1", org_id=org, channel="email", recipient="Gone@Example.com", subject="S",
                             body="Merhaba Ayşe", source="alert", source_ref="1", status="sent"))
        await db.commit()
    assert (await client.post(MEMBER, json={"confirmation": "gone@example.com"}, headers=hdr)).status_code == 200
    async with client._maker() as db:
        prefs = (await db.execute(select(AlertPreference).where(AlertPreference.org_id == org))).scalar_one()
        assert json.loads(prefs.email_recipients) == ["keep@example.com"]
        msg = (await db.execute(select(OutboxMessage).where(OutboxMessage.key == "k1"))).scalar_one()
        assert msg.recipient.endswith(TOMBSTONE_DOMAIN) and msg.body == "[erased]" and msg.status == "sent"


@pytest.mark.parametrize("path", ["/privacy/member-erasure", "/privacy/erasure-requests"])
async def test_privacy_routes_need_a_sign_in(client, path) -> None:
    call = client.post(f"/api/v1{path}", json={"confirmation": "x@y.com"}) if "member" in path else client.get(f"/api/v1{path}")
    assert (await call).status_code in (401, 403)
