"""Her durum değiştiren rota, hangi rolün yapabileceğini söyler.

`tests/test_route_access.py` asks *whose* an object is. This asks *who in the
company* may change it. Before `require_writer` / `require_decider` /
`require_smmm`, a viewer could approve a held run, resolve a duplicate, correct a
category and finalise the accountant's packet.

1. Structural: every POST / PUT / PATCH / DELETE route is public, guarded by a
   role dependency (the real guard function, by identity — a dependency that
   merely shares a name does not count), guarded inline (listed, with how; the
   handler must actually reach the role resolver) or open to any member
   (listed, with why). A new route that is none of these fails here by name.
2. Behavioural: viewer and analyst are refused (403) on a route of each class;
   the right role passes; an accountant of company A gets 404 on company B.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import textwrap
import types

import pytest
import pytest_asyncio

from app.api import access
from app.api.access import INLINE_GUARDED, OPEN_ROUTES, PUBLIC_ROUTES
from app.models.analysis_job import AnalysisJob
from app.models.defensibility_packet import DefensibilityPacket
from app.models.organization import Organization, OrgMembership
from app.models.user import User
from app.services import payment_plan
from tests.api_helpers import PAROLA, bellek_istemcisi, kullanici
from tests.test_route_access import ROUTES

STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
# The real guard functions. `require_role(...)` builds a closure per call, so it
# is recognised by where it is defined, not by its (common) name `_check`.
GUARD_FUNCS = {
    access.require_contributor,
    access.require_writer,
    access.require_decider,
    access.require_smmm,
    access.require_platform_operator,
}


def _is_role_closure(call) -> bool:
    return (
        getattr(call, "__module__", "") == "app.api.auth"
        and getattr(call, "__qualname__", "").startswith("require_role.<locals>.")
    )


def _calls(route) -> set:
    dependant = getattr(route, "dependant", None) or getattr(
        getattr(route, "original_route", None), "dependant", None
    )
    out: set = set()

    def walk(d):
        for sub in d.dependencies:
            out.add(sub.call)
            walk(sub)

    if dependant is not None:
        walk(dependant)
    return out


def _guarded(route) -> bool:
    return any(c in GUARD_FUNCS or _is_role_closure(c) for c in _calls(route))


def _guards_of(route) -> set:
    return {c for c in _calls(route) if c in GUARD_FUNCS}


def _changing():
    return [(k, r) for k, r in ROUTES if k[0] in STATE_CHANGING]


def test_every_state_changing_route_declares_who_may_use_it() -> None:
    offenders = [
        f"{m} {p}" for (m, p), r in _changing()
        if not _guarded(r)
        and (m, p) not in PUBLIC_ROUTES
        and (m, p) not in OPEN_ROUTES
        and (m, p) not in INLINE_GUARDED
    ]
    assert not offenders, (
        "rota hangi rolün kullanabileceğini söylemiyor — Depends(require_writer / "
        "require_decider / require_smmm) ekleyin, ya da app/api/access.py'de "
        "OPEN_ROUTES / INLINE_GUARDED'a gerekçesiyle yazın:\n  " + "\n  ".join(offenders)
    )


# Reads of one organisation's own queue: any member may read (a viewer too), nobody without an
# organisation, and the rows are selected by that organisation only (tested over HTTP in
# test_statement_direction_flow). Classified here so a new read route in the family cannot go unguarded.
MEMBER_READ_ROUTES = [
    ("GET", "/api/v1/held-rows"),
    ("GET", "/api/v1/held-rows/file-questions"),
    ("GET", "/api/v1/held-rows/direction-mappings"),
    ("GET", "/api/v1/org/base-currency"),
]


def test_member_read_routes_are_guarded_by_require_member() -> None:
    by_key = dict(ROUTES)
    for key in MEMBER_READ_ROUTES:
        assert key in by_key, f"{key} no longer exists: update MEMBER_READ_ROUTES"
        assert access.require_member in _calls(by_key[key]), f"{key} reads an organisation's queue without require_member"
    held = [k for k in by_key if k[0] == "GET" and k[1].startswith("/api/v1/held-rows")]
    assert sorted(held) == sorted(k for k in MEMBER_READ_ROUTES if "held-rows" in k[1]), "an unclassified held-rows read route"


def test_the_allow_lists_name_routes_that_exist_and_do_not_overlap() -> None:
    keys = {k for k, _ in _changing()}
    guarded = {k for k, r in _changing() if _guarded(r)}
    for name, table in (("OPEN_ROUTES", OPEN_ROUTES), ("INLINE_GUARDED", INLINE_GUARDED)):
        assert not [k for k in table if k not in keys], f"{name}: artık olmayan rota"
        assert not [k for k in table if k in guarded], f"{name}: zaten korunan rota"
        assert not [k for k in table if k in PUBLIC_ROUTES], f"{name}: herkese açık listede de"
    assert not set(OPEN_ROUTES) & set(INLINE_GUARDED)


def test_the_role_classes_are_all_in_use() -> None:
    used = set().union(*(_guards_of(r) for _, r in _changing()))
    assert used == GUARD_FUNCS


def test_a_look_alike_dependency_is_not_a_guard() -> None:
    """The old test accepted any dependency called `_check`."""

    async def _check() -> None: ...

    assert not _is_role_closure(_check)
    assert _check not in GUARD_FUNCS


# What counts as "the handler really checks the role": it reaches the one
# resolver of the acting role (membership role in the acting organisation), or
# reads the caller's membership row itself (briefing release, org erasure).
_RESOLVERS = {access.acting_role, access.OrgMembership}


def _reachable(fn, seen=None, depth=0) -> set:
    """Functions and classes a handler references, followed through functions
    defined in the app (resolved by the module's own globals), a few levels deep."""
    seen = set() if seen is None else seen
    if fn in seen or depth > 4:
        return seen
    seen.add(fn)
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError):
        return seen
    scope = dict(fn.__globals__)
    for node in ast.walk(tree):  # imports made inside the handler
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            module = importlib.import_module(node.module)
            for alias in node.names:
                if hasattr(module, alias.name):
                    scope[alias.asname or alias.name] = getattr(module, alias.name)
    targets: list = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in scope:
            targets.append(scope[node.id])
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            owner = scope.get(node.value.id)  # `payment_plan.propose(...)`
            if isinstance(owner, types.ModuleType) and owner.__name__.startswith("app."):
                targets.append(getattr(owner, node.attr, None))
    for obj in targets:
        if isinstance(obj, types.FunctionType) and obj.__module__.startswith("app."):
            _reachable(obj, seen, depth + 1)
        elif isinstance(obj, type):
            seen.add(obj)
    return seen


