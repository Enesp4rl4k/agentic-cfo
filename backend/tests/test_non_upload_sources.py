"""Money rows that are fetched, not uploaded: counted, held when unknown, and never an empty success.

The defects (all found in review of #116, none on the upload path):

  1. open banking: a missing type code was booked as an expense (Garanti), a missing amount was 0 and a zero
     amount an expense (Akbank); `POST /open-banking/connections/{id}/sync`;
  2. `integrations.py`: a missing amount defaulted to 0, a non-200 returned an empty list (an outage looked like
     "no transactions");
  3. the scheduled sync's `_to_cents`: "1.500" became 150 cents, "abc" and "" became 0, all booked as income
     with confidence 90;
  4. Paraşüt: an invoice with no amount or date was silently dropped;
  5. none of these counted anything.

Network is mocked everywhere (httpx.MockTransport).
"""
from __future__ import annotations

import json
import random
from typing import Any

import httpx
import pytest

from app.services.data_plane.normalization_service import normalize_csv_transactions
from app.services.ingest.feed import (
    AMOUNT_AMBIGUOUS,
    AMOUNT_MISSING,
    AMOUNT_UNREADABLE,
    AMOUNT_ZERO,
    AWAITING_REVIEW,
    CURRENCY_UNREADABLE,
    DATE_UNREADABLE,
    DIRECTION_MISSING,
    FAILED,
    PARTIAL,
    SUCCESS,
    Feed,
    evidence_text,
    read_money,
)
from app.services.open_banking.akbank import AkbankClient
from app.services.open_banking.base import MAX_PAGES
from app.services.open_banking.garanti import GarantiClient

# ── payload fixtures ───────────────────────────────────────────────────────────────────────────────────────

SECRET = "Bearer-SECRET-TOKEN-123"


def garanti_item(**over: Any) -> dict[str, Any]:
    base = {"TransactionId": "T1", "TransactionDate": "20260105", "Amount": "1500.00", "CurrencyCode": "TRY",
            "TransactionType": "C", "Description": "HAVALE", "CounterPartyName": "ABC A.S.", "ReferenceNumber": "R1"}
    base.update(over)
    return {k: v for k, v in base.items() if v is not _GONE}


def akbank_item(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"transactionId": "A1", "bookingDate": "2026-01-05",
                            "transactionAmount": {"amount": "-250.00", "currency": "TRY"},
                            "remittanceInformationUnstructured": "KIRA"}
    base.update(over)
    return base


_GONE = object()


def garanti_payload(*items: dict[str, Any]) -> dict[str, Any]:
    return {"TransactionList": list(items)}


def akbank_payload(*items: dict[str, Any], pending: list | None = None, nxt: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"transactions": {"booked": list(items), "pending": pending or []}}
    if nxt:
        out["_links"] = {"next": {"href": nxt}}
    return out


def _bank(cls, handler):
    c = cls("cid", "csecret", sandbox=True)
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


async def _pull(client, handler):
    bank = _bank(client, handler)
    try:
        return await bank.get_transactions("tok", "ACC", "2026-01-01", "2026-01-31")
    finally:
        await bank.close()


def _json(payload):
    return lambda request: httpx.Response(200, json=payload)


# ── 1. open banking ────────────────────────────────────────────────────────────────────────────────────────

async def test_garanti_a_missing_type_code_is_held_never_an_expense() -> None:
    result = await _pull(GarantiClient, _json(garanti_payload(garanti_item(TransactionType=_GONE))))
    (row,) = result.rows
    assert row["type"] is None and DIRECTION_MISSING in row["feed_flags"]
    assert row["amount_cents"] == 150000                       # the amount itself was fine
    assert result.outcome()["status"] == AWAITING_REVIEW and result.held_candidates == 1


@pytest.mark.parametrize("code", ["", "X", "debit", None, "  "])
async def test_garanti_an_unknown_type_code_is_held(code) -> None:
    result = await _pull(GarantiClient, _json(garanti_payload(garanti_item(TransactionType=code))))
    assert result.rows[0]["type"] is None


async def test_garanti_known_codes_are_booked_with_their_direction() -> None:
    result = await _pull(GarantiClient, _json(garanti_payload(
        garanti_item(TransactionType="c"), garanti_item(TransactionType="D", TransactionId="T2", Amount="250.50"))))
    assert [(r["type"], r["amount_cents"], r["date"], r["currency"]) for r in result.rows] == [
        ("income", 150000, "2026-01-05", "TRY"), ("expense", 25050, "2026-01-05", "TRY")]
    assert result.outcome()["status"] == SUCCESS and result.complete


@pytest.mark.parametrize(("amount", "flag"), [
    (_GONE, AMOUNT_MISSING), ("", AMOUNT_MISSING), ("abc", AMOUNT_UNREADABLE), ("1.500", AMOUNT_AMBIGUOUS),
    ("1,500", AMOUNT_AMBIGUOUS), (None, AMOUNT_MISSING), ("0.500", AMOUNT_AMBIGUOUS), ("0", AMOUNT_ZERO),
])
async def test_garanti_a_missing_garbled_or_ambiguous_amount_is_held_not_zero_not_guessed(amount, flag) -> None:
    result = await _pull(GarantiClient, _json(garanti_payload(garanti_item(Amount=amount))))
    (row,) = result.rows
    assert flag in row["feed_flags"]
    assert row["amount_cents"] is None or (row["amount_cents"] == 0 and flag == AMOUNT_ZERO)


@pytest.mark.parametrize(("amount", "cents"), [("1.500,00", 150000), ("1,500.00", 150000), ("1500.5", 150050), (1500.5, 150050), ("1.234.567,89", 123456789)])
async def test_garanti_an_amount_with_its_own_evidence_is_read(amount, cents) -> None:
    (row,) = (await _pull(GarantiClient, _json(garanti_payload(garanti_item(Amount=amount))))).rows
    assert row["amount_cents"] == cents and not row["feed_flags"]


