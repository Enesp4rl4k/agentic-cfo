"""Stripe pull (PR #124 follow-ups): the currency's real minor unit, and credit notes reach the ledger as expense.

Recorded fixtures only: `stripe` is replaced by objects shaped like the API's JSON (no network, no key). The amounts
are integers in the currency's minor unit, converted through one ISO 4217 table; a credit note is an expense row with
the direction its own type gives; what cannot be exact or listed is held / partial, never rounded or dropped.
"""
from __future__ import annotations

import csv
import io
import sys
import types
from typing import Any

import pytest_asyncio

from app.services.data_plane.normalization_service import normalize_csv_transactions
from app.services.ingest.currencies import cents_text, minor_exponent, minor_to_cents
from tests.api_helpers import bellek_istemcisi

TS = 1_767_600_000          # 2026-01-05


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _inv(id_: str, paid: int | None, currency: str) -> Any:
    return types.SimpleNamespace(
        id=id_, number=id_, amount_paid=paid, currency=currency, created=TS,
        status_transitions=types.SimpleNamespace(paid_at=TS),
    )


def _note(id_: str, refund: int | None, currency: str, *, oob: int | None = None, credit: int | None = None,
          status: str = "issued") -> Any:
    return types.SimpleNamespace(
        id=id_, number=id_, refund_amount=refund, out_of_band_amount=oob, credit_amount=credit, currency=currency,
        created=TS, status=status,
    )


async def _pull(client, monkeypatch, invoices: list[Any], notes: list[Any] | None, *, notes_error: bool = False,
                notes_more: bool = False, has_credit_notes: bool = True):
    from sqlalchemy import select

    from app.config import get_settings
    from app.models.organization import Organization
    from app.services.connectors.billing_stripe import pull_stripe_revenue_csv
    from tests.test_ingest import _login

    seen: dict[str, Any] = {"calls": []}

    class Invoice:
        @staticmethod
        def list(**kwargs):
            seen["calls"].append(("Invoice", kwargs))
            return types.SimpleNamespace(data=invoices, has_more=False)

    class CreditNote:
        @staticmethod
        def list(**kwargs):
            seen["calls"].append(("CreditNote", kwargs))
            if notes_error:
                raise RuntimeError("boom")
            return types.SimpleNamespace(data=notes or [], has_more=notes_more)

    fake = types.SimpleNamespace(Invoice=Invoice, api_key=None, **({"CreditNote": CreditNote} if has_credit_notes else {}))
    monkeypatch.setitem(sys.modules, "stripe", fake)
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test_x", raising=False)
    await _login(client, f"stripe{len(seen)}{id(invoices)}@example.com")
    async with client._maker() as db:
        org = (await db.execute(select(Organization))).scalars().first()
        org.stripe_customer_id = "cus_1"
        await db.commit()
        data, _, partial = await pull_stripe_revenue_csv(org.id, db)
    return data, partial, seen


def _by_ref(data: bytes) -> dict[str, dict[str, str]]:
    return {r["reference"]: r for r in csv.DictReader(io.StringIO(data.decode()))}


# ── one table of minor units ─────────────────────────────────────────────────────────────────────────────────

def test_the_minor_unit_table_is_iso_4217_and_a_conversion_is_exact_or_none() -> None:
    assert [minor_exponent(c) for c in ("USD", "TRY", "EUR", "JPY", "KRW", "VND", "KWD", "BHD", "OMR", "XXX", None)] == [
        2, 2, 2, 0, 0, 0, 3, 3, 3, None, None]
    assert minor_to_cents(12_500, "USD") == 12_500 and minor_to_cents(12_500, "JPY") == 1_250_000
    assert minor_to_cents(12_340, "KWD") == 1_234 and minor_to_cents(12_345, "KWD") is None   # not a whole 1/100: never rounded
    assert minor_to_cents(5, "ZZZ") is None and minor_to_cents(5, None) is None
    assert minor_to_cents(12_500, "ISK", {"ISK": 2}) == 12_500          # a provider override is explicit
    assert [cents_text(x) for x in (1_250_000, 5, -150, 0)] == ["12500.00", "0.05", "-1.50", "0.00"]


# ── invoices ─────────────────────────────────────────────────────────────────────────────────────────────────

