"""Erasing an organisation must erase it — every table, derived from the schema.

The seeder below fills *every* org-scoped table with rows whose every text and
JSON column carries a marker (``ZZPIIA`` for the organisation being erased,
``ZZPIIB`` for its neighbour). Nothing here lists tables by hand: a table added
to the models later is seeded, erased and scanned automatically, and a table the
erasure cannot place fails `test_every_table_is_classified`.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    insert,
    select,
)
from sqlalchemy.types import BigInteger

from app.database import Base
from app.services import org_erasure as svc
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.db_helpers import gecici_veritabani

PII = {"A": "ZZPIIA", "B": "ZZPIIB"}
OVERRIDES: dict[str, dict[str, Any]] = {
    "canonical_transactions": {"basis": "book", "ledger_status": "active"},
    "journal_lines": {"borc_kurus": 1, "alacak_kurus": 0},
    "open_items": {"status": "open", "direction": "receivable", "paid_cents": 0},
    "open_item_matches": {"status": "confirmed"},
    "smmm_onay_kayitlari": {"durum": "bekliyor"},
    "decisions": {"supersedes_id": None, "decided_via": "human", "rule_id": None},
}
SCOPE = svc.derive_scope()


def _value(col: Any, tag: str) -> Any:
    t = col.type
    if isinstance(t, JSON):
        return {"k": PII[tag]}
    if isinstance(t, String | Text):  # Text subclasses nothing of String in SQLAlchemy
        n = getattr(t, "length", None) or 200
        return f"{PII[tag]}{uuid.uuid4().hex}"[:n]
    if isinstance(t, Boolean):
        return False
    if isinstance(t, Integer | BigInteger | Float | Numeric):
        return 1
    if isinstance(t, DateTime):
        return datetime.now(UTC)
    if isinstance(t, Date):
        return date.today()
    raise AssertionError(f"seeder cannot fill {col.table.name}.{col.name}: {t!r}")


async def _insert(db: Any, table: Table, tag: str, **fixed: Any) -> str:
    row: dict[str, Any] = {}
    for col in table.columns:
        if col.name in fixed:
            row[col.name] = fixed[col.name]
        elif col.name in OVERRIDES.get(table.name, {}):
            row[col.name] = OVERRIDES[table.name][col.name]
        elif col.nullable and col.name not in ("job_id",) and not isinstance(col.type, String | Text | JSON):
            continue
        else:
            row[col.name] = _value(col, tag)
    pk = next(iter(table.primary_key.columns)).name
    row[pk] = fixed.get(pk, str(uuid.uuid4()))
    await db.execute(insert(table).values(**row))
    return row[pk]


async def seed(db: Any, tag: str, org_id: str, extra_member: str | None = None) -> dict[str, Any]:
    """One org: owner + member (+ a shared member), a row in every scoped table, files' paths."""
    T = Base.metadata.tables
    ids: dict[str, Any] = {"org": org_id, "users": []}
    await _insert(db, T["organizations"], tag, id=org_id, slug=f"org-{tag}-{uuid.uuid4().hex[:6]}",
                  country_code="TR", base_currency="TRY", locale="tr-TR", plan="free",
                  subscription_plan="free", subscription_status="inactive", max_members=5,
                  max_jobs_per_month=5, is_active=True, regional_packs=[])
    for role in ("owner", "analyst"):
        uid = await _insert(db, T["users"], tag, org_id=org_id, role=role, is_active=True,
                            email=f"{PII[tag].lower()}-{role}-{uuid.uuid4().hex[:6]}@x.test")
        ids["users"].append(uid)
        await _insert(db, T["org_memberships"], tag, user_id=uid, org_id=org_id, role=role)
    if extra_member:
        await _insert(db, T["org_memberships"], tag, user_id=extra_member, org_id=org_id, role="analyst")
    owner = ids["users"][0]
    order = sorted((n for n in SCOPE if n != "org_memberships"), key=lambda n: svc._depth(n, SCOPE))
    for name in order:
        fixed: dict[str, Any] = {"org_id": org_id} if "org_id" in Base.metadata.tables[name].c else {}
        for col in Base.metadata.tables[name].columns:
            for fk in col.foreign_keys:
                if fk.column.table.name == "users":
                    fixed[col.name] = owner
        for col, parent, _ in SCOPE[name][1]:
            fixed[col] = ids[parent]
        ids[name] = await _insert(db, Base.metadata.tables[name], tag, **fixed)
    # linked through the users
    for uid in ids["users"]:
        await _insert(db, T["audit_logs"], tag, user_id=uid, user_email=f"{uid}@x.test")
    await _insert(db, T["pilot_invites"], tag, used_by_user_id=owner)
    muh = await _insert(db, T["smmm_muhasebeci"], tag, user_id=owner)
    await _insert(db, T["smmm_musteri_kayit"], tag, muhasebeci_id=muh, client_org_id=None)
    return ids


