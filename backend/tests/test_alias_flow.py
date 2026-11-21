"""G23 review B2 and S4: excluding a duplicate and declaring two suppliers one are two decisions.

- exclude alone creates no alias; it proposes one (both raw names, the consequence in words);
- creating it is a separate call, for an owner, admin or the accountant, recorded as its own decision;
- aliases are listable and revocable per organisation; revoking affects future ingests, lists the rows
  ingested while it was active, rewrites nothing;
- chains, cycles, isolation between organisations, erasure classification;
- excluding a document with money matched to it: what the user sees, and the way out.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.invoice_identity import document_key, key_party, open_item_key, party_token
from app.models.canonical_transaction import CanonicalTransaction
from app.models.counterparty_alias import CounterpartyAlias
from app.models.decision import Decision
from app.models.open_item import OpenItem
from app.models.open_item_match import OpenItemMatch
from app.services.duplicate_resolution import AliasRefused, _pair
from tests.api_helpers import PAROLA, bellek_istemcisi, kullanici
from tests.test_duplicate_resolution_radar import (
    FULL,
    SHORT,
    _aliases,
    _confirm,
    _held,
    _items,
    _radar_out,
    _resolve,
    _rows,
    _upload,
)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _excluded_pair(client, email, role="owner"):
    headers, org_id, user_id = await kullanici(client, email, role=role)
    await _upload(client, org_id, who=FULL)
    await _upload(client, org_id, who=SHORT)
    held = await _held(client, org_id)
    await _resolve(client, headers, held.id, "exclude")
    return headers, org_id, user_id, held


# ── who may declare two counterparties one supplier ──────────────────────────────────────────


@pytest.mark.parametrize("role, allowed", [("owner", True), ("admin", True), ("smmm", True), ("cfo", False)])
async def test_only_a_decider_or_the_accountant_may_create_an_alias(client, role, allowed):
    headers, org_id, _, held = await _excluded_pair(client, f"alias-{role}@example.com", role)
    res = await _confirm(client, headers, held.id)
    assert res.status_code == (200 if allowed else 403), res.text
    assert len(await _aliases(client, org_id)) == (1 if allowed else 0)


async def test_a_plain_writer_can_still_resolve_the_duplicate(client):
    """Excluding stays `require_writer`: a cfo answers "same money", just not "same supplier"."""
    _headers, org_id, _, _ = await _excluded_pair(client, "alias-cfo-resolve@example.com", "cfo")
    assert await _aliases(client, org_id) == []


async def test_an_alias_needs_the_explicit_confirmation_flag(client):
    headers, org_id, _, held = await _excluded_pair(client, "alias-flag@example.com")
    res = await client.post("/api/v1/ledger/counterparty-aliases", headers=headers, json={"row_id": held.id})
    assert res.status_code == 422
    res = await client.post("/api/v1/ledger/counterparty-aliases", headers=headers,
                            json={"row_id": held.id, "confirm": False})
    assert res.status_code == 422
    assert await _aliases(client, org_id) == []


async def test_a_row_that_was_not_excluded_cannot_be_aliased(client):
    headers, org_id, _ = await kullanici(client, "alias-notex@example.com")
    await _upload(client, org_id, who=FULL)
    await _upload(client, org_id, who=SHORT)
    held = await _held(client, org_id)
    res = await _confirm(client, headers, held.id)
    assert res.status_code == 409 and res.json()["details"]["reason"] == "not_excluded"


async def test_the_proposal_can_be_read_again_before_confirming(client):
    headers, _org_id, _, held = await _excluded_pair(client, "alias-proposal@example.com")
    data = (await client.get(f"/api/v1/ledger/rows/{held.id}/alias-proposal", headers=headers)).json()["data"]
    assert data["confirmation_text"] == f"Bundan sonra {SHORT} ve {FULL} aynı tedarikçi sayılacak."


# ── list, revoke ─────────────────────────────────────────────────────────────────────────────


async def test_aliases_are_listed_with_both_names_and_the_decision(client):
    headers, _org_id, _, held = await _excluded_pair(client, "alias-list@example.com")
    await _confirm(client, headers, held.id)
    (item,) = (await client.get("/api/v1/ledger/counterparty-aliases", headers=headers)).json()["data"]
    assert (item["alias_name"], item["canonical_name"], item["active"]) == (SHORT, FULL, True)
    assert item["decision_id"] and item["created_by"]


async def test_revoking_stops_future_ingests_lists_the_rows_it_touched_and_rewrites_nothing(client):
    headers, org_id, _, held = await _excluded_pair(client, "alias-revoke@example.com")
    await _confirm(client, headers, held.id)
    (alias,) = await _aliases(client, org_id)

    # While the alias is active the short name's other invoice is read as the full name's supplier.
    await _upload(client, org_id, number="A-2", who=SHORT, cents=50_000)
    touched = next(r for r in await _rows(client, org_id) if r.amount_cents == 50_000)
    assert key_party(touched.source_record_id)[1] == alias.canonical_token

    res = await client.delete(f"/api/v1/ledger/counterparty-aliases/{alias.id}", headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert [r["id"] for r in data["rows_ingested_under"]] == [touched.id]
    assert data["rows_ingested_under"][0]["counterparty"] == SHORT
    assert "değiştirilmedi" in data["note"]
    after = next(r for r in await _rows(client, org_id) if r.id == touched.id)
    assert after.source_record_id == touched.source_record_id         # history is not rewritten

    (listed,) = (await client.get("/api/v1/ledger/counterparty-aliases", headers=headers)).json()["data"]
    assert listed["active"] is False and listed["revoked_at"]
    async with client._maker() as db:
        revoked = (await db.execute(select(Decision).where(
            Decision.org_id == org_id, Decision.kind == "counterparty_alias", Decision.outcome == "revoked")
        )).scalars().one()
    assert revoked.before["active"] is True and revoked.after["active"] is False
    assert revoked.after["rows_to_review"] == 1

    # Future ingests no longer apply it: the same invoice under the short name is asked about again.
    _, again = await _upload(client, org_id, number="A-2", who=SHORT, cents=50_000)
    assert again["already"] == 0 and again["possible_duplicate"] + again["new"] == 1
    again_revoke = await client.delete(f"/api/v1/ledger/counterparty-aliases/{alias.id}", headers=headers)
    assert again_revoke.status_code == 409


async def test_revoking_is_for_a_decider_or_the_accountant(client):
    headers, org_id, _, held = await _excluded_pair(client, "alias-revrole@example.com")
    await _confirm(client, headers, held.id)
    (alias,) = await _aliases(client, org_id)
    from app.models.user import User

    # A cfo of the same organisation: a writer, not a decider.
    _, _, cfo_id = await kullanici(client, "alias-revrole-cfo@example.com", attach_org=False, role="cfo")
    async with client._maker() as db:
        (await db.get(User, cfo_id)).org_id = org_id
        await db.commit()
    login = await client.post("/api/v1/auth/login", json={"email": "alias-revrole-cfo@example.com", "password": PAROLA})
    cfo = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    res = await client.delete(f"/api/v1/ledger/counterparty-aliases/{alias.id}", headers=cfo)
    assert res.status_code == 403
    assert (await _aliases(client, org_id))[0].revoked_at is None


async def test_an_alias_can_be_confirmed_again_after_it_was_revoked(client):
    headers, org_id, _, held = await _excluded_pair(client, "alias-reconfirm@example.com")
    await _confirm(client, headers, held.id)
    (alias,) = await _aliases(client, org_id)
    await client.delete(f"/api/v1/ledger/counterparty-aliases/{alias.id}", headers=headers)
    assert (await _confirm(client, headers, held.id)).status_code == 200
    (again,) = await _aliases(client, org_id)
    assert again.id == alias.id and again.revoked_at is None


# ── isolation between organisations ──────────────────────────────────────────────────────────


async def test_another_organisation_neither_sees_nor_revokes_an_alias(client):
    headers, org_id, _, held = await _excluded_pair(client, "alias-iso-a@example.com")
    await _confirm(client, headers, held.id)
    (alias,) = await _aliases(client, org_id)
    other, _other_org, _ = await kullanici(client, "alias-iso-b@example.com")

    assert (await client.get("/api/v1/ledger/counterparty-aliases", headers=other)).json()["data"] == []
    assert (await client.delete(f"/api/v1/ledger/counterparty-aliases/{alias.id}", headers=other)).status_code == 404
    assert (await client.get(f"/api/v1/ledger/counterparty-aliases/{alias.id}/rows", headers=other)).status_code == 404
    assert (await client.post("/api/v1/ledger/counterparty-aliases", headers=other,
                              json={"row_id": held.id, "confirm": True})).status_code == 404
    assert (await _aliases(client, org_id))[0].revoked_at is None


# ── chains and cycles ────────────────────────────────────────────────────────────────────────


def _row(org, name, direction="expense"):
    key = document_key(org, "A-1", name, direction)
    return CanonicalTransaction(
        id=str(uuid.uuid4()), org_id=org, source_type="fingerprint", source_record_id=key,
        transaction_date=datetime(2024, 3, 1, tzinfo=UTC), amount_cents=100_000, currency="TRY",
        direction=direction, category="cogs", ledger_status="active", basis="document",
    )


def test_a_canonical_token_that_is_itself_an_alias_is_followed_not_chained():
    org = "org-chain"
    x, y, z = (_row(org, n) for n in ("Alfa Gıda A.Ş.", "Beta Tekstil A.Ş.", "Gamma Metal A.Ş."))
    tx, ty, tz = (key_party(r.source_record_id)[1] for r in (x, y, z))
    # y is already an alias of z; x is now found to be y: x becomes an alias of z, not of y.
    assert _pair(x, y, {ty: tz}) == (tx, tz)


def test_an_attempted_cycle_is_refused_with_its_reason():
    org = "org-cycle"
    x, y = _row(org, "Alfa Gıda A.Ş."), _row(org, "Beta Tekstil A.Ş.")
    tx, ty = (key_party(r.source_record_id)[1] for r in (x, y))
    with pytest.raises(AliasRefused) as caught:
        _pair(x, y, {ty: tx})                        # y is already read as x; now x as y
    assert caught.value.reason == "cycle"
    with pytest.raises(AliasRefused) as caught:
        _pair(x, y, {tx: ty})                        # x is already read as y
    assert caught.value.reason == "already_same"


def test_different_numbers_or_sides_cannot_be_aliased():
    org = "org-sides"
    x, y = _row(org, "Alfa Gıda A.Ş."), _row(org, "Beta Tekstil A.Ş.", "income")
    with pytest.raises(AliasRefused) as caught:
        _pair(x, y, {})
    assert caught.value.reason == "not_same_number"
    with pytest.raises(AliasRefused) as caught:
        _pair(x, None, {})
    assert caught.value.reason == "no_match"


async def test_confirming_through_an_existing_alias_resolves_to_the_root_and_repoints_dependants(client):
    headers, org_id, _ = await kullanici(client, "alias-chain@example.com")
    n = {name: party_token(org_id, name) for name in ("Alfa Gıda A.Ş.", "Beta Tekstil A.Ş.", "Gamma Metal A.Ş.", "Delta A.Ş.")}
    alfa, beta, gamma = n["Alfa Gıda A.Ş."], n["Beta Tekstil A.Ş."], n["Gamma Metal A.Ş."]
    kept, held = _row(org_id, "Beta Tekstil A.Ş."), _row(org_id, "Gamma Metal A.Ş.")
    held.ledger_status, held.duplicate_of = "excluded", kept.id
    async with client._maker() as db:
        db.add_all([kept, held])
        # beta is already read as alfa; delta is already read as gamma.
        db.add_all([CounterpartyAlias(org_id=org_id, alias_token=beta, canonical_token=alfa),
                    CounterpartyAlias(org_id=org_id, alias_token=n["Delta A.Ş."], canonical_token=gamma)])
        await db.commit()
    res = await _confirm(client, headers, held.id)
    assert res.status_code == 200, res.text
    mapping = {a.alias_token: a.canonical_token for a in await _aliases(client, org_id)}
    assert mapping[gamma] == alfa                  # gamma is beta, and beta is alfa: gamma -> alfa
    assert mapping[n["Delta A.Ş."]] == alfa        # whoever read as gamma now reads as alfa
    assert all(v not in mapping for v in mapping.values())          # no chain anywhere


# ── erasure ──────────────────────────────────────────────────────────────────────────────────


def test_the_alias_table_is_org_scoped_and_not_retained_by_erasure():
    """`counterparty_aliases` has an `org_id`, so `derive_scope` finds it; it is not in `RETAINED`, so it is
    deleted in both erasure modes (anonymise and hard_delete). The names it keeps are erased with it."""
    from app.services import org_erasure

    assert "counterparty_aliases" in org_erasure.derive_scope()
    assert "counterparty_aliases" not in org_erasure.RETAINED
    assert "counterparty_aliases" not in org_erasure.SPECIAL_TABLES


# ── S4: money matched to a document that is excluded ─────────────────────────────────────────


async def _matched(client, org_id, held, status):
    """What older books can hold: an open item for a held row, with a bank line matched to it."""
    async with client._maker() as db:
        item = OpenItem(
            id=str(uuid.uuid4()), org_id=org_id, direction="payable", instrument="invoice",
            document_id=open_item_key(held.source_record_id), counterparty=SHORT, amount_cents=100_000,
            paid_cents=100_000 if status == "confirmed" else 0, currency="TRY", issue_date=date(2024, 3, 1),
            status="settled" if status == "confirmed" else "open", created_at=datetime.now(UTC),
        )
        match = OpenItemMatch(
            id=str(uuid.uuid4()), org_id=org_id, open_item_id=item.id, ledger_row_id=held.id,
            amount_cents=100_000, method="invoice_number", status=status, matched_on=date(2024, 3, 5),
        )
        db.add_all([item, match])
        await db.commit()
        return item.id, match.id


async def _held_with_match(client, email, status):
    headers, org_id, _ = await kullanici(client, email)
    await _upload(client, org_id, who=FULL)
    await _upload(client, org_id, who=SHORT)
    held = await _held(client, org_id)
    item_id, match_id = await _matched(client, org_id, held, status)
    return headers, org_id, held, item_id, match_id


async def test_excluding_a_document_with_confirmed_money_is_refused_and_changes_nothing(client):
    headers, org_id, held, item_id, match_id = await _held_with_match(client, "s4-confirmed@example.com", "confirmed")
    res = await client.post(f"/api/v1/ledger/rows/{held.id}/resolve", headers=headers, json={"action": "exclude"})
    assert res.status_code == 409
    detail = res.json()["details"]
    assert detail["reason"] == "matched_money" and detail["match_ids"] == [match_id]
    assert (await _held(client, org_id)).id == held.id                 # still waiting: nothing was flipped
    async with client._maker() as db:
        assert (await db.get(OpenItem, item_id)).paid_cents == 100_000
        assert (await db.get(OpenItemMatch, match_id)).status == "confirmed"


async def test_undoing_the_match_reopens_the_invoice_and_then_the_exclusion_goes_through(client):
    headers, org_id, held, item_id, match_id = await _held_with_match(client, "s4-undo@example.com", "confirmed")
    undone = await client.post(f"/api/v1/ledger/settlements/{match_id}/undo", headers=headers)
    assert undone.status_code == 200, undone.text
    async with client._maker() as db:
        item = await db.get(OpenItem, item_id)
        assert (item.paid_cents, item.status) == (0, "open")           # the bank line is its own money again
        assert (await db.get(OpenItemMatch, match_id)).status == "rejected"
        decision = (await db.execute(select(Decision).where(
            Decision.org_id == org_id, Decision.target_id == match_id))).scalars().one()
    assert (decision.kind, decision.outcome) == ("settlement_match", "undone")
    assert (await client.post(f"/api/v1/ledger/settlements/{match_id}/undo", headers=headers)).status_code == 409

    done = await _resolve(client, headers, held.id, "exclude")
    assert done["open_item"] == "removed"
    assert [i.document_id for i in await _items(client, org_id) if i.id == item_id] == []
    assert await _radar_out(client, org_id) == 100_000


async def test_excluding_a_document_with_only_a_proposed_match_rejects_the_proposal(client):
    headers, _org_id, held, item_id, match_id = await _held_with_match(client, "s4-proposed@example.com", "proposed")
    done = await _resolve(client, headers, held.id, "exclude")
    assert done["open_item"] == "removed" and done["rejected_proposals"] == [match_id]
    async with client._maker() as db:
        assert await db.get(OpenItem, item_id) is None
        assert await db.get(OpenItemMatch, match_id) is None            # no proposal left pointing at it


async def test_undo_is_scoped_to_the_organisation(client):
    _headers, _org_id, _held_row, _item_id, match_id = await _held_with_match(client, "s4-iso-a@example.com", "confirmed")
    other, _, _ = await kullanici(client, "s4-iso-b@example.com")
    assert (await client.post(f"/api/v1/ledger/settlements/{match_id}/undo", headers=other)).status_code == 404