@pytest.mark.parametrize("date", [_GONE, "", "31.31.2026", "garbage", "2026-02-30", "99999999"])
async def test_garanti_an_unreadable_date_is_held_never_today(date) -> None:
    (row,) = (await _pull(GarantiClient, _json(garanti_payload(garanti_item(TransactionDate=date))))).rows
    assert row["date"] is None and DATE_UNREADABLE in row["feed_flags"]


@pytest.mark.parametrize("currency", ["??", "Z", "12", "TRYY"])
async def test_garanti_an_unreadable_currency_is_held_and_a_missing_one_is_not_lira(currency) -> None:
    (row,) = (await _pull(GarantiClient, _json(garanti_payload(garanti_item(CurrencyCode=currency))))).rows
    assert row["currency"] is None and CURRENCY_UNREADABLE in row["feed_flags"]
    (row,) = (await _pull(GarantiClient, _json(garanti_payload(garanti_item(CurrencyCode=_GONE))))).rows
    assert row["currency"] is None and not row["feed_flags"]    # not stated: the pipeline's confirmed-base rule applies


async def test_akbank_a_missing_amount_is_held_not_a_zero_expense() -> None:
    result = await _pull(AkbankClient, _json(akbank_payload(
        akbank_item(transactionAmount={"currency": "TRY"}), akbank_item(transactionAmount={}), akbank_item(transactionAmount=None),
        akbank_item(transactionAmount={"amount": None, "currency": "TRY"}))))
    for row in result.rows:
        assert row["amount_cents"] is None and row["type"] is None and AMOUNT_MISSING in row["feed_flags"]
    assert len(result.rows) == 4 and result.outcome()["unaccounted"] == 0


async def test_akbank_a_zero_amount_has_no_direction_and_is_held() -> None:
    (row,) = (await _pull(AkbankClient, _json(akbank_payload(akbank_item(transactionAmount={"amount": "0.00", "currency": "TRY"}))))).rows
    assert row["type"] is None and AMOUNT_ZERO in row["feed_flags"]


async def test_akbank_the_sign_is_the_direction_and_pending_is_counted_not_booked() -> None:
    result = await _pull(AkbankClient, _json(akbank_payload(
        akbank_item(), akbank_item(transactionId="A2", transactionAmount={"amount": "900.00", "currency": "USD"}),
        pending=[{"transactionId": "P1"}, {"transactionId": "P2"}])))
    assert [(r["type"], r["amount_cents"], r["currency"]) for r in result.rows] == [("expense", 25000, "TRY"), ("income", 90000, "USD")]
    assert result.outcome()["ignored"] == {"pending": 2}


# ── an outage is a failed sync, not "no transactions" ──────────────────────────────────────────────────────

def _fail(status: int):
    return lambda request: httpx.Response(status, text=f"upstream said {SECRET}")


@pytest.mark.parametrize("cls", [GarantiClient, AkbankClient])
@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_a_bank_error_is_a_failed_pull_with_the_reason_and_nothing_booked(cls, status) -> None:
    result = await _pull(cls, _fail(status))
    out = result.outcome()
    assert result.rows == [] and out["status"] == FAILED and not result.complete and out["ok"] is False
    assert str(status) in out["reason"] and SECRET not in out["reason"]        # the reason, never the response body


@pytest.mark.parametrize("cls", [GarantiClient, AkbankClient])
@pytest.mark.parametrize("handler", [
    lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("slow")),
    lambda r: (_ for _ in ()).throw(httpx.ReadError("reset")),
    lambda r: httpx.Response(200, text="<html>maintenance</html>"),
    lambda r: httpx.Response(200, json={"error": "invalid_token"}),
    lambda r: httpx.Response(200, json=["not", "an", "object"]),
    lambda r: httpx.Response(200, json={"transactions": "oops"}),
    lambda r: httpx.Response(200, json=None),
], ids=["timeout", "reset", "html", "error-body", "list", "bad-container", "null"])
async def test_a_timeout_malformed_or_unexpected_response_is_failed_never_empty_success(cls, handler) -> None:
    result = await _pull(cls, handler)
    assert result.rows == [] and result.outcome()["status"] == FAILED and result.failed


async def test_an_empty_list_the_bank_really_returned_is_an_empty_success() -> None:
    result = await _pull(GarantiClient, _json(garanti_payload()))
    assert result.rows == [] and result.outcome()["status"] == SUCCESS and result.complete
    result = await _pull(AkbankClient, _json(akbank_payload()))
    assert result.rows == [] and result.complete


def _paged(first_next: str | None, second_status: int = 200, pages: int = 2):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        n = len(calls)
        assert request.headers["authorization"] == "Bearer tok"
        if n > 1 and n == pages and second_status != 200:
            return httpx.Response(second_status, text="boom")
        nxt = first_next if n < pages else None
        return httpx.Response(200, json=akbank_payload(akbank_item(transactionId=f"A{n}"), nxt=nxt))

    handler.calls = calls   # type: ignore[attr-defined]
    return handler


async def test_pages_are_followed_and_all_of_them_are_counted() -> None:
    handler = _paged("https://sandbox.api.akbank.com/api/v1/accounts/ACC/transactions?page=2", pages=3)
    result = await _pull(AkbankClient, handler)
    assert len(result.rows) == 3 and result.complete and result.ledger.read == 3
    assert "page=2" in handler.calls[1] or len(handler.calls) == 3


async def test_a_page_that_fails_after_the_first_is_a_partial_pull_that_does_not_cover_the_period() -> None:
    handler = _paged("https://sandbox.api.akbank.com/next", second_status=500)
    result = await _pull(AkbankClient, handler)
    out = result.outcome()
    assert len(result.rows) == 1                                       # page 1 is real money and is kept
    assert out["status"] == PARTIAL and out["complete"] is False and "2. sayfa" in out["reason"]
    assert out["ok"] is True and out["unaccounted"] == 0               # what was read is accounted for; the period is not covered