async def test_amounts_follow_the_currencys_real_exponent(client, monkeypatch) -> None:
    data, partial, _ = await _pull(client, monkeypatch, [
        _inv("in_usd", 12_500, "usd"), _inv("in_jpy", 12_500, "jpy"), _inv("in_kwd", 12_340, "kwd"),
        _inv("in_isk", 12_500, "isk"),
    ], [])
    assert partial is None
    n = {r.source_record_id: r.amount_cents for r in normalize_csv_transactions(csv_bytes=data, source="billing_stripe").rows}
    assert n == {"in_usd": 12_500, "in_jpy": 1_250_000, "in_kwd": 1_234, "in_isk": 12_500}


async def test_an_amount_with_no_exact_figure_is_held_with_its_raw_value_not_rounded(client, monkeypatch) -> None:
    data, _, _ = await _pull(client, monkeypatch, [_inv("in_kwd", 12_345, "kwd"), _inv("in_mga", 5_000, "mga"),
                                                    _inv("in_xxx", 100, "xxx")], [])
    norm = normalize_csv_transactions(csv_bytes=data, source="billing_stripe")
    assert norm.rows == [] and sorted(h["reference"] for h in norm.held) == ["in_kwd", "in_mga", "in_xxx"]
    assert "amount_paid=12345" in _by_ref(data)["in_kwd"]["description"]


# ── credit notes ─────────────────────────────────────────────────────────────────────────────────────────────

async def test_a_credit_note_is_an_expense_row_for_the_cash_that_went_back(client, monkeypatch) -> None:
    data, partial, seen = await _pull(client, monkeypatch, [_inv("in_1", 50_000, "try")], [
        _note("cn_1", 12_000, "try"), _note("cn_2", 3_000, "try", oob=2_000), _note("cn_jpy", 1_000, "jpy"),
    ])
    assert partial is None and seen["calls"][1] == ("CreditNote", {"customer": "cus_1", "limit": 100})
    rows = _by_ref(data)
    assert {k: rows[k]["type"] for k in rows} == {"in_1": "income", "cn_1": "expense", "cn_2": "expense", "cn_jpy": "expense"}
    norm = normalize_csv_transactions(csv_bytes=data, source="billing_stripe")
    got = {r.source_record_id: (r.direction, r.amount_cents) for r in norm.rows}
    assert got == {"in_1": ("income", 50_000), "cn_1": ("expense", 12_000), "cn_2": ("expense", 5_000),
                   "cn_jpy": ("expense", 100_000)}
    assert sum(a if d == "income" else -a for d, a in got.values()) == 50_000 - 12_000 - 5_000 - 100_000


async def test_a_credit_note_that_moved_no_cash_or_is_void_is_ignored_by_name_and_one_with_no_amount_is_held(
    client, monkeypatch,
) -> None:
    data, _, _ = await _pull(client, monkeypatch, [_inv("in_1", 50_000, "try")], [
        _note("cn_balance", 0, "try", credit=4_000), _note("cn_void", 9_000, "try", status="void"),
        _note("cn_unknown", None, "try"), _note("cn_zero", 0, "try"),
    ])
    norm = normalize_csv_transactions(csv_bytes=data, source="billing_stripe")
    assert [r.source_record_id for r in norm.rows] == ["in_1"]
    assert sorted(h["reference"] for h in norm.held) == ["cn_unknown", "cn_zero"]    # unstated / zero: a person looks
    assert "cn_balance" not in _by_ref(data) and "cn_void" not in _by_ref(data)


async def test_credit_notes_that_cannot_be_listed_make_the_pull_partial_never_complete(client, monkeypatch) -> None:
    _, failed, _ = await _pull(client, monkeypatch, [_inv("in_1", 100, "try")], None, notes_error=True)
    assert failed == "Stripe kredi notları alınamadı: RuntimeError"
    _, missing, _ = await _pull(client, monkeypatch, [_inv("in_2", 100, "try")], None, has_credit_notes=False)
    assert missing == "Stripe kredi notları bu sürümde listelenemiyor"
    _, more, _ = await _pull(client, monkeypatch, [_inv("in_3", 100, "try")], [_note("cn_1", 100, "try")], notes_more=True)
    assert more == "Stripe'ın sonraki kredi notu sayfası çekilmedi (en fazla 100 okunur)"