async def _two_orgs(db: Any) -> tuple[dict[str, Any], dict[str, Any], str]:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    ids_b = await seed(db, "B", b)
    shared = await _insert(db, Base.metadata.tables["users"], "B", org_id=a, role="analyst",
                           is_active=True, email=f"shared-{uuid.uuid4().hex[:6]}@x.test")
    await _insert(db, Base.metadata.tables["org_memberships"], "B", user_id=shared, org_id=b, role="analyst")
    ids_a = await seed(db, "A", a, extra_member=shared)
    # an accountant of B who lists A as a client
    muh_b = (await db.execute(select(Base.metadata.tables["smmm_muhasebeci"].c.id))).scalars().first()
    await _insert(db, Base.metadata.tables["smmm_musteri_kayit"], "A", muhasebeci_id=muh_b, client_org_id=a)
    await db.commit()
    return ids_a, ids_b, shared


async def _rows(db: Any, table: Table) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in (await db.execute(select(table))).all()]


def _text_cols(table: Table) -> list[str]:
    return [c.name for c in table.columns if isinstance(c.type, String | Text | JSON)]


def _keyish(table: Table) -> set[str]:
    return {c.name for c in table.columns if c.name == "id" or c.name.endswith("_id") or c.foreign_keys}


def _leaks(rows: list[dict[str, Any]], table: Table, token: str, allowed: set[str]) -> list[str]:
    skip = allowed | _keyish(table)
    return [
        f"{table.name}.{c}" for r in rows for c in _text_cols(table)
        if c not in skip and token in str(r[c])
    ]


def _b_rows(rows: list[dict[str, Any]], table: Table) -> int:
    return sum(1 for r in rows if any(PII["B"] in str(r[c]) for c in _text_cols(table)))


@pytest_asyncio.fixture
async def maker():
    async with gecici_veritabani() as m:
        yield m


# ── The schema derivation itself ─────────────────────────────────────────────

def test_every_table_is_classified() -> None:
    assert svc.unclassified_tables() == [], (
        "table neither derived as org-scoped nor handled in app/services/org_erasure.py"
    )


def test_a_new_org_scoped_table_is_picked_up_without_listing_it() -> None:
    md = MetaData()
    for t in Base.metadata.tables.values():
        t.to_metadata(md)
    Table("future_things", md, Column("id", String(36), primary_key=True), Column("org_id", String(36)))
    Table("future_children", md, Column("id", String(36), primary_key=True),
          Column("thing_id", String(36), __import__("sqlalchemy").ForeignKey("future_things.id")))
    Table("future_orphans", md, Column("id", String(36), primary_key=True), Column("note", Text))
    scope = svc.derive_scope(md)
    assert "future_things" in scope and "future_children" in scope
    assert svc.unclassified_tables(md) == ["future_orphans"]


def test_retained_tables_account_for_every_text_column() -> None:
    for name, rule in svc.RETAINED.items():
        table = Base.metadata.tables[name]
        for col in rule.scrub + rule.keep:
            assert col in table.c, f"{name}.{col} does not exist"
        unaccounted = set(_text_cols(table)) - _keyish(table) - set(rule.scrub) - set(rule.keep)
        assert not unaccounted, f"{name}: classify {sorted(unaccounted)} as scrub or keep"
        assert not set(rule.scrub) & set(rule.keep)


def test_retained_tables_are_known_tables() -> None:
    assert set(svc.RETAINED) <= set(Base.metadata.tables)
    assert set(svc.SOFT_LINKS) <= set(Base.metadata.tables)
    assert not svc.BOOKKEEPING_TABLES & set(svc.derive_scope())


# ── Behaviour ────────────────────────────────────────────────────────────────