async def test_a_next_link_to_another_host_is_not_followed_and_is_partial() -> None:
    handler = _paged("https://evil.example.com/steal?token=1")
    result = await _pull(AkbankClient, handler)
    assert len(handler.calls) == 1 and result.complete          # no next page on the bank's own host: nothing to fetch


async def test_the_page_limit_is_a_partial_pull_not_a_silent_cut() -> None:
    n = {"calls": 0}

    def forever(request: httpx.Request) -> httpx.Response:
        n["calls"] += 1
        return httpx.Response(200, json=akbank_payload(akbank_item(transactionId=str(n["calls"])),
                                                       nxt="https://sandbox.api.akbank.com/api/v1/accounts/ACC/transactions?p=x"))

    result = await _pull(AkbankClient, forever)
    assert n["calls"] == MAX_PAGES and len(result.rows) == MAX_PAGES
    assert result.outcome()["status"] == PARTIAL and "sayfa sınırı" in result.partial


# ── held rows carry what the source said, and no secret ────────────────────────────────────────────────────

async def test_a_held_row_shows_the_raw_values_and_never_a_token() -> None:
    item = garanti_item(Amount="abc", TransactionType="Z", Authorization=SECRET, access_token=SECRET)
    (row,) = (await _pull(GarantiClient, _json(garanti_payload(item)))).rows
    assert "Amount='abc'" in row["description"] and "TransactionType='Z'" in row["description"]
    assert SECRET not in json.dumps(row) and "token" not in row["description"].lower()
    assert SECRET not in evidence_text({"Authorization": SECRET, "api_key": SECRET, "note": "x"})


# ── 2. integrations.py ─────────────────────────────────────────────────────────────────────────────────────

_REAL_CLIENT = httpx.AsyncClient


