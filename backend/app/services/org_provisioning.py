"""Create an organisation: the one place a company row comes from (workspace screen and pilot invite).

`POST /org/create` and the redemption of a pilot invite both make a company and its owner. The slug rules
(unique, never the reserved `demo-` prefix) and the regional defaults are the same for both.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization


def slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = slug.strip("-")
    return slug[:80]


def regional_defaults(country_code: str) -> dict[str, Any]:
    cc = country_code.upper()
    if cc == "TR":
        return {"country_code": "TR", "base_currency": "TRY", "locale": "tr-TR", "regional_packs": ["tr"]}
    return {"country_code": cc, "base_currency": "USD", "locale": "en-US", "regional_packs": []}


async def unique_slug(db: AsyncSession, wanted: str) -> str:
    """`wanted` or `wanted-1`, `wanted-2`, ... whichever is free. The `demo-` prefix is reserved for guests."""
    base = wanted or "sirket"
    if base.startswith("demo-"):
        base = f"org-{base}"
    slug, counter = base, 1
    while (await db.execute(select(Organization.id).where(Organization.slug == slug))).first() is not None:
        slug = f"{base}-{counter}"
        counter += 1
    return slug


async def create_organisation(
    db: AsyncSession, *, name: str, slug: str | None = None, description: str | None = None,
    country_code: str = "TR",
) -> Organization:
    """Add the organisation to the caller's transaction and flush it (the caller commits)."""
    org = Organization(
        name=name,
        slug=await unique_slug(db, slug or slugify(name)),
        description=description,
        **regional_defaults(country_code),
    )
    db.add(org)
    await db.flush()
    return org