async def test_anonymise_leaves_no_personal_data_and_spares_the_neighbour(maker, tmp_path: Path) -> None:
    async with maker() as db:
        a, b, shared = await _two_orgs(db)
        b_counts = {
            n: _b_rows(await _rows(db, t), t) for n, t in Base.metadata.tables.items()
            if n not in svc.BOOKKEEPING_TABLES
        }
        job_a = a["analysis_jobs"]
        (tmp_path / "uploads" / job_a).mkdir(parents=True)
        (tmp_path / "uploads" / job_a / "d.csv").write_text("x")
        (tmp_path / "reports" / job_a).mkdir(parents=True)
        (tmp_path / "reports" / job_a / "r.pdf").write_text("x")
        (tmp_path / "uploads" / b["analysis_jobs"]).mkdir(parents=True)
        (tmp_path / "uploads" / b["analysis_jobs"] / "keep.csv").write_text("x")
        outside = tmp_path.parent / f"outside-{uuid.uuid4().hex}.txt"
        outside.write_text("x")

        res = await svc.erase_org(db, a["org"], mode="anonymise", storage_root=tmp_path)
        assert not res.already_erased

        tables = Base.metadata.tables
        for name, table in tables.items():
            if name in svc.BOOKKEEPING_TABLES:
                continue
            rows = await _rows(db, table)
            if name in svc.RETAINED:
                rule = svc.RETAINED[name]
                assert not _leaks(rows, table, PII["A"], set(rule.keep)), name
                if name != "organizations":
                    # the retained books keep their rows (amounts, dates, codes)
                    assert any(PII["A"] in str(r[c]) for r in rows for c in rule.keep) or not rule.keep, name
            else:
                assert not _leaks(rows, table, PII["A"], set()), name
                scoped = svc._clause(table, a["org"], SCOPE, tables) if name in SCOPE else None
                if scoped is not None:
                    assert (await db.execute(select(table).where(scoped))).first() is None, name

        # the neighbour is untouched: same rows carrying B's marker as before the erasure
        for name, table in tables.items():
            if name not in svc.BOOKKEEPING_TABLES:
                assert b_counts[name] == _b_rows(await _rows(db, table), table), name
        assert b_counts["transactions"] == 1 and b_counts["users"] >= 2

        # the shared member keeps their account, moved onto the other org
        u = tables["users"]
        shared_row = (await db.execute(select(u).where(u.c.id == shared))).one()
        assert shared_row.org_id == b["org"] and shared_row.is_active
        m = tables["org_memberships"]
        assert (await db.execute(select(m).where(m.c.org_id == a["org"]))).first() is None
        assert (await db.execute(select(m).where(m.c.user_id == shared, m.c.org_id == b["org"]))).first()

        # the organisation row is anonymised, not deleted; erased users are gone
        o = tables["organizations"]
        org_row = (await db.execute(select(o).where(o.c.id == a["org"]))).one()
        assert org_row.is_active is False
        assert org_row.name == svc.ERASED and org_row.slug.startswith("erased-")
        assert (await db.execute(select(u).where(u.c.id.in_(a["users"])))).first() is None

        # files: A's gone, B's and anything outside the root untouched
        assert not (tmp_path / "uploads" / job_a).exists()
        assert not (tmp_path / "reports" / job_a).exists()
        assert (tmp_path / "uploads" / b["analysis_jobs"] / "keep.csv").exists()
        assert outside.exists()
        outside.unlink()


async def test_hard_delete_leaves_no_row_at_all(maker, tmp_path: Path) -> None:
    async with maker() as db:
        a, b, _ = await _two_orgs(db)
        await svc.erase_org(db, a["org"], mode="hard_delete", storage_root=tmp_path)
        tables = Base.metadata.tables
        for name, table in tables.items():
            if name in svc.BOOKKEEPING_TABLES:
                continue
            assert not _leaks(await _rows(db, table), table, PII["A"], set()), name
            if name in SCOPE:
                scoped = svc._clause(table, a["org"], SCOPE, tables)
                assert (await db.execute(select(table).where(scoped))).first() is None, name
        o = tables["organizations"]
        assert (await db.execute(select(o).where(o.c.id == a["org"]))).first() is None
        assert (await db.execute(select(o).where(o.c.id == b["org"]))).first() is not None
        assert any(PII["B"] in str(r["description"]) for r in await _rows(db, tables["transactions"]))


