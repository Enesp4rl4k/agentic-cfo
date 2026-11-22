"""One spelling per mailbox: the normaliser, every lookup, the migration, and what a request leaves behind."""
from __future__ import annotations

import ast
import logging
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import select

from app.core.email_address import normalize_email
from app.models.organization import OrgInvite
from app.models.user import User
from app.services.secret_tokens import hash_token
from tests.api_helpers import PAROLA, bellek_istemcisi, kullanici

P = "/api/v1"
APP = Path(__file__).resolve().parent.parent / "app"


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _load_migration():
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "069_normalised_emails.py"
    spec = importlib.util.spec_from_file_location("migration_069", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── the normaliser ──────────────────────────────────────────────────────────

def test_the_normaliser_folds_case_space_and_compatibility_forms_but_not_plus_or_dots():
    assert normalize_email("  Yeni.Kisi@Example.COM ") == "yeni.kisi@example.com"
    assert normalize_email("ａｄａ@example.com") == "ada@example.com"  # full-width letters
    assert normalize_email("ada+fatura@example.com") == "ada+fatura@example.com"
    assert normalize_email("a.da@example.com") != normalize_email("ada@example.com")


def test_the_migration_normalises_exactly_like_the_application():
    migration = _load_migration()
    for sample in ("Ada@Example.com", " ada@EXAMPLE.com\t", "ＡＤＡ@example.com", "a.da+x@Example.com"):
        assert migration._normalize(sample) == normalize_email(sample)
        assert unicodedata.is_normalized("NFKC", normalize_email(sample))


# ── the flows ───────────────────────────────────────────────────────────────

async def seed_invite(client, org_id: str, email: str, role: str = "viewer") -> str:
    token = "m" * 64
    async with client._maker() as db:
        db.add(OrgInvite(org_id=org_id, email=email, role=role, token_hash=hash_token(token), accepted=False,
                         expires_at=datetime.now(UTC) + timedelta(days=7)))
        await db.commit()
    return token


async def an_org(client) -> str:
    _, org, _ = await kullanici(client, "sahip@example.com", role="owner")
    return org


async def test_invite_mixed_case_accept_then_login_with_any_spelling(client):
    org = await an_org(client)
    token = await seed_invite(client, org, "Yeni.Kisi@Example.com")
    r = await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA})
    assert r.status_code == 201, r.text
    for spelling in ("Yeni.Kisi@Example.com", "yeni.kisi@example.com", "YENI.KISI@EXAMPLE.COM", " yeni.kisi@example.com "):
        login = await client.post(f"{P}/auth/login", json={"email": spelling, "password": PAROLA})
        assert login.status_code == 200, spelling


async def test_registering_a_case_variant_gets_the_ordinary_already_registered_answer(client):
    first = await client.post(f"{P}/auth/register", json={"email": "Ada@example.com", "password": PAROLA})
    same = await client.post(f"{P}/auth/register", json={"email": "Ada@example.com", "password": PAROLA})
    variant = await client.post(f"{P}/auth/register", json={"email": "ada@EXAMPLE.com", "password": PAROLA})
    assert first.status_code == 201
    assert same.status_code == 400
    assert (variant.status_code, variant.json()) == (same.status_code, same.json())
    async with client._maker() as db:
        assert len((await db.execute(select(User))).scalars().all()) == 1


async def test_two_case_variants_cannot_both_exist_even_when_written_around_the_model(client):
    from sqlalchemy.exc import IntegrityError

    async with client._maker() as db:
        db.add(User(email="Ada@example.com", hashed_password="x"))
        await db.commit()
    async with client._maker() as db:
        # Bypass the model's own normalising: the index is the backstop.
        with pytest.raises(IntegrityError):
            await db.execute(sa.text(
                "INSERT INTO users (id, email, hashed_password, role, is_active) "
                "VALUES ('x1', 'ADA@example.com', 'x', 'analyst', 1)"
            ))


async def test_sso_with_a_case_variant_links_the_existing_account(client):
    from app.services.sso import OAuthUser, provision_sso_user

    await client.post(f"{P}/auth/register", json={"email": "Ada@example.com", "password": PAROLA})
    async with client._maker() as db:
        user = await provision_sso_user(
            OAuthUser(provider="google", provider_id="g1", email="ADA@Example.com", full_name="Ada"), db
        )
        assert user.sso_provider == "google"
        assert len((await db.execute(select(User))).scalars().all()) == 1


async def test_password_reset_looks_the_account_up_in_any_spelling(client):
    """The reset flow is one of the lookups: an address typed in another case or width finds the account.

    (It used to be recorded here that there was no reset flow. The structural test at the end of this
    file also covers its query: it compares `User.email` with a `normalize_email(...)` value.)"""
    from app.models.outbox_message import OutboxMessage

    await client.post(f"{P}/auth/register", json={"email": "Ada@Example.com", "password": PAROLA})
    for spelling in (" ADA@example.COM", "ａｄａ@example.com"):
        answer = await client.post(f"{P}/auth/forgot-password", json={"email": spelling})
        assert answer.status_code == 200, spelling
    async with client._maker() as db:
        rows = (await db.execute(select(OutboxMessage).where(OutboxMessage.kind == "password_reset"))).scalars().all()
    assert {r.recipient for r in rows} == {"ada@example.com"} and len(rows) == 2


# ── the migration ───────────────────────────────────────────────────────────

def _migrate(rows, invites=()):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, email VARCHAR(255) NOT NULL UNIQUE)"))
        conn.execute(sa.text("CREATE TABLE org_invites (id VARCHAR(36) PRIMARY KEY, email VARCHAR(255) NOT NULL)"))
        for uid, email in rows:
            conn.execute(sa.text("INSERT INTO users VALUES (:i, :e)"), {"i": uid, "e": email})
        for iid, email in invites:
            conn.execute(sa.text("INSERT INTO org_invites VALUES (:i, :e)"), {"i": iid, "e": email})
    migration = _load_migration()
    return engine, migration, MigrationContext, Operations