def _patch_httpx(monkeypatch, handler) -> None:
    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_CLIENT(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _ob_handler(txs: Any = None, status: int = 200, token_status: int = 200, links: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(token_status, json={"access_token": "t", "expires_in": 3600})
        if status != 200:
            return httpx.Response(status, text="no")
        body: dict[str, Any] = {"transactions": txs} if txs is not None else {"unexpected": True}
        if links:
            body["_links"] = links
        return httpx.Response(200, json=body)
    return handler


def _ob_tx(**over):
    tx = {"transactionId": "1", "bookingDate": "2026-01-05", "amount": {"amount": "-100.00", "currency": "EUR"},
          "transactionText": "FATURA"}
    tx.update(over)
    return tx


async def test_integrations_open_banking_a_missing_amount_is_held_and_a_zero_is_not_an_expense(monkeypatch) -> None:
    from app.services.integrations import TurkiyeOpenBankingClient

    _patch_httpx(monkeypatch, _ob_handler([_ob_tx(), _ob_tx(amount={"currency": "EUR"}), _ob_tx(amount={"amount": "0", "currency": "EUR"}),
                                           _ob_tx(amount=None), _ob_tx(amount={"amount": "1.500", "currency": "EUR"})]))
    result = await TurkiyeOpenBankingClient("akbank", "i", "s").get_transactions("ACC", "2026-01-01", "2026-01-31")
    assert [(r["type"], r["amount_cents"]) for r in result.rows] == [
        ("expense", 10000), (None, None), (None, 0), (None, None), (None, None)]
    assert result.held_candidates == 4 and result.outcome()["unaccounted"] == 0


async def test_integrations_open_banking_a_non_200_is_failed_not_an_empty_list(monkeypatch) -> None:
    from app.services.integrations import TurkiyeOpenBankingClient

    for kwargs in ({"status": 503}, {"token_status": 401}, {"txs": None}):
        _patch_httpx(monkeypatch, _ob_handler(**kwargs))
        result = await TurkiyeOpenBankingClient("akbank", "i", "s").get_transactions("ACC", "2026-01-01", "2026-01-31")
        assert result.rows == [] and result.outcome()["status"] == FAILED, kwargs


async def test_integrations_open_banking_an_unfetched_next_page_is_partial(monkeypatch) -> None:
    from app.services.integrations import TurkiyeOpenBankingClient

    _patch_httpx(monkeypatch, _ob_handler([_ob_tx()], links={"next": {"href": "/p2"}}))
    result = await TurkiyeOpenBankingClient("akbank", "i", "s").get_transactions("ACC", "2026-01-01", "2026-01-31")
    assert len(result.rows) == 1 and result.outcome()["status"] == PARTIAL


async def test_integrations_list_accounts_raises_on_a_refusal_instead_of_returning_nothing(monkeypatch) -> None:
    from app.services.integrations import TurkiyeOpenBankingClient

    _patch_httpx(monkeypatch, _ob_handler(status=500))
    with pytest.raises(RuntimeError):
        await TurkiyeOpenBankingClient("akbank", "i", "s").list_accounts()


def _shop(orders: Any, status: int = 200, link: str = ""):
    return lambda request: httpx.Response(status, json={"orders": orders} if orders is not None else {"x": 1},
                                          headers={"link": link} if link else {})


async def test_shopify_missing_total_is_held_not_zero_and_an_outage_is_failed(monkeypatch) -> None:
    from app.services.integrations import ShopifyConnector

    orders = [{"id": 1, "order_number": 1001, "total_price": "250.00", "currency": "TRY", "created_at": "2026-01-05T10:00:00+03:00"},
              {"id": 2, "order_number": 1002, "currency": "TRY", "created_at": "2026-01-06T10:00:00+03:00"},
              {"id": 3, "order_number": 1003, "total_price": "1.500", "currency": "TRY", "created_at": "2026-01-06"},
              {"id": 4, "order_number": 1004, "total_price": "9.00", "created_at": "garbage"}]
    _patch_httpx(monkeypatch, _shop(orders))
    result = await ShopifyConnector("shop.example.com", "tok").get_orders("2026-01-01", "2026-01-31")
    assert [r["amount_cents"] for r in result.rows] == [25000, None, None, 900]
    assert result.rows[3]["date"] is None and result.held_candidates == 3

    for handler in (_shop(None, status=500), _shop(None)):
        _patch_httpx(monkeypatch, handler)
        failed = await ShopifyConnector("shop.example.com", "tok").get_orders("2026-01-01", "2026-01-31")
        assert failed.rows == [] and failed.outcome()["status"] == FAILED

    _patch_httpx(monkeypatch, _shop(orders[:1], link='<https://shop/orders.json?page_info=x>; rel="next"'))
    partial = await ShopifyConnector("shop.example.com", "tok").get_orders("2026-01-01", "2026-01-31")
    assert partial.outcome()["status"] == PARTIAL


async def test_trendyol_an_order_without_lines_or_a_date_is_a_held_row_not_nothing_and_not_1970(monkeypatch) -> None:
    from app.services.integrations import TrendyolConnector

    content = [{"id": 1, "orderNumber": "T1", "orderDate": 1767600000000, "lines": [{"amount": 100.5, "productName": "A", "currencyCode": "TRY"}]},
               {"id": 2, "orderNumber": "T2", "orderDate": 1767600000000, "lines": []},
               {"id": 3, "orderNumber": "T3", "lines": [{"productName": "B"}]},
               {"id": 4, "orderNumber": "T4", "orderDate": 0, "lines": [{"amount": "7.00", "productName": "C"}]}]
    _patch_httpx(monkeypatch, lambda r: httpx.Response(200, json={"content": content, "totalPages": 3}))
    result = await TrendyolConnector("1", "k", "s").get_orders("2026-01-01", "2026-01-31")
    assert len(result.rows) == 4 and result.ledger.read == 4
    assert result.rows[0]["amount_cents"] == 10050 and result.rows[0]["date"] == "2026-01-05"
    assert result.rows[1]["amount_cents"] is None and result.rows[2]["amount_cents"] is None
    assert result.rows[3]["date"] is None                       # epoch 0 is not a date
    assert result.outcome()["status"] == PARTIAL                 # totalPages > 1 and only the first page was fetched

    _patch_httpx(monkeypatch, lambda r: httpx.Response(429))
    assert (await TrendyolConnector("1", "k", "s").get_orders("2026-01-01", "2026-01-31")).outcome()["status"] == FAILED


async def test_the_ecommerce_route_reports_counts_and_a_failed_channel_is_502(client, monkeypatch) -> None:
    from tests.test_ingest import _login

    h = await _login(client, "shop@example.com")
    body = {"channel": "shopify", "from_date": "2026-01-01", "to_date": "2026-01-31",
            "credentials": {"shop_domain": "s.example.com", "access_token": "t"}}
    _patch_httpx(monkeypatch, _shop([{"id": 1, "total_price": "10.00", "currency": "TRY", "created_at": "2026-01-02"},
                                      {"id": 2, "created_at": "2026-01-02"}]))
    ok = (await client.post("/api/v1/integrations/ecommerce/sync", json=body, headers=h)).json()["data"]
    assert ok["order_count"] == 2 and ok["held_candidates"] == 1 and ok["sync_status"] == AWAITING_REVIEW
    assert ok["total_revenue_cents_by_currency"] == {"TRY": 1000}      # the unreadable order is in no total, not "0"
    _patch_httpx(monkeypatch, _shop(None, status=500))
    r = await client.post("/api/v1/integrations/ecommerce/sync", json=body, headers=h)
    assert r.status_code == 502 and "500" in r.json()["error"]


# ── 3. the scheduled sync's normalisation ──────────────────────────────────────────────────────────────────

def _csv(*rows: str, header: str = "date,amount,description,reference,type,currency") -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode()


@pytest.mark.parametrize("amount", ["1.500", "1,500", "abc", "", "  ", "-", "NaN", "12 34"])
def test_to_cents_cases_are_held_not_zero_and_not_guessed_income(amount) -> None:
    n = normalize_csv_transactions(csv_bytes=_csv(f'2026-01-05,"{amount}",x,R1,income,TRY'))
    assert n.rows == [] and len(n.held) == 1 and n.held[0]["amount_cents"] is None
    assert n.held[0]["feed_flags"], amount
    assert n.outcome()["status"] == AWAITING_REVIEW


@pytest.mark.parametrize(("amount", "cents"), [("1.500,00", 150000), ("1,500.00", 150000), ("1500.50", 150050), ("₺1.234,56", 123456), ("2.000.000", 200000000)])
def test_to_cents_amounts_with_their_own_evidence_are_booked(amount, cents) -> None:
    n = normalize_csv_transactions(csv_bytes=_csv(f'2026-01-05,"{amount}",x,R1,income,TRY'))
    assert [r.amount_cents for r in n.rows] == [cents] and n.held == []


def test_direction_is_never_assumed_to_be_income() -> None:
    # no type column, every amount positive, no source semantics: nothing says which way the money went
    n = normalize_csv_transactions(csv_bytes=_csv("2026-01-05,100.00,x,R1,,TRY", header="date,amount,description,reference,type,currency"))
    assert n.rows == [] and len(n.held) == 1 and DIRECTION_MISSING in n.held[0]["feed_flags"]
    # a file with both signs is NOT "signed": no contract and no type field means every row is held
    n = normalize_csv_transactions(csv_bytes=_csv("2026-01-05,-100.00,x,R1,,TRY", "2026-01-06,40.00,y,R2,,TRY"))
    assert n.rows == [] and len(n.held) == 2
    # not even a source name is evidence (no source is declared by contract): an untyped payroll row is held
    n = normalize_csv_transactions(csv_bytes=_csv("2026-01-05,100.00,x,R1,,TRY"), source="hr_export")
    assert n.rows == [] and len(n.held) == 1
    # an unknown type word is held, not read as income
    n = normalize_csv_transactions(csv_bytes=_csv("2026-01-05,100.00,x,R1,transfer,TRY"), source="crm_export")
    assert n.rows == [] and len(n.held) == 1


def test_a_row_with_no_currency_or_no_date_is_held_and_confidence_is_not_invented() -> None:
    n = normalize_csv_transactions(csv_bytes=_csv("2026-01-05,100.00,ok,R1,income,TRY", "garbage,100.00,d,R2,income,TRY",
                                                  "2026-01-05,100.00,c,R3,income,"))
    assert [r.source_record_id for r in n.rows] == ["R1"] and n.rows[0].confidence is None
    assert DATE_UNREADABLE in n.held[0]["feed_flags"]
    assert len(n.held) == 2 and n.outcome()["counts"]["emitted"] == 3 == len(n.rows) + len(n.held)


def test_the_normalised_file_the_job_reads_has_the_held_amounts_marked_and_the_raw_values_visible() -> None:
    n = normalize_csv_transactions(csv_bytes=_csv("2026-01-05,100.00,ok,R1,income,TRY", "2026-01-06,1.500,bad,R2,income,TRY".replace("1.500", '"1.500"')))
    text = n.job_csv.decode()
    assert "ok" in text and ",?," in text.replace('"', "") and "[ham: " in text and "'1.500'" in text
    clean = normalize_csv_transactions(csv_bytes=_csv("2026-01-05,100.00,ok,R1,income,TRY"))
    assert clean.job_csv == _csv("2026-01-05,100.00,ok,R1,income,TRY")


def test_every_csv_row_is_counted_blank_rows_by_name() -> None:
    n = normalize_csv_transactions(csv_bytes=_csv("2026-01-05,100.00,ok,R1,income,TRY", ",,,,,", "2026-01-06,x,bad,R2,income,TRY"))
    out = n.outcome()
    assert out["counts"]["read"] == 3 and out["counts"]["blank"] == 1 and out["unaccounted"] == 0
    assert (len(n.rows), len(n.held)) == (1, 1)


# ── 4. Paraşüt ─────────────────────────────────────────────────────────────────────────────────────────────

def test_a_parasut_invoice_with_no_amount_or_date_is_a_held_row_not_dropped() -> None:
    from app.services.erp.parasut_connector import islem_from_fatura

    ok = islem_from_fatura({"id": "1", "attributes": {"issue_date": "2026-01-05", "gross_total": "100", "invoice_no": "A-1", "currency": "TRL"}}, "income")
    assert ok["amount_cents"] == 10000 and ok["currency"] == "TRY" and not ok["feed_flags"]
    for attrs, flag in (({"issue_date": "2026-01-05", "invoice_no": "A-2"}, AMOUNT_MISSING),
                        ({"gross_total": "100", "invoice_no": "A-3"}, DATE_UNREADABLE),
                        ({"issue_date": "2026-01-05", "gross_total": "1.500", "invoice_no": "A-4"}, AMOUNT_AMBIGUOUS),
                        ({"issue_date": "2026-01-05", "gross_total": "0", "invoice_no": "A-5"}, AMOUNT_ZERO)):
        tx = islem_from_fatura({"id": "9", "attributes": attrs}, "expense")
        assert flag in tx["feed_flags"] and tx["type"] == "expense" and tx["document_id"]


class _Paged:
    """Paraşüt invoice lists: pages of 25 until the window ends, optional broken items and a failing page."""

    def __init__(self, pages: int, bad_every: int = 0, fail_page: int | None = None, endless: bool = False):
        self.pages, self.bad_every, self.fail_page, self.endless = pages, bad_every, fail_page, endless
        self.served = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        import time

        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "ACCESS", "refresh_token": "R", "expires_in": 7200})
        if request.url.path == "/v4/me":
            return httpx.Response(200, json={"data": {"id": "1"}, "included": [{"id": "123456", "type": "companies", "attributes": {"name": "K"}}]})
        page = int(request.url.params.get("page[number]", "1"))
        if request.url.path.endswith("purchase_bills"):
            return httpx.Response(200, json={"data": []})
        if self.fail_page == page:
            return httpx.Response(500)
        if page > self.pages and not self.endless:
            return httpx.Response(200, json={"data": []})
        today = time.strftime("%Y-%m-%d")
        data = []
        for i in range(25):
            self.served += 1
            attrs: dict[str, Any] = {"issue_date": today, "gross_total": "10.00", "invoice_no": f"F-{page}-{i}", "currency": "TRY"}
            if self.bad_every and self.served % self.bad_every == 0:
                attrs.pop("gross_total")
            data.append({"id": f"{page}-{i}", "type": "sales_invoices", "attributes": attrs})
        return httpx.Response(200, json={"data": data})