async def test_the_erasure_record_is_evidence_without_personal_data(maker, tmp_path: Path) -> None:
    async with maker() as db:
        a, _, _ = await _two_orgs(db)
        res = await svc.erase_org(db, a["org"], storage_root=tmp_path, requested_by_hash=svc.hash_id("user", "u1"))
        rec = res.record
        blob = repr((rec.org_hash, rec.requested_by_hash, rec.confirmed_by_hash, rec.counts, rec.mode))
        for forbidden in [a["org"], PII["A"], *a["users"]]:
            assert forbidden not in blob
        assert rec.org_hash == svc.hash_id("org", a["org"])
        assert rec.counts["transactions"]["anonymised"] == 1
        assert rec.counts["users"]["deleted"] == 2
        assert rec.counts["_files"]["deleted"] >= 0
        assert await svc.verify_chain(db) == []

        rec.counts = {**rec.counts, "users": {"deleted": 0}}  # tamper
        await db.commit()
        assert await svc.verify_chain(db) == [rec.seq]


async def test_erasure_is_idempotent_and_hard_delete_can_follow_anonymise(maker, tmp_path: Path) -> None:
    async with maker() as db:
        a, _, _ = await _two_orgs(db)
        first = await svc.erase_org(db, a["org"], storage_root=tmp_path)
        again = await svc.erase_org(db, a["org"], storage_root=tmp_path)
        assert again.already_erased and again.record.id == first.record.id
        rt = Base.metadata.tables["org_erasure_records"]
        assert len(await _rows(db, rt)) == 1

        hard = await svc.erase_org(db, a["org"], mode="hard_delete", storage_root=tmp_path)
        assert not hard.already_erased and hard.record.seq == 2
        assert (await svc.erase_org(db, a["org"], mode="anonymise", storage_root=tmp_path)).already_erased
        assert await svc.verify_chain(db) == []


async def test_a_failure_rolls_everything_back(maker, tmp_path: Path, monkeypatch) -> None:
    async with maker() as db:
        a, _, _ = await _two_orgs(db)

        def boom(*_a: Any, **_k: Any) -> int:
            raise OSError("disk")

        monkeypatch.setattr(svc, "remove_org_files", boom)
        with pytest.raises(OSError):
            await svc.erase_org(db, a["org"], storage_root=tmp_path)
        t = Base.metadata.tables["transactions"]
        assert any(PII["A"] in str(r["description"]) for r in await _rows(db, t))
        assert await _rows(db, Base.metadata.tables["org_erasure_records"]) == []


def test_files_outside_the_storage_root_are_never_touched(tmp_path: Path) -> None:
    root = tmp_path / "store"
    (root / "uploads" / "j1").mkdir(parents=True)
    (root / "uploads" / "j1" / "a.csv").write_text("x")
    victim = tmp_path / "victim.txt"
    victim.write_text("x")
    assert svc.remove_org_files(root, ["j1"], [str(victim), str(root / "uploads" / "j1" / "a.csv")]) == 1
    assert victim.exists() and not (root / "uploads" / "j1").exists()


# ── The endpoint ─────────────────────────────────────────────────────────────