# A handler whose check is "you are the author", not a role: the function that
# makes it must be reachable instead.
_AUTHOR_CHECKED = {("POST", "/api/v1/ledger/plan-changes/{change_id}/withdraw"): payment_plan.withdraw}


def test_every_inline_guarded_handler_reaches_the_role_resolver() -> None:
    """INLINE_GUARDED was asserted by string; a handler could lose its check and pass."""
    routes = dict(_changing())
    missing = [
        f"{m} {p}" for (m, p) in INLINE_GUARDED
        if not (_reachable(routes[(m, p)].endpoint) & (_RESOLVERS | {_AUTHOR_CHECKED.get((m, p))}))
    ]
    assert not missing, "satır içi korumalı ama rol çözücüye ulaşmıyor:\n  " + "\n  ".join(missing)


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
CONTRIBUTORS = {"analyst", "cfo", "admin", "owner", "smmm"}  # everyone but a viewer


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
        # contributor: bringing data in and running an analysis on it — an analyst may
        ("POST", "/api/v1/upload", None, CONTRIBUTORS),
        ("POST", "/api/v1/analyze/nope", None, CONTRIBUTORS),
        ("POST", "/api/v1/analysis/nope/rerun", None, CONTRIBUTORS),
        ("POST", "/api/v1/datasource/nope/sales/csv", None, CONTRIBUTORS),
        ("POST", "/api/v1/erp/mikro/sync", None, CONTRIBUTORS),
        # ...but not what changes or decides a record
        ("DELETE", "/api/v1/datasource/nope/nope", None, {"cfo", "admin", "owner", "smmm"}),
        ("POST", "/api/v1/erp/logo-tiger/connect", {}, {"admin", "owner"}),
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