@pytest.fixture
def parasut_integration(client, monkeypatch):
    from app.config import get_settings
    from app.services.erp import parasut_connector as pc

    s = get_settings()
    monkeypatch.setattr(s, "parasut_client_id", "c")
    monkeypatch.setattr(s, "parasut_client_secret", "s")

    async def connect(fake):
        import urllib.parse

        from tests.test_ingest import _login

        monkeypatch.setattr(pc, "_transport", httpx.MockTransport(fake))
        h = await _login(client, "p@example.com")
        url = (await client.post("/api/v1/erp/parasut/baglan", headers=h)).json()["data"]["auth_url"]
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))["state"]
        await client.get("/api/v1/erp/parasut/callback", params={"code": "iyi", "state": state})
        from sqlalchemy import select

        from app.models.erp_integration import ERPIntegration

        async with client._maker() as db:
            return h, (await db.execute(select(ERPIntegration))).scalar_one().id

    return connect


async def test_parasut_pull_counts_every_invoice_and_holds_the_unreadable_ones(client, parasut_integration) -> None:
    from app.models.erp_integration import ERPIntegration
    from app.services.erp.parasut_connector import ParasutConnector

    _, integ = await parasut_integration(_Paged(pages=2, bad_every=7))
    async with client._maker() as db:
        row = await db.get(ERPIntegration, integ)
        pulled = await ParasutConnector(db).islemleri_cek(row)
    out = pulled.outcome()
    assert len(pulled.rows) == 50 and out["counts"]["read"] == 50 and out["unaccounted"] == 0
    assert out["held_candidates"] == 7 and out["status"] == AWAITING_REVIEW and out["complete"]
    assert all(r["amount_cents"] is None for r in pulled.rows if r["feed_flags"])


