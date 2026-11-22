"""The materiality threshold is proportional to the company, applies only after acknowledgement, and is
only materiality.

`app/services/materiality.py`. Pure computation (measured, declared fallback, floor, ceiling, rounding),
the ledger measurement, the HTTP flow (proposal -> acknowledgement -> applied; override), who may do
what, and the integrity gates, which never read the threshold.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.canonical_transaction import CanonicalTransaction
from app.models.decision import Decision
from app.models.organization import Organization
from app.platform.authority_matrix import (
    DEFAULT_POLICY_RULES,
    AuthorityRequest,
    evaluate,
    load_active_rules,
)
from app.services import materiality as m
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.test_payment_plan_changes import member

URL = "/api/v1/org/me/materiality"
LIRA = 100


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def measured(monthly_lira: int, months: int = 6) -> dict:
    return {"avg_cents": monthly_lira * LIRA, "months": [f"2026-0{i}" for i in range(1, months + 1)], "currency": "TRY"}


# ── the computation ──────────────────────────────────────────────────────────

def test_the_threshold_is_a_share_of_the_companys_own_monthly_outflow():
    small = m.compute(measured=measured(2_000_000 // 12), declared_band=None)  # a 2 million lira a year company
    large = m.compute(measured=measured(200_000_000 // 12), declared_band=None)  # a 200 million lira a year company
    assert small is not None and large is not None
    assert small["amount_cents"] == 8_300 * LIRA and small["source"] == m.MEASURED
    assert large["amount_cents"] == 830_000 * LIRA
    assert small["basis"]["clamped"] is None and large["basis"]["clamped"] is None
    # one fixed amount (the legacy 100.000) would be 60% of a month for the first and 0.6% for the second
    assert m.LEGACY_CENTS == 100_000 * LIRA


def test_the_floor_and_the_ceiling_hold():
    tiny = m.compute(measured=measured(20_000), declared_band=None)
    huge = m.compute(measured=measured(500_000_000), declared_band=None)
    assert tiny is not None and huge is not None
    assert (tiny["amount_cents"], tiny["basis"]["clamped"]) == (m.FLOOR_CENTS, "floor")
    assert (huge["amount_cents"], huge["basis"]["clamped"]) == (m.CEILING_CENTS, "ceiling")


def test_without_a_measurement_the_declared_band_is_the_basis_and_without_either_there_is_no_proposal():
    declared = m.compute(measured=None, declared_band="500k_to_5m")
    assert declared is not None and declared["source"] == m.DECLARED
    assert declared["amount_cents"] == 75_000 * LIRA  # 5% of the band's stated middle, 1.500.000
    assert "eyan" in m.basis_text(declared)
    assert m.compute(measured=None, declared_band=None) is None
    assert m.compute(measured=None, declared_band="nonsense") is None


def test_two_significant_figures():
    assert m.round_two_figures(8_333_33) == 8_300 * LIRA
    assert m.round_two_figures(833_333_00) == 830_000 * LIRA
    assert m.round_two_figures(1) == 1 * LIRA
    assert m.round_two_figures(12_500_00) == 13_000 * LIRA


def test_the_basis_sentence_names_the_share_and_the_result():
    text = m.basis_text(m.compute(measured=measured(166_667), declared_band=None))
    assert "%5" in text and "₺8.300" in text and "166.667" in text and "6 tam ay" in text
    assert "Sabit tutar" in m.basis_text(None)


def test_an_amount_in_another_currency_counts_as_material():
    org = Organization(name="x", slug="x")
    assert m.is_material(org, 1, "USD") is True
    assert m.is_material(org, m.LEGACY_CENTS, "TRY") is False  # the threshold itself is not above it
    assert m.is_material(org, m.LEGACY_CENTS + 1, "TRY") is True


# ── the ledger measurement ───────────────────────────────────────────────────

def _months_back(n: int) -> datetime:
    now = datetime.now(UTC)
    year, month = now.year, now.month - n
    while month < 1:
        year, month = year - 1, month + 12
    return datetime(year, month, 15, tzinfo=UTC)


async def seed_outflow(client, org_id: str, per_month_lira: int, months: int) -> None:
    async with client._maker() as db:
        for back in range(1, months + 1):
            db.add(CanonicalTransaction(
                org_id=org_id, source_type="bank_statement", source_record_id=f"out-{back}",
                transaction_date=_months_back(back), amount_cents=per_month_lira * LIRA, currency="TRY",
                direction="expense", basis="cash",
            ))
        await db.commit()


async def test_the_measurement_is_the_average_of_the_last_complete_months(client):
    _, org_id, _ = await kullanici(client, "olc@example.com", role="owner")
    await seed_outflow(client, org_id, 160_000, 8)
    async with client._maker() as db:
        got = await m.measure_monthly_outflow(db, org_id)
    assert got is not None
    assert got["avg_cents"] == 160_000 * LIRA and len(got["months"]) == m.MAX_MONTHS and got["currency"] == "TRY"


async def test_too_few_complete_months_is_no_measurement(client):
    _, org_id, _ = await kullanici(client, "az@example.com", role="owner")
    await seed_outflow(client, org_id, 160_000, 2)
    async with client._maker() as db:
        assert await m.measure_monthly_outflow(db, org_id) is None


# ── the flow: proposal, acknowledgement, applied ─────────────────────────────

async def test_a_proposal_applies_only_after_the_owner_acknowledges_it(client):
    owner, org_id, owner_id = await kullanici(client, "sahip@example.com", role="owner")
    await seed_outflow(client, org_id, 160_000, 6)

    first = (await client.get(URL, headers=owner)).json()["data"]
    assert first["current"]["acknowledged"] is False and first["current"]["source"] == m.LEGACY
    assert first["current"]["threshold_cents"] == m.LEGACY_CENTS
    proposal = first["proposal"]
    assert proposal["amount_cents"] == 8_000 * LIRA and proposal["differs_from_current"] is True
    assert "%5" in proposal["basis_text"]

    # until acknowledged the authority policy still reads exactly as it always did
    rules = await _rules(client, org_id)
    assert _high_value(rules)["when"] == {"amount_kurus_gt": m.LEGACY_CENTS}
    assert evaluate(rules, AuthorityRequest(domain="journal_entry", amount_kurus=20_000 * LIRA)).outcome == "auto_approve"

    # a number other than the one shown is refused (the ledger may have moved while the person read)
    assert (await client.post(f"{URL}/acknowledge", headers=owner, json={"amount_cents": 1234})).status_code == 409
    assert (await client.get(URL, headers=owner)).json()["data"]["current"]["acknowledged"] is False

    ok = await client.post(f"{URL}/acknowledge", headers=owner, json={"amount_cents": proposal["amount_cents"]})
    assert ok.status_code == 200
    cur = ok.json()["data"]["current"]
    assert cur["acknowledged"] and cur["threshold_cents"] == 8_000 * LIRA and cur["source"] == m.MEASURED
    assert cur["acknowledged_by"] == owner_id and "%5" in cur["basis_text"]

    # now it is applied, with its basis shown where the rule applies
    rules = await _rules(client, org_id)
    assert _high_value(rules)["when"] == {"amount_kurus_gt": 8_000 * LIRA}
    assert "%5" in _high_value(rules)["note"]
    decision = evaluate(rules, AuthorityRequest(domain="journal_entry", amount_kurus=20_000 * LIRA))
    assert decision.outcome == "needs_approval" and decision.required_approvals == [{"role": "owner", "count": 1}]
    assert "%5" in decision.rationale

    [rec] = await _records(client, org_id, "proposal_acknowledged")
    assert rec.decided_by == owner_id and rec.before["amount_cents"] == m.LEGACY_CENTS
    assert rec.after["amount_cents"] == 8_000 * LIRA and rec.after["source"] == m.MEASURED
    assert rec.after["basis"]["monthly_outflow_cents"] == 160_000 * LIRA


async def test_with_too_little_data_the_declared_band_is_proposed(client):
    owner, org_id, _ = await kullanici(client, "beyan@example.com", role="owner")
    assert (await client.get(URL, headers=owner)).json()["data"]["proposal"] is None
    assert (await client.post(f"{URL}/acknowledge", headers=owner, json={"amount_cents": 5000})).status_code == 422
    async with client._maker() as db:
        (await db.get(Organization, org_id)).monthly_outflow_band = "under_500k"
        await db.commit()
    proposal = (await client.get(URL, headers=owner)).json()["data"]["proposal"]
    assert proposal["source"] == m.DECLARED and proposal["amount_cents"] == 13_000 * LIRA  # 5% of 250.000, half up
    assert proposal["basis"]["clamped"] is None


async def test_the_owner_may_set_their_own_amount_and_it_is_recorded_with_the_reason(client):
    owner, org_id, owner_id = await kullanici(client, "karar@example.com", role="owner")
    r = await client.put(URL, headers=owner, json={"amount_cents": 30_000 * LIRA, "reason": "ortağımla konuştuk"})
    assert r.status_code == 200
    cur = r.json()["data"]["current"]
    assert cur["source"] == m.OWNER_OVERRIDE and cur["threshold_cents"] == 30_000 * LIRA
    [rec] = await _records(client, org_id, "owner_override")
    assert rec.decided_by == owner_id and rec.reason == "ortağımla konuştuk"
    assert rec.before["amount_cents"] == m.LEGACY_CENTS and rec.after["amount_cents"] == 30_000 * LIRA
    assert (await client.put(URL, headers=owner, json={"amount_cents": 0})).status_code == 422


async def test_who_may_read_and_who_may_change_it(client):
    _owner, org_id, _ = await kullanici(client, "rol@example.com", role="owner")
    viewer = await member(client, "izleyici@example.com", org_id, "viewer")
    analyst = await member(client, "analist@example.com", org_id, "analyst")
    admin = await member(client, "yonetici@example.com", org_id, "admin")
    smmm = await member(client, "musavir@example.com", org_id, "smmm")
    for who in (viewer, analyst, smmm):
        got = await client.get(URL, headers=who)
        assert got.status_code == 200 and got.json()["data"]["can_decide"] is False and got.json()["data"]["proposal"] is None
        assert (await client.put(URL, headers=who, json={"amount_cents": 1000})).status_code == 403
        assert (await client.post(f"{URL}/acknowledge", headers=who, json={"amount_cents": 1000})).status_code == 403
    assert (await client.get(URL, headers=admin)).json()["data"]["can_decide"] is True
    assert (await client.put(URL, headers=admin, json={"amount_cents": 1000})).status_code == 200


async def test_another_companys_threshold_is_not_this_ones(client):
    a, _a_org, _ = await kullanici(client, "a@example.com", role="owner")
    b, b_org, _ = await kullanici(client, "b@example.com", role="owner")
    await client.put(URL, headers=a, json={"amount_cents": 7_000 * LIRA})
    assert (await client.get(URL, headers=b)).json()["data"]["current"]["threshold_cents"] == m.LEGACY_CENTS
    async with client._maker() as db:
        assert (await db.get(Organization, b_org)).materiality_applied is None
        assert _high_value(await load_active_rules(b_org, db))["when"] == {"amount_kurus_gt": m.LEGACY_CENTS}


# ── only materiality ─────────────────────────────────────────────────────────

async def test_only_the_high_value_rule_follows_the_threshold(client):
    owner, org_id, _ = await kullanici(client, "ozel@example.com", role="owner")
    await client.put(URL, headers=owner, json={"amount_cents": 7_000 * LIRA})
    rules = await _rules(client, org_id)
    changed = [r["id"] for r, d in zip(rules, DEFAULT_POLICY_RULES, strict=True) if r != d]
    assert changed == ["high_value"]  # related party, low confidence, unclassified and fixed asset are as they were


_GATES = [
    "app/services/held_rows.py", "app/services/held_direction.py", "app/services/account_identity.py",
    "app/services/reconciliation.py", "app/services/balance_reverify.py", "app/services/bank_balance.py",
    "app/services/statement_account.py", "app/services/duplicate_resolution.py", "app/services/ledger_documents.py",
    "app/core/currency_totals.py", "app/services/runway.py",
]


@pytest.mark.parametrize("path", _GATES)
def test_the_integrity_gates_never_read_the_threshold(path):
    """A row nobody can read, a currency, a direction, an account's identity, a reconciliation and a possible
    duplicate are questions about one upload, not about size: they must not scale away with the company."""
    source = (Path(__file__).resolve().parent.parent / path).read_text(encoding="utf-8")
    assert not re.search(r"materiality|materiality_applied|LEGACY_CENTS", source), path
    for parser in (Path(__file__).resolve().parent.parent / "app" / "parsers").rglob("*.py"):
        assert "materiality" not in parser.read_text(encoding="utf-8"), parser


# ── helpers ──────────────────────────────────────────────────────────────────

async def _rules(client, org_id: str):
    async with client._maker() as db:
        return await load_active_rules(org_id, db)


def _high_value(rules):
    return next(r for r in rules if r["id"] == "high_value")


async def _records(client, org_id: str, outcome: str):
    async with client._maker() as db:
        return list((await db.execute(
            select(Decision).where(Decision.org_id == org_id, Decision.kind == "materiality", Decision.outcome == outcome)
        )).scalars())
