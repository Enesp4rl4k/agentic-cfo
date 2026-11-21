"""Her durum değiştiren rota, hangi rolün yapabileceğini söyler.

`tests/test_route_access.py` asks *whose* an object is. This asks *who in the
company* may change it. Before `require_writer` / `require_decider` /
`require_smmm`, a viewer could approve a held run, resolve a duplicate, correct a
category and finalise the accountant's packet.

1. Structural: every POST / PUT / PATCH / DELETE route is public, guarded by a
   role dependency, guarded inline (listed, with how) or open to any member
   (listed, with why). A new route that is none of these fails here by name.
2. Behavioural: viewer and analyst are refused (403) on a route of each class;
   the right role passes; an accountant of company A gets 404 on company B.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.api.access import INLINE_GUARDED, OPEN_ROUTES, PUBLIC_ROUTES
from app.models.analysis_job import AnalysisJob
from app.models.defensibility_packet import DefensibilityPacket
from app.models.organization import Organization, OrgMembership
from app.models.user import User
from tests.api_helpers import PAROLA, bellek_istemcisi, kullanici
from tests.test_route_access import ROUTES, _deps

STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
GUARDS = {"require_writer", "require_decider", "require_smmm", "_check"}  # _check = require_role


def _changing():
    return [(k, r) for k, r in ROUTES if k[0] in STATE_CHANGING]


def test_every_state_changing_route_declares_who_may_use_it() -> None:
    offenders = [
        f"{m} {p}" for (m, p), r in _changing()
        if not (_deps(r) & GUARDS)
        and (m, p) not in PUBLIC_ROUTES
        and (m, p) not in OPEN_ROUTES
        and (m, p) not in INLINE_GUARDED
    ]
    assert not offenders, (
        "rota hangi rolün kullanabileceğini söylemiyor — Depends(require_writer / "
        "require_decider / require_smmm) ekleyin, ya da app/api/access.py'de "
        "OPEN_ROUTES / INLINE_GUARDED'a gerekçesiyle yazın:\n  " + "\n  ".join(offenders)
    )


def test_the_allow_lists_name_routes_that_exist_and_do_not_overlap() -> None:
    keys = {k for k, _ in _changing()}
    guarded = {k for k, r in _changing() if _deps(r) & GUARDS}
    for name, table in (("OPEN_ROUTES", OPEN_ROUTES), ("INLINE_GUARDED", INLINE_GUARDED)):
        assert not [k for k in table if k not in keys], f"{name}: artık olmayan rota"
        assert not [k for k in table if k in guarded], f"{name}: zaten korunan rota"
        assert not [k for k in table if k in PUBLIC_ROUTES], f"{name}: herkese açık listede de"
    assert not set(OPEN_ROUTES) & set(INLINE_GUARDED)


def test_the_three_role_classes_are_all_in_use() -> None:
    used = set().union(*(_deps(r) for _, r in _changing()))
    assert {"require_writer", "require_decider", "require_smmm"} <= used


# ── behaviour ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _member(client, email: str, org_id: str, role: str) -> dict[str, str]:
    """A user acting in `org_id` with `role`, through the membership.

    Rows and a token are made directly: /auth/register is rate-limited to five
    a minute per address, and the role is what is under test, not sign-up.
    """
    from app.api.auth import create_access_token, hash_password

    async with client._maker() as db:
        user = User(email=email, hashed_password=hash_password(PAROLA), full_name="T",
                    role=role, org_id=org_id)
        db.add(user)
        await db.flush()
        db.add(OrgMembership(user_id=user.id, org_id=org_id, role=role))
        await db.commit()
        token = create_access_token(user.id, email, role)
    return {"Authorization": f"Bearer {token}"}


async def _packet(client, org_id: str) -> str:
    """A draft packet of a job of `org_id` (a packet is its job's, and the job decides)."""
    async with client._maker() as db:
        job = AnalysisJob(org_id=org_id, filename="a.csv", file_path="/tmp/a.csv", file_type="csv")
        db.add(job)
        await db.flush()
        packet = DefensibilityPacket(org_id=org_id, job_id=job.id, status="draft")
        db.add(packet)
        await db.commit()
        return str(packet.id)


async def _company(client, name: str, *, roles: tuple[str, ...]) -> tuple[str, dict[str, dict[str, str]]]:
    async with client._maker() as db:
        org = Organization(name=name, slug=name, regional_packs=["tr"])
        db.add(org)
        await db.commit()
        org_id = org.id
    return org_id, {
        role: await _member(client, f"u-{role}@{name}.com", org_id, role) for role in roles
    }


ALL = ("viewer", "analyst", "cfo", "admin", "owner", "smmm")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body", "allowed"),
    [
        # writer: a ledger row, a category, a held run
        ("POST", "/api/v1/ledger/rows/nope/resolve", {"action": "keep"}, {"cfo", "admin", "owner", "smmm"}),
        ("PATCH", "/api/v1/transactions/nope/category", {"category": "rent"}, {"cfo", "admin", "owner", "smmm"}),
        ("POST", "/api/v1/analysis/nope/approve", None, {"cfo", "admin", "owner", "smmm"}),
        # decider: an action that leaves the system
        ("POST", "/api/v1/actions/nope/approve", None, {"admin", "owner"}),
    ],
)
async def test_read_only_roles_are_refused_and_writers_pass(client, method, path, body, allowed) -> None:
    _, heads = await _company(client, "acme", roles=ALL)
    for role in ALL:
        r = await client.request(method, path, headers=heads[role], json=body)
        if role in allowed:
            assert r.status_code != 403, (role, path, r.text)
        else:
            assert r.status_code == 403, (role, path, r.status_code)
            assert r.json()["error"], "an explanation, not an empty refusal"