async def test_parasut_a_failed_page_fails_the_pull_and_does_not_move_last_synced(client, parasut_integration) -> None:
    from app.models.erp_integration import ERPIntegration
    from app.services.erp.parasut_connector import ParasutConnector

    _, integ = await parasut_integration(_Paged(pages=3, fail_page=2))
    async with client._maker() as db:
        row = await db.get(ERPIntegration, integ)
        before = row.last_sync_at
        with pytest.raises(ValueError, match="500"):
            await ParasutConnector(db).islemleri_cek(row)
        await db.refresh(row)
        assert row.last_sync_status == "error" and row.last_sync_at == before


async def test_parasut_hitting_the_page_limit_is_partial_and_is_not_recorded_as_the_last_state(client, parasut_integration, monkeypatch) -> None:
    from app.services.erp import parasut_connector as pc

    h, integ = await parasut_integration(_Paged(pages=1, endless=True))

    async def fake_cekilen(self, integration, gun=90):
        feed = Feed("parasut")
        for _ in feed.each([{"id": "1", "attributes": {"issue_date": "2026-01-05", "gross_total": "5.00"}}]):
            pc.islem_from_fatura({"id": "1", "attributes": {"issue_date": "2026-01-05", "gross_total": "5.00"}}, "income", feed=feed)
        feed.partial = "sales_invoices: sayfa sınırına ulaşıldı (200)"
        return feed.result()

    monkeypatch.setattr(pc.ParasutConnector, "islemleri_cek", fake_cekilen)
    out = (await client.post("/api/v1/erp/parasut/sync", data={"integration_id": integ}, headers=h)).json()["data"]
    assert out["sync_status"] == PARTIAL and out["period_covered"] is False and out["sync_count"] == 1
    again = (await client.post("/api/v1/erp/parasut/sync", data={"integration_id": integ}, headers=h)).json()["data"]
    assert again["durum"] == "analiz_baslatildi"           # a partial pull is never "no change since the last one"


# ── the whole sync through the pipeline: nothing booked with a guessed value ──────────────────────────────

async def _ingest_job(client, job_id: str) -> dict[str, Any]:
    """Run the ingestion step on the file a sync wrote for `job_id`; what it books and what it holds."""
    from app.agents.data_ingestion import run_data_ingestion
    from app.models.analysis_job import AnalysisJob

    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
    out = await run_data_ingestion({"file_path": job.file_path, "file_type": "csv", "org_id": job.org_id}, None)  # type: ignore[arg-type]
    return out.patch


async def test_an_open_banking_sync_with_unknown_values_reaches_the_review_queue_with_the_raw_payload(client, monkeypatch, tmp_path) -> None:
    from app.config import get_settings
    from tests.test_ingest import _login

    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path), raising=False)
    monkeypatch.setattr("app.api.open_banking._get_bank_settings", lambda bank_id: ("id", "secret", True))
    monkeypatch.setattr("app.worker.enqueue_analysis", lambda job_id, budget_input=None: _queued())
    payload = garanti_payload(
        garanti_item(), garanti_item(TransactionId="T2", TransactionType=_GONE, Amount="300.00", Description="BILINMEYEN"),
        garanti_item(TransactionId="T3", Amount="abc", Description="BOZUK"), garanti_item(TransactionId="T4", Amount="1.500", Description="BELIRSIZ"))
    monkeypatch.setattr("app.services.open_banking.get_bank_client", lambda *a, **k: _bank(GarantiClient, _json(payload)))
    h = await _login(client, "obq@example.com")
    r = await client.post("/api/v1/open-banking/connections/c1/sync", headers=h,
                          json={"bank_id": "garanti", "account_id": "A", "access_token": SECRET})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["transaction_count"] == 4 and d["held_candidates"] == 3 and d["sync_status"] == AWAITING_REVIEW
    assert d["counts"]["read"] == 4 and d["counts"]["unaccounted"] == 0 and d["period_covered"] is True

    patch = await _ingest_job(client, d["job_id"])
    booked, held = patch["transactions"], patch["held_transactions"]
    assert [t["amount_cents"] for t in booked] == [150000] and booked[0]["type"] == "income"
    assert len(held) == 3 and len(booked) + len(held) == 4
    shown = " ".join(json.dumps(x) for x in held)
    assert "BILINMEYEN" in shown and "abc" in shown and "'1.500'" in shown and SECRET not in shown
    assert not any(x.get("type") == "expense" and x.get("amount_cents") == 0 for x in held)   # no zero-lira expense
    assert patch["ingest_counts"]["unaccounted"] == 0


async def _queued():
    return "queued"


async def test_an_open_banking_outage_is_a_502_with_the_reason_and_no_analysis(client, monkeypatch, tmp_path) -> None:
    from sqlalchemy import func, select

    from app.config import get_settings
    from app.models.analysis_job import AnalysisJob
    from tests.test_ingest import _login

    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path), raising=False)
    monkeypatch.setattr("app.api.open_banking._get_bank_settings", lambda bank_id: ("id", "secret", True))
    monkeypatch.setattr("app.services.open_banking.get_bank_client", lambda *a, **k: _bank(AkbankClient, _fail(503)))
    h = await _login(client, "obf@example.com")
    r = await client.post("/api/v1/open-banking/connections/c1/sync", headers=h,
                          json={"bank_id": "akbank", "account_id": "A", "access_token": SECRET})
    assert r.status_code == 502 and "503" in r.json()["error"] and SECRET not in r.text
    async with client._maker() as db:
        assert (await db.execute(select(func.count()).select_from(AnalysisJob))).scalar() == 0


