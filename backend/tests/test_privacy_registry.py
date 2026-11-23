"""The personal-data registry stays complete: a new table or personal-looking column fails here by name."""
from __future__ import annotations

import app.models  # noqa: F401  (registers every table)
from app.database import Base
from app.services import org_erasure
from app.services.privacy import inventory_doc
from app.services.privacy.registry import (
    NOT_PERSONAL,
    THIRD_PARTIES,
    Category,
    Flow,
    looks_personal,
)
from app.services.privacy.registry_stores import STORES
from app.services.privacy.registry_tables import NO_PERSONAL_DATA, TABLES

TABLE_META = Base.metadata.tables


def test_every_table_is_in_the_registry_or_declared_free_of_personal_data() -> None:
    missing = sorted(set(TABLE_META) - TABLES.keys() - NO_PERSONAL_DATA.keys())
    assert not missing, f"add these tables to app/services/privacy/registry_tables.py: {missing}"
    assert all(NO_PERSONAL_DATA.values()), "a NO_PERSONAL_DATA entry needs a reason"
    stale = sorted((TABLES.keys() | NO_PERSONAL_DATA.keys()) - set(TABLE_META))
    assert not stale, f"registry names tables that no longer exist: {stale}"


def test_every_personal_looking_column_is_registered_or_excused() -> None:
    registered = {f"{t}.{c}" for t, meta in TABLES.items() for c in meta.columns}
    unregistered = sorted(
        f"{t}.{c.name}"
        for t, table in TABLE_META.items() for c in table.columns
        if looks_personal(c.name) and f"{t}.{c.name}" not in registered and f"{t}.{c.name}" not in NOT_PERSONAL
    )
    assert not unregistered, (
        f"personal-looking columns with no registry entry: {unregistered}. Register them in "
        "app/services/privacy/registry_tables.py (and say what erasure does) or excuse them in registry.NOT_PERSONAL."
    )


def test_registry_columns_exist() -> None:
    absent = sorted(f"{t}.{c}" for t, meta in TABLES.items() if t in TABLE_META for c in meta.columns
                    if c not in TABLE_META[t].columns)
    assert not absent, f"registered columns that do not exist: {absent}"
    excused_absent = sorted(k for k in NOT_PERSONAL if k.split(".")[1] not in TABLE_META[k.split(".")[0]].columns)
    assert not excused_absent, f"NOT_PERSONAL names columns that do not exist: {excused_absent}"


def test_excused_columns_are_not_also_registered() -> None:
    registered = {f"{t}.{c}" for t, meta in TABLES.items() for c in meta.columns}
    both = sorted(registered & NOT_PERSONAL.keys())
    assert not both, f"both registered and excused: {both}"


def test_every_retained_personal_column_is_scrubbed_by_erasure() -> None:
    """A table the erasure keeps must scrub every personal column the registry lists for it."""
    leaks = []
    for name, rule in org_erasure.RETAINED.items():
        meta = TABLES.get(name)
        assert meta is not None, f"retained table {name} is missing from the registry"
        leaks += [f"{name}.{c}" for c in meta.columns if c not in rule.scrub]
    assert not leaks, f"registered personal columns that erasure leaves in place: {leaks}"


def test_every_scrubbed_column_is_registered() -> None:
    gaps = [f"{n}.{c}" for n, r in org_erasure.RETAINED.items() for c in r.scrub
            if c not in TABLES.get(n, TABLES["users"]).columns]
    assert not gaps, f"erasure scrubs columns the registry does not list: {gaps}"


def test_every_flow_is_described_and_used() -> None:
    assert set(THIRD_PARTIES) == set(Flow)
    used = {f for t in TABLES.values() for f in t.flows} | {f for s in STORES for f in s.flows}
    assert used <= set(Flow)
    assert Flow.LLM in used and Flow.SMTP in used
    assert not THIRD_PARTIES[Flow.LLM].masked, "if masking lands, say so here and in the documents"


def test_credentials_are_a_registered_category() -> None:
    cats = {c for t in TABLES.values() for c in t.columns.values()}
    assert Category.CREDENTIAL in cats and Category.NETWORK in cats and Category.TAX_ID in cats


def test_the_generated_inventory_is_current() -> None:
    current = inventory_doc.DOC_PATH.read_text(encoding="utf-8")
    assert current == inventory_doc.render(), (
        "docs/kvkk/veri-envanteri-uretilen.md is stale: run `python -m app.services.privacy.inventory_doc` in backend/"
    )