def _has_index(conn) -> bool:
    return conn.execute(sa.text("SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_users_email_lower'")).first() is not None


def test_the_migration_normalises_existing_rows_adds_the_index_and_downgrades():
    engine, migration, Ctx, Ops = _migrate([("u1", "Ada@Example.com"), ("u2", "bob@x.com ")], [("i1", "Ada@Example.COM")])
    with engine.begin() as conn, Ops.context(Ctx.configure(conn)):
        migration.upgrade()
    with engine.connect() as conn:
        assert sorted(r[0] for r in conn.execute(sa.text("SELECT email FROM users"))) == ["ada@example.com", "bob@x.com"]
        assert conn.execute(sa.text("SELECT email FROM org_invites")).scalar() == "ada@example.com"
        assert _has_index(conn)
    with engine.begin() as conn, Ops.context(Ctx.configure(conn)):
        migration.downgrade()
    with engine.connect() as conn:
        assert not _has_index(conn)


def test_the_migration_aborts_without_touching_data_when_accounts_collide():
    engine, migration, Ctx, Ops = _migrate([("u1", "Ada@Example.com"), ("u2", "ada@example.com"), ("u3", "Zed@x.com")])
    with pytest.raises(RuntimeError) as err, engine.begin() as conn, Ops.context(Ctx.configure(conn)):
        migration.upgrade()
    message = str(err.value)
    assert "u1" in message and "u2" in message and "u3" not in message
    assert "@" not in message, "ids only, no addresses"
    with engine.connect() as conn:
        assert sorted(r[0] for r in conn.execute(sa.text("SELECT email FROM users"))) == [
            "Ada@Example.com", "Zed@x.com", "ada@example.com",
        ]
        assert not _has_index(conn)


# ── the invitation path never answers 500 ───────────────────────────────────

async def test_a_lost_race_for_the_account_is_a_409_not_a_500(client, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import AsyncSession

    org = await an_org(client)
    token = await seed_invite(client, org, "yeni@example.com")
    real_flush = AsyncSession.flush

    async def flush(self, *a, **k):
        if any(isinstance(o, User) and o.email == "yeni@example.com" for o in self.new):
            raise IntegrityError("insert", {}, Exception("duplicate"))
        return await real_flush(self, *a, **k)

    monkeypatch.setattr(AsyncSession, "flush", flush)
    r = await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA})
    assert r.status_code == 409
    monkeypatch.undo()
    # The claim was rolled back with it: trying again works.
    assert (await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA})).status_code == 201


# ── what a request leaves behind, and what it costs ─────────────────────────

async def test_accept_and_preview_leave_neither_token_nor_password_in_the_logs(client, caplog):
    org = await an_org(client)
    token = await seed_invite(client, org, "yeni@example.com")
    caplog.set_level(logging.DEBUG)
    await client.post(f"{P}/org/invite/preview", json={"token": token})
    await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA})
    ours = " ".join(r.getMessage() for r in caplog.records if r.name.startswith("app"))
    assert token not in ours and PAROLA not in ours


def test_the_audit_middleware_redacts_the_invitation_secrets_before_storing_a_body():
    """The audit middleware is the one that buffers request bodies; it keeps neither field."""
    from app.middleware.audit import _redact_body

    kept = _redact_body({"token": "t" * 64, "password": PAROLA, "full_name": "Ada"})
    assert "t" * 64 not in str(kept) and PAROLA not in str(kept) and kept["full_name"] == "Ada"


async def test_an_authenticated_request_reads_the_user_row_at_most_twice(client):
    headers, _, _ = await kullanici(client, "tek@example.com", role="owner")
    engine = client._maker.kw["bind"].sync_engine
    seen: list[str] = []

    def count(_conn, _cursor, statement, *_a):
        if "FROM users" in statement and "WHERE users.id" in statement:
            seen.append(statement)

    sa.event.listen(engine, "before_cursor_execute", count)
    try:
        for url in (f"{P}/org/me", f"{P}/org/memberships"):
            seen.clear()
            assert (await client.get(url, headers=headers)).status_code == 200
            assert len(seen) <= 2, (url, seen)
    finally:
        sa.event.remove(engine, "before_cursor_execute", count)


# ── architecture: no lookup of an e-mail column without the normaliser ──────

_EMAIL_OWNERS = {"User", "OrgInvite", "PilotInvite"}


def _is_email_column(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute) and node.attr == "email"
        and isinstance(node.value, ast.Name) and node.value.id in _EMAIL_OWNERS
    )


def _is_normalised(node: ast.AST) -> bool:
    if isinstance(node, ast.ListComp):
        return _is_normalised(node.elt)
    return isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "normalize_email"


def test_every_query_on_an_email_column_goes_through_the_normaliser():
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            where = f"{path.relative_to(APP)}:{getattr(node, 'lineno', 0)}"
            if isinstance(node, ast.Compare) and any(_is_email_column(n) for n in [node.left, *node.comparators]):
                others = [n for n in [node.left, *node.comparators] if not _is_email_column(n)]
                if not all(_is_normalised(o) for o in others):
                    offenders.append(where)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"in_", "ilike", "like", "startswith"} and _is_email_column(node.func.value):
                    if not all(_is_normalised(a) for a in node.args):
                        offenders.append(where)
                if node.func.attr == "filter_by" and any(k.arg == "email" and not _is_normalised(k.value) for k in node.keywords):
                    offenders.append(where)
    assert offenders == [], "compare e-mail columns only with normalize_email(...): " + ", ".join(offenders)