async def _membership(client: Any, user_id: str, org_id: str, role: str) -> None:
    from app.models.organization import OrgMembership

    async with client._maker() as db:
        db.add(OrgMembership(user_id=user_id, org_id=org_id, role=role))
        await db.commit()


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def test_two_step_erasure_over_http(client, monkeypatch) -> None:
    from app.config import get_settings
    from app.models.organization import Organization
    from app.models.transaction import Transaction  # noqa: F401  (table registered)

    own, org_a, uid_own = await kullanici(client, "owner@example.com", role="owner")
    adm, _, uid_adm = await kullanici(client, "admin@example.com", attach_org=False, role="admin")
    ana, _, uid_ana = await kullanici(client, "analyst@example.com", attach_org=False, role="analyst")
    viw, _, uid_viw = await kullanici(client, "viewer@example.com", attach_org=False, role="viewer")
    oth, org_b, uid_oth = await kullanici(client, "ownerb@example.org", role="owner")
    from app.models.user import User

    async with client._maker() as db:
        for uid in (uid_adm, uid_ana, uid_viw):
            (await db.get(User, uid)).org_id = org_a
        await db.commit()
    for uid, role in ((uid_own, "owner"), (uid_adm, "admin"), (uid_ana, "analyst"),
                      (uid_viw, "viewer"), (uid_oth, "owner")):
        await _membership(client, uid, org_b if uid == uid_oth else org_a, role)

    url = "/api/v1/compliance/org-erasure"
    for h in (ana, viw):  # ordinary members cannot even ask
        assert (await client.post(f"{url}/request", json={}, headers=h)).status_code == 403
    assert (await client.post(f"{url}/request", json={})).status_code in (401, 403)

    monkeypatch.setattr(get_settings(), "org_erasure_hard_delete_enabled", True)
    r = await client.post(f"{url}/request", json={"mode": "hard_delete"}, headers=adm)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    rid, phrase = data["request_id"], data["confirmation_phrase"]
    assert data["mode"] == "hard_delete"
    async with client._maker() as db:  # a request alone erases nothing
        assert (await db.get(Organization, org_a)) is not None

    body = {"confirmation_phrase": phrase}
    assert (await client.post(f"{url}/{rid}/confirm", json=body, headers=adm)).status_code == 403
    assert (await client.post(f"{url}/{rid}/confirm", json=body, headers=ana)).status_code == 403
    assert (await client.post(f"{url}/{rid}/confirm", json=body, headers=oth)).status_code == 404
    assert (await client.post(f"{url}/{rid}/confirm", json={"confirmation_phrase": "yes"}, headers=own)).status_code == 422
    async with client._maker() as db:
        assert (await db.get(Organization, org_a)) is not None

    ok = await client.post(f"{url}/{rid}/confirm", json=body, headers=own)
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["record"]["counts"]["organizations"]["deleted"] == 1
    async with client._maker() as db:
        assert (await db.get(Organization, org_a)) is None
        assert (await db.get(Organization, org_b)) is not None
        assert (await db.get(User, uid_oth)) is not None
        assert (await db.get(User, uid_own)) is None
    # and the caller's own token no longer opens anything
    assert (await client.post(f"{url}/{rid}/confirm", json=body, headers=own)).status_code in (401, 403, 404)


async def test_global_role_does_not_grant_erasure_in_another_org(client) -> None:
    """`users.role` is global; only the membership in the acting org counts."""
    hdr, org, uid = await kullanici(client, "acct@example.com", role="owner")  # no membership row
    r = await client.post("/api/v1/compliance/org-erasure/request", json={}, headers=hdr)
    assert r.status_code == 403
    await _membership(client, uid, org, "smmm")
    r = await client.post("/api/v1/compliance/org-erasure/request", json={}, headers=hdr)
    assert r.status_code == 403


async def test_hard_delete_is_rejected_unless_the_server_enables_it(client, monkeypatch) -> None:
    from app.config import get_settings
    from app.models.erasure_record import OrgErasureRequest

    hdr, org, uid = await kullanici(client, "own@example.com", role="owner")
    await _membership(client, uid, org, "owner")
    url = "/api/v1/compliance/org-erasure"
    settings = get_settings()
    assert settings.org_erasure_hard_delete_enabled is False  # the default

    r = await client.post(f"{url}/request", json={"mode": "hard_delete"}, headers=hdr)
    assert r.status_code == 422 and "hard_delete" in r.text  # rejected, not downgraded
    async with client._maker() as db:
        assert (await db.execute(select(OrgErasureRequest))).first() is None

    monkeypatch.setattr(settings, "org_erasure_hard_delete_enabled", True)
    ok = await client.post(f"{url}/request", json={"mode": "hard_delete"}, headers=hdr)
    assert ok.status_code == 200 and ok.json()["data"]["mode"] == "hard_delete"
    rid, phrase = ok.json()["data"]["request_id"], ok.json()["data"]["confirmation_phrase"]

    # a request made while enabled cannot be confirmed after the switch is turned off
    monkeypatch.setattr(settings, "org_erasure_hard_delete_enabled", False)
    r = await client.post(f"{url}/{rid}/confirm", json={"confirmation_phrase": phrase}, headers=hdr)
    assert r.status_code == 422

    # anonymise needs no switch
    r = await client.post(f"{url}/request", json={}, headers=hdr)
    assert r.status_code == 200 and r.json()["data"]["mode"] == "anonymise"
