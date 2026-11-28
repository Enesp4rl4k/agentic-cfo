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
    llm = THIRD_PARTIES[Flow.LLM]
    # masking has landed (app/platform/llm_egress): it is said here and in the documents, with its limit
    assert llm.masked and "free text can still hold personal data" in llm.sends and "LLM_DATA_MODE" in llm.switch


def test_credentials_are_a_registered_category() -> None:
    cats = {c for t in TABLES.values() for c in t.columns.values()}
    assert Category.CREDENTIAL in cats and Category.NETWORK in cats and Category.TAX_ID in cats


def test_the_generated_inventory_is_current() -> None:
    current = inventory_doc.DOC_PATH.read_text(encoding="utf-8")
    assert current == inventory_doc.render(), (
        "docs/kvkk/veri-envanteri-uretilen.md is stale: run `python -m app.services.privacy.inventory_doc` in backend/"
    )


def test_every_store_and_every_purge_says_whether_its_retention_is_in_effect() -> None:
    """The KVKK inventory may not call a period a policy when the job only counts it: each store and each retention
    purge declares enforced / dry_run_default / not_applicable with a reason, the generated document shows it, and
    the retention job's behaviour is read from the same registry."""
    from app.services.privacy import retention
    from app.services.privacy.registry import Enforcement
    from app.services.privacy.registry_stores import PURGES

    unstated = [s.key for s in STORES if s.enforcement is None or not s.enforcement_why.strip()]
    assert not unstated, f"stores that do not say whether their retention is in effect: {unstated}"
    vague = [k for k, p in PURGES.items() if not (p.why.strip() and p.tables and p.period.strip())]
    assert not vague, f"purges without a reason, tables or period: {vague}"

    stores = {s.key: s for s in STORES}
    checkpoints = stores["agent_checkpoints"]
    assert checkpoints.enforcement == Enforcement.ENFORCED and "RESTORED" in checkpoints.holds
    assert "erase" in checkpoints.erased_by and "retention job" in checkpoints.erased_by

    enforced = {k for k, p in PURGES.items() if p.enforcement == Enforcement.ENFORCED}
    assert retention.ENFORCED_ALWAYS == enforced == {
        "checkpoints", "checkpoints_unscoped", "checkpoints_orphaned", "erasure_leftovers"}
    assert {k for k, p in PURGES.items() if p.enforcement == Enforcement.DRY_RUN_DEFAULT} == {
        "uploads", "outbox_bodies", "notifications", "alert_history", "tokens", "invitations", "audit_ip"}
    library = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "agent_memory_episodes"}
    unknown = sorted({t for p in PURGES.values() for t in p.tables} - set(TABLE_META) - library)
    assert not unknown, f"purges name tables that do not exist: {unknown}"

    doc = inventory_doc.DOC_PATH.read_text(encoding="utf-8")
    lines = doc.splitlines()
    for key, purge in PURGES.items():
        row = next((ln for ln in lines if ln.startswith(f"| `{key}` | {purge.what}")), None)
        assert row is not None and f"| {purge.enforcement.value} |" in row, f"the inventory does not state purge {key}"
    for store in STORES:
        row = next(ln for ln in lines if ln.startswith(f"| `{store.key}` | {store.holds}"))
        assert f"| {store.enforcement.value}: " in row, f"the inventory does not state store {store.key}"
    llm_logs = next(ln for ln in lines if ln.startswith("| `llm_call_logs` |"))
    assert "never its message" in llm_logs
