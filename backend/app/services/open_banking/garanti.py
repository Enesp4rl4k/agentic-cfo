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

from app.services.open_banking.base import BankOAuthConfig, OpenBankingClient


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
                "currency":     acc.get("CurrencyCode") or acc.get("currency", "TRY"),
                "account_type": acc.get("AccountType", "CURRENT"),
                "name":         acc.get("AccountName", "Garanti BBVA Hesabı"),
                "balance":      float(acc.get("Balance") or acc.get("balance") or 0),
            }
            for acc in account_list
        ]

    def _parse_transactions(self, raw: Any) -> list[dict[str, Any]]:
        """
        Normalize Garanti BBVA transaction format to CFO pipeline format.

        Garanti uses:
          TransactionType: "C" = Credit (income), "D" = Debit (expense)
          TransactionDate: "YYYYMMDD" format (different from Akbank)
        """
        tx_list = (
            raw.get("TransactionList")
            or raw.get("transactions")
            or raw.get("data")
            or []
        )
        result: list[dict[str, Any]] = []

        for tx in tx_list:
            raw_amount = float(tx.get("Amount") or tx.get("amount") or 0)
            tx_type_code = (tx.get("TransactionType") or "D").upper()
            tx_type = "income" if tx_type_code == "C" else "expense"
            amount_cents = abs(int(raw_amount * 100))

            # Normalize date from YYYYMMDD to YYYY-MM-DD
            raw_date = tx.get("TransactionDate") or tx.get("BookingDate") or ""
            if len(raw_date) == 8 and raw_date.isdigit():
                date_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
            else:
                date_str = raw_date  # Assume already ISO format

            description = (
                tx.get("Description")
                or tx.get("remittanceInformationUnstructured", "")
                or "Garanti BBVA işlemi"
            )
            vendor = tx.get("CounterPartyName") or tx.get("DebtorName") or None

            result.append({
                "amount_cents":     amount_cents,
                "type":             tx_type,
                "transaction_date": date_str,
                "description":      description[:200],
                "currency":         tx.get("CurrencyCode") or tx.get("currency", "TRY"),
                "reference":        tx.get("TransactionId") or tx.get("ReferenceNumber"),
                "vendor":           vendor[:100] if vendor else None,
                "raw_source":       "garanti_open_banking",
            })

        return result
