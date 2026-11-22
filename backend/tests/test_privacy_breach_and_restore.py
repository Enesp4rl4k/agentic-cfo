"""Breach scoping from the registry, and re-applying erasures after a restore."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import delete, update

from app.config import get_settings
from app.database import Base
from app.models.organization import Organization
from app.services import org_erasure as svc
from app.services.privacy import erasure_flow
from app.services.privacy.breach_scope import scope
from app.services.privacy.member_erasure import MEMBER_MODE, is_tombstone
from tests.api_helpers import kullanici
from tests.db_helpers import gecici_veritabani
from tests.test_org_erasure import _rows, _two_orgs


@pytest_asyncio.fixture
async def maker():
    async with gecici_veritabani() as m:
        yield m


async def test_breach_scope_names_companies_categories_and_people(maker) -> None:
    async with maker() as db:
        a, b, _ = await _two_orgs(db)
        report = await scope(db, ["transactions", "outbox_messages", "uploads", "users"])
    assert set(report["organisations"]) == {a["org"], b["org"]}
    assert {"tax_id", "free_text", "contact", "identity"} <= set(report["categories"]) | {"tax_id", "identity"}
    assert "counterparty" in report["subjects"] and "member" in report["subjects"]
    assert report["keys"]["transactions"]["rows_per_organisation"][a["org"]] == 1
    assert report["keys"]["uploads"]["third_parties"] == ["llm_provider"]
    assert report["keys"]["outbox_messages"]["third_parties"] == ["smtp_provider", "slack_webhook", "whatsapp_twilio"]
    assert "ZZPII" not in repr(report)  # counts only, never content


async def test_breach_scope_refuses_a_key_the_registry_does_not_know(maker) -> None:
    async with maker() as db:
        with pytest.raises(ValueError, match="not_a_table"):
            await scope(db, ["not_a_table"])


async def test_breach_scope_route_is_for_operators_only(client, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "platform_operator_emails", "ops@example.com")
    own, _, _ = await kullanici(client, "own@example.com", role="owner")
    ops, _, _ = await kullanici(client, "ops@example.com", attach_org=False, role="analyst")
    url = "/api/v1/privacy/operator/breach-scope?keys=users,uploads"
    assert (await client.get(url, headers=own)).status_code == 403
    ok = await client.get(url, headers=ops)
    assert ok.status_code == 200 and ok.json()["data"]["organisation_count"] >= 1
    assert (await client.get("/api/v1/privacy/operator/breach-scope?keys=nope", headers=ops)).status_code == 422


async def test_erasures_are_reapplied_from_hashes_after_a_restore(maker, tmp_path) -> None:
    """Erase, restore the rows from before the erasure, re-apply from the exported hashes only."""
    async with maker() as db:
        a, b, _ = await _two_orgs(db)
        res = await svc.erase_org(db, a["org"], storage_root=tmp_path)
        erased = {res.record.org_hash: res.record.mode, svc.hash_id("member", b["users"][1]): MEMBER_MODE}
        o = Base.metadata.tables["organizations"]
        await db.execute(update(o).where(o.c.id == a["org"]).values(name="ZZPIIA restored", is_active=True))
        await db.execute(delete(Base.metadata.tables["org_erasure_records"]))
        await db.commit()
        assert (await db.get(Organization, a["org"])).name == "ZZPIIA restored"

        counts = await erasure_flow.reapply_erased(db, erased)
        assert counts["organisations"] == 1 and counts["members"] == 1
        assert (await db.get(Organization, a["org"])).name == svc.ERASED
        users = {r["id"]: r for r in await _rows(db, Base.metadata.tables["users"])}
        assert is_tombstone(users[b["users"][1]]["email"]) and not is_tombstone(users[b["users"][0]]["email"])
        again = await erasure_flow.reapply_erased(db, erased)
        assert again["organisations"] == 0 and again["members"] == 0  # idempotent
