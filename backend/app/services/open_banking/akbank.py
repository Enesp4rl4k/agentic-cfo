"""
Akbank Open Banking connector.

Akbank Developer Portal: https://developer.akbank.com
Sandbox base URL: https://sandbox.api.akbank.com
Production base URL: https://openapi.akbank.com

Akbank'ın Berlin Group NextGenPSD2 standardına uygun API'si kullanır.
Transaction response format:
  {
    "transactions": {
      "booked": [
        {
          "transactionId": "...",
          "bookingDate": "2024-01-15",
          "valueDate": "2024-01-15",
          "transactionAmount": {"amount": "1500.00", "currency": "TRY"},
          "debtorName": "Tedarikçi A.Ş.",
          "creditorName": "Müşteri B Ltd",
          "remittanceInformationUnstructured": "Fatura No: INV-2024-001",
          "bankTransactionCode": "PMNT/RCDT/ESCT"
        }
      ]
    }
  }
"""
from __future__ import annotations

from typing import Any

from app.services.ingest.feed import (
    Feed,
    FeedFailed,
    direction_from_sign,
    first,
    item_is_blank,
    read_money,
    signed_amount,
)
from app.services.open_banking.base import BankOAuthConfig, OpenBankingClient


def _make_akbank_config(
    client_id: str,
    client_secret: str,
    sandbox: bool = True,
) -> BankOAuthConfig:
    base = "https://sandbox.api.akbank.com" if sandbox else "https://openapi.akbank.com"
    return BankOAuthConfig(
        bank_id       = "akbank",
        bank_name     = "Akbank",
        client_id     = client_id,
        client_secret = client_secret,
        auth_url      = f"{base}/api/v1/oauth/authorize",
        token_url     = f"{base}/api/v1/oauth/token",
        accounts_url  = f"{base}/api/v1/accounts",
        transactions_url = f"{base}/api/v1/accounts/{{account_id}}/transactions",
        scopes        = ["accounts", "transactions"],
        sandbox       = sandbox,
    )


class AkbankClient(OpenBankingClient):
    """Akbank-specific transaction parser."""

    def __init__(self, client_id: str, client_secret: str, sandbox: bool = True) -> None:
        super().__init__(_make_akbank_config(client_id, client_secret, sandbox))

    def _parse_accounts(self, raw: Any) -> list[dict[str, Any]]:
        accounts_raw = raw.get("accounts", [])
        return [
            {
                "account_id":     acc.get("resourceId") or acc.get("accountId", ""),
                "iban":           acc.get("iban", ""),
                # A currency or balance the bank did not state is None, not lira and not zero.
                "currency":       first(acc, "currency"),
                "account_type":   acc.get("cashAccountType", "CACC"),
                "name":           acc.get("name", "Akbank Hesabı"),
                "balance":        signed_amount(first(acc.get("balanceAmount"), "amount")),
            }
            for acc in accounts_raw
        ]

    def _parse_transactions(self, raw: Any, feed: Feed) -> None:
        """
        Add one row to `feed` per booked Akbank (NextGenPSD2) transaction.

        The direction is the amount's sign (positive credit, negative debit). A missing or unreadable amount
        has no sign and no value: the row is held, it is not a zero-lira expense. Pending entries are not
        booked money and are counted as ignored, by name.
        """
        section = raw.get("transactions") if isinstance(raw, dict) else None
        if not isinstance(section, dict) or not isinstance(section.get("booked"), list):
            raise FeedFailed("yanıtta transactions.booked listesi yok (beklenmeyen biçim)")
        for _ in section.get("pending") or []:
            feed.ignore("pending")
        for tx in feed.each(section["booked"]):
            if item_is_blank(tx):
                feed.blank()
                continue
            amount_obj = tx.get("transactionAmount") if isinstance(tx, dict) else None
            raw_amount = first(amount_obj, "amount")
            money = read_money(raw_amount)
            description = (
                first(tx, "remittanceInformationUnstructured")
                or first(tx.get("remittanceInformationStructured"), "reference")
                or "Akbank işlemi"
            )
            vendor = first(tx, "debtorName", "creditorName")
            feed.add(
                amount=raw_amount, direction=direction_from_sign(money),
                date=first(tx, "bookingDate", "valueDate"), currency=first(amount_obj, "currency"),
                description=str(description)[:200], reference=first(tx, "transactionId"),
                evidence={"amount": raw_amount, "currency": first(amount_obj, "currency"),
                          "bookingDate": first(tx, "bookingDate", "valueDate"), "transactionId": first(tx, "transactionId")},
                vendor=str(vendor)[:100] if vendor else None, raw_source="akbank_open_banking",
            )