@pytest.mark.asyncio
async def test_smmm_class_needs_the_accountant_when_the_company_has_one(client) -> None:
    _, heads = await _company(client, "acme", roles=ALL)
    for role in ALL:
        r = await client.post("/api/v1/smmm/donem-kilitleri", headers=heads[role], json={"donem": "2026-01"})
        if role == "smmm":
            assert r.status_code != 403, r.text
        else:
            assert r.status_code == 403, (role, r.status_code)


@pytest.mark.asyncio
async def test_a_company_without_an_accountant_keeps_its_own_books(client) -> None:
    _, heads = await _company(client, "solo", roles=("viewer", "analyst", "cfo", "admin", "owner"))
    for role in ("viewer", "analyst"):
        r = await client.post("/api/v1/smmm/donem-kilitleri", headers=heads[role], json={"donem": "2026-01"})
        assert r.status_code == 403, role
    for role in ("cfo", "admin", "owner"):
        r = await client.post("/api/v1/smmm/donem-kilitleri", headers=heads[role], json={"donem": "2026-01"})
        assert r.status_code != 403, (role, r.text)


@pytest.mark.asyncio
async def test_smmm_finalises_a_packet_and_viewer_does_not(client) -> None:
    org_a, heads_a = await _company(client, "alfa", roles=("viewer", "smmm"))
    packet_id = await _packet(client, org_a)
    url = f"/api/v1/smmm/defensibility/{packet_id}/finalize"
    body = {"statement": "Beyan"}
    assert (await client.post(url, headers=heads_a["viewer"], json=body)).status_code == 403
    r = await client.post(url, headers=heads_a["smmm"], json=body)
    assert r.status_code != 403 and r.status_code != 404, r.text


@pytest.mark.asyncio
async def test_an_accountant_of_one_company_cannot_act_on_another(client) -> None:
    _, heads_a = await _company(client, "alfa", roles=("smmm",))
    org_b, _ = await _company(client, "beta", roles=("smmm",))
    packet_id = await _packet(client, org_b)
    r = await client.post(
        f"/api/v1/smmm/defensibility/{packet_id}/finalize",
        headers=heads_a["smmm"], json={"statement": "Beyan"},
    )
    assert r.status_code == 404
    async with client._maker() as db:
        assert (await db.get(DefensibilityPacket, packet_id)).status == "draft"


@pytest.mark.asyncio
async def test_the_role_is_the_membership_not_the_users_column(client) -> None:
    """An owner at home who is only a viewer in this company is a viewer here."""
    headers, org_id, user_id = await kullanici(client, "firma@x.com", role="owner")
    async with client._maker() as db:
        db.add(OrgMembership(user_id=user_id, org_id=org_id, role="viewer"))
        await db.commit()
    r = await client.post("/api/v1/actions/nope/approve", headers=headers)
    assert r.status_code == 403
    r = await client.post("/api/v1/ledger/rows/nope/resolve", headers=headers, json={"action": "keep"})
    assert r.status_code == 403


async def _split_role(client, org_id: str, email: str, *, column: str, membership: str) -> dict[str, str]:
    """A user whose `users.role` and membership role disagree."""
    from app.api.auth import create_access_token, hash_password

    async with client._maker() as db:
        user = User(email=email, hashed_password=hash_password(PAROLA), full_name="T",
                    role=column, org_id=org_id)
        db.add(user)
        await db.flush()
        db.add(OrgMembership(user_id=user.id, org_id=org_id, role=membership))
        await db.commit()
        token = create_access_token(user.id, email, column)
    return {"Authorization": f"Bearer {token}"}


async def _review_row(client, org_id: str) -> str:
    from app.models.smmm_onay import SMMMOnayKaydi

    async with client._maker() as db:
        job = AnalysisJob(org_id=org_id, filename="a.csv", file_path="/tmp/a.csv", file_type="csv")
        db.add(job)
        await db.flush()
        row = SMMMOnayKaydi(job_id=job.id, org_id=org_id, kayit_id="k1", durum="bekliyor",
                            orijinal_kayit={})
        db.add(row)
        await db.commit()
        return str(row.id)


@pytest.mark.asyncio
async def test_the_membership_role_wins_over_the_users_column_everywhere(client) -> None:
    """One source for the acting role: the SMMM approval route and a decider route."""
    org_id, _ = await _company(client, "gama", roles=())
    demoted = await _split_role(client, org_id, "d@gama.com", column="smmm", membership="viewer")
    promoted = await _split_role(client, org_id, "p@gama.com", column="viewer", membership="smmm")
    boss = await _split_role(client, org_id, "b@gama.com", column="analyst", membership="owner")
    fake_boss = await _split_role(client, org_id, "f@gama.com", column="owner", membership="analyst")

    # SMMM approval route (inline authority matrix)
    row_a, row_b = await _review_row(client, org_id), await _review_row(client, org_id)
    assert (await client.post(f"/api/v1/smmm/onay/{row_a}/onayla", headers=demoted,
                              json={})).status_code == 403
    assert (await client.post(f"/api/v1/smmm/onay/{row_b}/onayla", headers=promoted,
                              json={})).status_code == 200
    # decider route (guard) and an inline decider route (authority policy)
    assert (await client.post("/api/v1/actions/nope/approve", headers=fake_boss)).status_code == 403
    assert (await client.post("/api/v1/actions/nope/approve", headers=boss)).status_code != 403
    policy = {"rules": []}
    assert (await client.put("/api/v1/authority/policy", headers=fake_boss, json=policy)).status_code == 403
    assert (await client.put("/api/v1/authority/policy", headers=boss, json=policy)).status_code != 403
