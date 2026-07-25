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
                "currency":       acc.get("currency", "TRY"),
                "account_type":   acc.get("cashAccountType", "CACC"),
                "name":           acc.get("name", "Akbank Hesabı"),
                "balance":        float(acc.get("balanceAmount", {}).get("amount", 0)),
            }
            for acc in accounts_raw
        ]

    def _parse_transactions(self, raw: Any) -> list[dict[str, Any]]:
        """
        Normalize Akbank NextGenPSD2 transaction format to CFO pipeline format.
        """
        booked = raw.get("transactions", {}).get("booked", [])
        result: list[dict[str, Any]] = []

        for tx in booked:
            amount_obj  = tx.get("transactionAmount", {})
            raw_amount  = float(amount_obj.get("amount", 0) or 0)
            currency    = amount_obj.get("currency", "TRY")
            # Positive = credit (income), negative = debit (expense)
            tx_type     = "income" if raw_amount > 0 else "expense"
            amount_cents = abs(int(raw_amount * 100))

            description = (
                tx.get("remittanceInformationUnstructured")
                or tx.get("remittanceInformationStructured", {}).get("reference", "")
                or "Akbank işlemi"
            )
            vendor = tx.get("debtorName") or tx.get("creditorName") or None

            result.append({
                "amount_cents":      amount_cents,
                "type":              tx_type,
                "transaction_date":  tx.get("bookingDate") or tx.get("valueDate"),
                "description":       description[:200],
                "currency":          currency,
                "reference":         tx.get("transactionId"),
                "vendor":            vendor[:100] if vendor else None,
                "raw_source":        "akbank_open_banking",
            })

        return result