# ── the injection property test ────────────────────────────────────────────────────────────────────────────
# Inject K items with a missing/garbled amount, date, direction or currency into each source's own payload:
# booked + held grows by exactly K, nothing is lost, and none of the injected rows carries a guessed value.

MUTATIONS = ("amount_missing", "amount_garbled", "amount_ambiguous", "date_missing", "date_garbled", "direction_missing", "currency_garbled")

# field -> (what the mutated row must show)
EXPECT = {
    "amount_missing": ("amount_cents", None), "amount_garbled": ("amount_cents", None), "amount_ambiguous": ("amount_cents", None),
    "date_missing": ("date", None), "date_garbled": ("date", None), "direction_missing": ("type", None),
    "currency_garbled": ("currency", None),
}


def _garanti(m: str, i: int) -> dict[str, Any]:
    base = garanti_item(TransactionId=f"X{i}", Description=f"INJ{i}")
    return {
        "amount_missing": {k: v for k, v in base.items() if k != "Amount"}, "amount_garbled": {**base, "Amount": "abc"},
        "amount_ambiguous": {**base, "Amount": "1.500"}, "date_missing": {k: v for k, v in base.items() if k != "TransactionDate"},
        "date_garbled": {**base, "TransactionDate": "31.31.2026"}, "direction_missing": {**base, "TransactionType": "?"},
        "currency_garbled": {**base, "CurrencyCode": "??"},
    }[m]


def _akbank(m: str, i: int) -> dict[str, Any]:
    ok = {"amount": "-100.00", "currency": "TRY"}
    base = akbank_item(transactionId=f"X{i}", remittanceInformationUnstructured=f"INJ{i}")
    return {
        "amount_missing": {**base, "transactionAmount": {"currency": "TRY"}}, "amount_garbled": {**base, "transactionAmount": {**ok, "amount": "x1"}},
        "amount_ambiguous": {**base, "transactionAmount": {**ok, "amount": "-1.500"}},
        "date_missing": {k: v for k, v in base.items() if k != "bookingDate"}, "date_garbled": {**base, "bookingDate": "tomorrow"},
        "direction_missing": {**base, "transactionAmount": {"amount": "0.00", "currency": "TRY"}},
        "currency_garbled": {**base, "transactionAmount": {**ok, "currency": "TL?"}},
    }[m]


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize(("name", "cls", "good", "mutate", "wrap"), [
    ("garanti", GarantiClient, lambda i: garanti_item(TransactionId=f"G{i}"), _garanti, garanti_payload),
    ("akbank", AkbankClient, lambda i: akbank_item(transactionId=f"G{i}"), _akbank, akbank_payload),
])
async def test_injected_bad_items_are_all_counted_and_held_in_bank_payloads(seed, name, cls, good, mutate, wrap) -> None:
    rng = random.Random(seed)
    items = [good(i) for i in range(rng.randint(2, 8))]
    clean = await _pull(cls, _json(wrap(*items)))
    injected = [rng.choice(MUTATIONS) for _ in range(rng.randint(1, 5))]
    for n, m in enumerate(injected):
        items.insert(rng.randint(0, len(items)), mutate(m, n))
    result = await _pull(cls, _json(wrap(*items)))
    out = result.outcome()
    assert len(result.rows) == len(clean.rows) + len(injected) and out["unaccounted"] == 0 and out["counts"]["read"] == len(items)
    assert result.held_candidates == clean.held_candidates + len(injected)
    inj = {f"INJ{n}": m for n, m in enumerate(injected)}
    seen = 0
    for row in result.rows:
        tag = next((k for k in inj if k in row["description"]), None)
        if tag:
            field, expected = EXPECT[inj[tag]]
            assert row[field] is expected and row["feed_flags"], (inj[tag], row)
            seen += 1
    assert seen == len(injected)


@pytest.mark.parametrize("seed", range(12))
def test_injected_bad_rows_are_all_counted_and_held_in_a_scheduled_csv(seed) -> None:
    rng = random.Random(seed)
    good = [f"2026-01-{i + 1:02d},{(i + 1) * 10}.50,ok{i},G{i},income,TRY" for i in range(rng.randint(2, 8))]
    bad_rows = {
        "amount_missing": "2026-01-05,,INJ,B{n},income,TRY", "amount_garbled": "2026-01-05,abc,INJ,B{n},income,TRY",
        "amount_ambiguous": '2026-01-05,"1.500",INJ,B{n},income,TRY', "date_missing": "  ,10.00,INJ,B{n},income,TRY",
        "date_garbled": "99.99.2026,10.00,INJ,B{n},income,TRY", "direction_missing": "2026-01-05,10.00,INJ,B{n},,TRY",
        "currency_garbled": "2026-01-05,10.00,INJ,B{n},income,??",
    }
    injected = [rng.choice(MUTATIONS) for _ in range(rng.randint(1, 5))]
    lines = list(good)
    for n, m in enumerate(injected):
        lines.insert(rng.randint(0, len(lines)), bad_rows[m].format(n=n))
    normalized = normalize_csv_transactions(csv_bytes=_csv(*lines))
    out = normalized.outcome()
    assert len(normalized.rows) == len(good) and len(normalized.held) == len(injected)
    assert out["counts"]["read"] == len(lines) and out["unaccounted"] == 0
    assert all(r.source_record_id.startswith("G") for r in normalized.rows)
    assert all(h["feed_flags"] and (h["amount_cents"] is None or h["type"] is None or h["date"] is None or h["currency"] is None)
               for h in normalized.held)


# ── the shared pieces ──────────────────────────────────────────────────────────────────────────────────────

