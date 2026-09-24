"""A category correction is one company's rule, not everyone's.

Rules were saved with no organisation and the upsert matched by vendor name
alone, so company A correcting "Migros" to `food` rewrote company B's rule for
Migros; and the rule lookup read every company's rules.
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select

from app.services.classifier import classify, learn
from tests.api_helpers import bellek_istemcisi


@pytest_asyncio.fixture
async def db():
    async with bellek_istemcisi() as c, c._maker() as session:
        yield session


async def test_one_companys_correction_does_not_rewrite_anothers(db):
    from app.models.category_rule import CategoryRule

    await learn("Migros market", "Migros", "rent", True, db, org_id="org-b")
    await learn("Migros market", "Migros", "other_expense", True, db, org_id="org-a")

    kurallar = {r.org_id: r.category for r in (await db.execute(select(CategoryRule))).scalars()}
    assert kurallar == {"org-a": "other_expense", "org-b": "rent"}


async def test_a_company_is_classified_by_its_own_rules_only(db):
    await learn("Migros market", "Migros", "rent", True, db, org_id="org-b")

    assert await classify("Migros market", "Migros", db, org_id="org-b") == "rent"
    # Company A never taught this rule; it gets the built-in heuristics.
    assert await classify("Migros market", "Migros", db, org_id="org-a") != "rent"
    assert await classify("Migros market", "Migros", db) != "rent"


async def test_keyword_rules_are_scoped_too(db):
    # A category the built-in heuristics would never pick for this text, so a
    # "rent" answer can only have come from the rule.
    await learn("ACME yazılım lisansı", None, "rent", False, db, org_id="org-b")

    assert await classify("ACME yazılım lisansı yenileme", None, db, org_id="org-b") == "rent"
    assert await classify("ACME yazılım lisansı yenileme", None, db, org_id="org-a") != "rent"
