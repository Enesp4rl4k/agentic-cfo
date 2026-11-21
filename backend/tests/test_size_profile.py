"""Company size input: answers, the derived suggestion, the human confirmation.

Nothing here changes an authorisation, a threshold or a money rule; the profile
only suggests what the menu shows. See `services/size_profile.py` for the rule.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.decision import Decision
from app.models.organization import Organization
from app.services.size_profile import (
    FOCUS_DEFAULT,
    HeadcountBand,
    OutflowBand,
    SizeProfile,
    derive_size_profile,
)
from tests.api_helpers import bellek_istemcisi, kullanici

URL = "/api/v1/org/me/size-profile"
CONFIRM = f"{URL}/confirm"
ORG_ME = "/api/v1/org/me"
LOW, MID, HIGH = OutflowBand.UNDER_500K, OutflowBand.FROM_500K_TO_5M, OutflowBand.OVER_5M
FEW, SOME, MANY = HeadcountBand.UNDER_10, HeadcountBand.FROM_10_TO_49, HeadcountBand.FROM_50
MICRO, SMALL, MEDIUM = SizeProfile.MICRO, SizeProfile.SMALL, SizeProfile.MEDIUM


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _decisions(client, org_id):
    async with client._maker() as db:
        return (await db.execute(select(Decision).where(Decision.org_id == org_id)
                                 .order_by(Decision.decided_at))).scalars().all()


async def _org(client, org_id):
    async with client._maker() as db:
        return await db.get(Organization, org_id)


@pytest.mark.parametrize(("outflow", "headcount", "profile", "decided_by", "disagreement"), [
    (LOW, None, MICRO, "volume", False),
    (MID, None, SMALL, "volume", False),
    (HIGH, None, MEDIUM, "volume", False),
    (None, FEW, MICRO, "headcount", False),
    (None, SOME, SMALL, "headcount", False),
    (None, MANY, MEDIUM, "headcount", False),
    (LOW, FEW, MICRO, "volume", False),
    (MID, SOME, SMALL, "volume", False),
    (LOW, MANY, MICRO, "volume", True),    # volume wins over a large headcount
    (HIGH, FEW, MEDIUM, "volume", True),   # volume wins over a small headcount
    (MID, MANY, SMALL, "volume", True),
])
def test_derivation_table(outflow, headcount, profile, decided_by, disagreement):
    d = derive_size_profile(outflow, headcount)
    assert (d.profile, d.decided_by, d.disagreement) == (profile, decided_by, disagreement)


def test_nothing_answered_suggests_nothing():
    assert derive_size_profile(None, None) is None


def test_focus_default_per_profile():
    assert FOCUS_DEFAULT == {MICRO: True, SMALL: True, MEDIUM: False}


async def test_a_company_starts_undetermined(client):
    headers, org_id, _ = await kullanici(client, "bos@example.com")
    data = (await client.get(URL, headers=headers)).json()["data"]
    assert data["size_profile"] is None and data["suggestion"] is None
    assert data["monthly_outflow_band"] is None and data["has_inhouse_finance"] is None
    assert [o["value"] for o in data["options"]["monthly_outflow_band"]] == [b.value for b in OutflowBand]
    assert (await client.get(ORG_ME, headers=headers)).json()["data"]["size_profile"] is None
    assert await _decisions(client, org_id) == []


@pytest.mark.parametrize("role", ["viewer", "analyst", "cfo"])
async def test_only_deciders_may_read_or_set(client, role):
    headers, org_id, _ = await kullanici(client, f"{role}@example.com", role=role)
    assert (await client.get(URL, headers=headers)).status_code == 403
    assert (await client.put(URL, json={"headcount_band": "under_10"}, headers=headers)).status_code == 403
    assert (await client.post(CONFIRM, json={"profile": "micro"}, headers=headers)).status_code == 403
    assert (await _org(client, org_id)).size_profile is None
    assert await _decisions(client, org_id) == []


@pytest.mark.parametrize("role", ["owner", "admin"])
async def test_owner_and_admin_pass(client, role):
    headers, _, _ = await kullanici(client, f"{role}@example.com", role=role)
    assert (await client.get(URL, headers=headers)).status_code == 200
    assert (await client.put(URL, json={"headcount_band": "under_10"}, headers=headers)).status_code == 200


async def test_answers_are_validated(client):
    headers, org_id, _ = await kullanici(client, "gecersiz@example.com")
    for body in ({"monthly_outflow_band": "huge"}, {"headcount_band": 7}, {"has_inhouse_finance": "belki"}):
        assert (await client.put(URL, json=body, headers=headers)).status_code == 422
    assert (await client.post(CONFIRM, json={"profile": "giant"}, headers=headers)).status_code == 422
    assert (await _org(client, org_id)).monthly_outflow_band is None


async def test_answers_are_stored_and_suggest_but_do_not_set_the_profile(client):
    headers, org_id, user_id = await kullanici(client, "cevap@example.com")
    body = {"monthly_outflow_band": "under_500k", "headcount_band": "50_plus", "has_inhouse_finance": False}
    data = (await client.put(URL, json=body, headers=headers)).json()["data"]
    assert data["suggestion"] == {"profile": "micro", "decided_by": "volume", "disagreement": True}
    assert data["size_profile"] is None and data["focus_mode"] is False
    org = await _org(client, org_id)
    assert (org.monthly_outflow_band, org.headcount_band, org.has_inhouse_finance) == ("under_500k", "50_plus", False)
    (row,) = await _decisions(client, org_id)
    assert (row.decided_via, row.decided_by, row.outcome) == ("human", user_id, "answers_recorded")
    assert row.before["monthly_outflow_band"] is None and row.after["monthly_outflow_band"] == "under_500k"


async def test_repeating_the_same_answers_records_nothing_new(client):
    headers, org_id, _ = await kullanici(client, "ayni@example.com")
    for _ in range(2):
        await client.put(URL, json={"headcount_band": "under_10"}, headers=headers)
    assert len(await _decisions(client, org_id)) == 1


async def test_confirming_the_suggestion_sets_profile_focus_and_records_it(client):
    headers, org_id, user_id = await kullanici(client, "onay@example.com")
    await client.put(URL, json={"monthly_outflow_band": "under_500k"}, headers=headers)
    data = (await client.post(CONFIRM, json={"profile": "micro"}, headers=headers)).json()["data"]
    assert (data["size_profile"], data["size_profile_source"], data["focus_mode"]) == ("micro", "suggested_accepted", True)
    assert data["focus_mode_changed"] is True and data["size_profile_set_by"] == user_id
    org = await _org(client, org_id)
    assert org.focus_mode is True and org.focus_mode_explicit is False and org.size_profile_set_at is not None
    row = (await _decisions(client, org_id))[-1]
    assert row.outcome == "profile_confirmed" and row.decided_by == user_id
    assert row.before == {"size_profile": None, "focus_mode": False}
    assert row.after == {"size_profile": "micro", "focus_mode": True, "source": "suggested_accepted"}


async def test_choosing_another_profile_is_self_reported(client):
    headers, _, _ = await kullanici(client, "baska@example.com")
    await client.put(URL, json={"monthly_outflow_band": "under_500k"}, headers=headers)
    data = (await client.post(CONFIRM, json={"profile": "medium"}, headers=headers)).json()["data"]
    assert (data["size_profile"], data["size_profile_source"], data["focus_mode"]) == ("medium", "self_reported", False)
    assert data["focus_mode_changed"] is False


async def test_small_turns_focus_on_and_medium_leaves_the_full_menu(client):
    headers, _, _ = await kullanici(client, "kucuk@example.com")
    small = (await client.post(CONFIRM, json={"profile": "small"}, headers=headers)).json()["data"]
    assert small["focus_mode"] is True
    medium = (await client.post(CONFIRM, json={"profile": "medium"}, headers=headers)).json()["data"]
    assert medium["focus_mode"] is False  # nobody chose focus mode: the profile default follows


async def test_an_explicit_focus_choice_is_never_overwritten(client):
    headers, org_id, _ = await kullanici(client, "acik@example.com")
    await client.put(URL, json={"monthly_outflow_band": "under_500k"}, headers=headers)
    await client.post(CONFIRM, json={"profile": "micro"}, headers=headers)
    undo = await client.patch(ORG_ME, json={"focus_mode": False}, headers=headers)  # the one-click undo
    assert undo.json()["data"]["focus_mode"] is False
    again = (await client.post(CONFIRM, json={"profile": "micro"}, headers=headers)).json()["data"]
    assert again["focus_mode"] is False and again["focus_mode_changed"] is False
    assert (await _org(client, org_id)).focus_mode_explicit is True
    # and a medium company that chose focus on keeps it
    headers2, _, _ = await kullanici(client, "acik2@example.com")
    await client.patch(ORG_ME, json={"focus_mode": True}, headers=headers2)
    kept = (await client.post(CONFIRM, json={"profile": "medium"}, headers=headers2)).json()["data"]
    assert kept["focus_mode"] is True


async def test_other_settings_do_not_mark_focus_as_chosen(client):
    headers, org_id, _ = await kullanici(client, "diger@example.com")
    await client.patch(ORG_ME, json={"locale": "tr-TR"}, headers=headers)
    assert (await _org(client, org_id)).focus_mode_explicit is False


def test_migration_round_trip_and_backfill():
    """067 on a bare organisations table: backfills the focus choice, and downgrades cleanly."""
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "067_org_size_profile.py"
    spec = importlib.util.spec_from_file_location("m065", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("create table organizations (id varchar(36) primary key, focus_mode boolean not null default 0)"))
        conn.execute(sa.text("insert into organizations values ('on', 1), ('off', 0)"))
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
            rows = dict(conn.execute(sa.text("select id, focus_mode_explicit from organizations")).fetchall())
            assert rows == {"on": 1, "off": 0}
            mig.downgrade()
            assert [r[1] for r in conn.execute(sa.text("pragma table_info(organizations)")).fetchall()] == ["id", "focus_mode"]