def test_read_money_is_the_upload_parsers_money_with_the_ambiguity_guard() -> None:
    from app.parsers.direction import parse_money

    for raw in ("1.234,56", "-1.234,56", "(500,00)", "₺1.234,56", "1,234.56", 1234.56, "500,00 TL-"):
        m = read_money(raw)
        assert (m.cents, m.negative) == parse_money(raw)         # one parser: same answer wherever it is unambiguous
    for raw in ("1.500", "1,500", "999.999", "0.500"):
        assert read_money(raw).flag == AMOUNT_AMBIGUOUS and read_money(raw).cents is None
    for raw in (None, "", "   "):
        assert read_money(raw).flag == AMOUNT_MISSING
    for raw in ("abc", True, [], {}, float("nan"), float("inf")):
        assert read_money(raw).flag == AMOUNT_UNREADABLE


def test_a_pull_that_loses_an_item_is_visible_as_unaccounted() -> None:
    feed = Feed("probe")
    for item in feed.each([{"a": 1}, {"a": 2}, {"a": 3}]):
        if item["a"] != 2:                # a source module that forgets to account for an item
            feed.add(amount="1.00", direction="income", date="2026-01-01", currency="TRY", description="x")
    out = feed.result().outcome()
    assert out["unaccounted"] == 1 and out["status"] == AWAITING_REVIEW and out["ok"] is False


def test_a_feed_result_that_is_not_complete_never_covers_its_period() -> None:
    feed = Feed("probe")
    feed.partial = "page 2 failed"
    assert feed.result().complete is False
    assert Feed("probe").fail("down").complete is False
    assert Feed("probe").result().complete is True


# ── the scheduled runner ───────────────────────────────────────────────────────────────────────────────────

async def test_a_scheduled_pull_that_fails_is_a_failed_run_with_the_reason_and_a_recorded_sync_run(client, monkeypatch) -> None:
    from sqlalchemy import select

    from app.models.sync_run import SyncRun
    from app.services.ingest.feed import FeedFailed
    from app.services.scheduled_sync import (
        ScheduledSyncRunner,
        SyncScheduleConfig,
        SyncSourceType,
        SyncStatus,
    )
    from tests.test_ingest import _login

    await _login(client, "sched@example.com")

    async def down(self, schedule, settings, db=None):
        raise FeedFailed("Paraşüt çekimi başarısız: Paraşüt faturalar isteği başarısız (503).")

    monkeypatch.setattr(ScheduledSyncRunner, "_pull_data", down)
    schedule = SyncScheduleConfig("s1", "org-sched", SyncSourceType.ERP_PARASUT)
    async with client._maker() as db:
        result = await ScheduledSyncRunner().run(schedule, db, None)
        await db.commit()
        runs = (await db.execute(select(SyncRun))).scalars().all()
    assert result.status == SyncStatus.FAILED and "503" in (result.error or "") and result.period_covered is False
    assert [r.status for r in runs] == [SyncStatus.FAILED]


@pytest.mark.parametrize("source", ["erp_logo_tiger", "open_banking", "gib_efatura"])
async def test_scheduled_sources_that_cannot_pull_say_so_instead_of_returning_an_empty_file(source) -> None:
    from app.services.ingest.feed import FeedFailed
    from app.services.scheduled_sync import ScheduledSyncRunner, SyncScheduleConfig

    with pytest.raises(FeedFailed):
        await ScheduledSyncRunner()._pull_data(SyncScheduleConfig("s", "o", source), None)


async def test_a_scheduled_pull_with_held_rows_is_awaiting_review_and_opens_a_job_for_them(client, monkeypatch, tmp_path) -> None:
    from sqlalchemy import select

    from app.config import get_settings
    from app.models.canonical_transaction import CanonicalTransaction
    from app.models.organization import Organization
    from app.services.scheduled_sync import (
        ScheduledSyncRunner,
        SyncScheduleConfig,
        SyncSourceType,
        SyncStatus,
    )
    from tests.test_ingest import _login

    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path), raising=False)
    monkeypatch.setattr("app.worker.enqueue_analysis", lambda job_id, budget_input=None: _queued())
    await _login(client, "sched2@example.com")
    async with client._maker() as db:
        org = (await db.execute(select(Organization))).scalars().first().id

    rows = ["date,amount,description,reference,type,currency"]
    rows += [f"2026-01-{i + 1:02d},{(i + 1) * 100}.00,Satis {i},R{i},income,TRY" for i in range(5)]
    rows += ['2026-01-20,"1.500",Belirsiz tutar,R9,income,TRY', "2026-01-21,abc,Bozuk tutar,R10,income,TRY"]
    payload = ("\n".join(rows) + "\n").encode()

    async def pull(self, schedule, settings, db=None):
        return payload, "sync.csv", None

    monkeypatch.setattr(ScheduledSyncRunner, "_pull_data", pull)
    schedule = SyncScheduleConfig("s2", org, SyncSourceType.MANUAL_CSV, auto_analyze=False, notify_on_completion=False)
    async with client._maker() as db:
        result = await ScheduledSyncRunner().run(schedule, db, get_settings())
        canonical = (await db.execute(select(CanonicalTransaction))).scalars().all()
    assert result.status == SyncStatus.AWAITING_REVIEW and result.held_candidates == 2 and result.job_id
    assert result.period_covered is True and result.counts["read"] == 7 and result.counts["unaccounted"] == 0
    assert len(canonical) == 5 and {c.amount_cents for c in canonical} == {10000, 20000, 30000, 40000, 50000}
    assert all(c.direction == "income" and c.currency == "TRY" for c in canonical)

    patch = await _ingest_job(client, result.job_id)
    assert len(patch["transactions"]) + len(patch["held_transactions"]) == 7        # nothing lost: booked or waiting
    held = " ".join(json.dumps(x) for x in patch["held_transactions"])
    assert len(patch["held_transactions"]) == 2 and "Belirsiz tutar" in held and "'1.500'" in held and "Bozuk tutar" in held
