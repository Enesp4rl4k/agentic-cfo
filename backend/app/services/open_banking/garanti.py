"""
Garanti BBVA Open Banking connector.

Garanti Developer Portal: https://developer.garantibbva.com.tr
Sandbox base URL: https://sanalpos.garantibbva.com.tr/openapi (sandbox)
Production base URL: https://api.garantibbva.com.tr/openapi

Garanti BBVA also follows Berlin Group NextGenPSD2 standard.
Transaction response format is slightly different from Akbank.

Garanti transaction format:
  {
    "TransactionList": [
      {
        "TransactionId": "TRX202401150001",
        "TransactionDate": "20240115",
        "ValueDate": "20240115",
        "Amount": "1500.00",
        "CurrencyCode": "TRY",
        "TransactionType": "C",   // C=Credit(income), D=Debit(expense)
        "Description": "HAVALE ALACAK",
        "CounterPartyName": "ABC A.S.",
        "ReferenceNumber": "REF001"
      }
    ]
  }
"""
from __future__ import annotations

from typing import Any

from app.services.ingest.feed import (
    INCOME,
    Feed,
    direction_from_code,
    first,
    item_is_blank,
    read_money,
    signed_amount,
)
from app.services.open_banking.base import BankOAuthConfig, OpenBankingClient, response_list


def _make_garanti_config(
    client_id: str,
    client_secret: str,
    sandbox: bool = True,
) -> BankOAuthConfig:
    base = (
        "https://sanalpos.garantibbva.com.tr/openapi"
        if sandbox
        else "https://api.garantibbva.com.tr/openapi"
    )
    return BankOAuthConfig(
        bank_id       = "garanti",
        bank_name     = "Garanti BBVA",
        client_id     = client_id,
        client_secret = client_secret,
        auth_url      = f"{base}/oauth/authorize",
        token_url     = f"{base}/oauth/token",
        accounts_url  = f"{base}/v1/accounts",
        transactions_url = f"{base}/v1/accounts/{{account_id}}/transactions",
        scopes        = ["account_info", "transaction_history"],
        sandbox       = sandbox,
    )


class GarantiClient(OpenBankingClient):
    """Garanti BBVA-specific transaction parser."""

    def __init__(self, client_id: str, client_secret: str, sandbox: bool = True) -> None:
        super().__init__(_make_garanti_config(client_id, client_secret, sandbox))

    def _parse_accounts(self, raw: Any) -> list[dict[str, Any]]:
        account_list = raw.get("AccountList") or raw.get("accounts") or []
        return [
            {
                "account_id":   acc.get("AccountNumber") or acc.get("accountId", ""),
                "iban":         acc.get("IBAN") or acc.get("iban", ""),
                # A currency or balance the bank did not state is None, not lira and not zero.
                "currency":     first(acc, "CurrencyCode", "currency"),
                "account_type": acc.get("AccountType", "CURRENT"),
                "name":         acc.get("AccountName", "Garanti BBVA Hesabı"),
                "balance":      signed_amount(first(acc, "Balance", "balance")),
            }
            for acc in account_list
        ]

    def _parse_transactions(self, raw: Any, feed: Feed) -> None:
        """
        Add one row to `feed` per Garanti BBVA transaction.

          TransactionType: "C" = Credit (income), "D" = Debit (expense); anything else, or nothing, is an
                           unknown direction and the row is held: it is never an expense.
          TransactionDate: "YYYYMMDD" (or ISO); a date that cannot be read holds the row.
          Amount:          read by the one money parser; missing, unreadable or ambiguous ("1.500") holds the row.
        """
        for tx in feed.each(response_list(raw, "TransactionList", "transactions", "data")):
            if item_is_blank(tx):
                feed.blank()
                continue
            raw_amount = first(tx, "Amount", "amount")
            code = first(tx, "TransactionType")
            money = read_money(raw_amount)
            direction = direction_from_code(code, ("C",), ("D",))
            if money.negative and direction == INCOME:
                direction = None       # a negative credit contradicts itself: a person decides
            date = first(tx, "TransactionDate", "BookingDate")
            if isinstance(date, str) and len(date) == 8 and date.isdigit():
                date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            vendor = first(tx, "CounterPartyName", "DebtorName")
            description = first(tx, "Description", "remittanceInformationUnstructured") or "Garanti BBVA işlemi"
            feed.add(
                amount=raw_amount, direction=direction, date=date, currency=first(tx, "CurrencyCode", "currency"),
                description=str(description)[:200], reference=first(tx, "TransactionId", "ReferenceNumber"),
                evidence={"Amount": raw_amount, "TransactionType": code, "TransactionDate": first(tx, "TransactionDate", "BookingDate"),
                          "CurrencyCode": first(tx, "CurrencyCode", "currency"), "TransactionId": first(tx, "TransactionId")},
                vendor=str(vendor)[:100] if vendor else None, raw_source="garanti_open_banking",
            )

