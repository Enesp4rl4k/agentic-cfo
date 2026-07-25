"""Open Banking connectors — Akbank, Garanti BBVA."""
from app.services.open_banking.base import OpenBankingClient, BankOAuthConfig, OpenBankingError
from app.services.open_banking.akbank import AkbankClient
from app.services.open_banking.garanti import GarantiClient

__all__ = [
    "OpenBankingClient", "BankOAuthConfig", "OpenBankingError",
    "AkbankClient", "GarantiClient",
]


def get_bank_client(
    bank_id: str,
    client_id: str,
    client_secret: str,
    sandbox: bool = True,
) -> OpenBankingClient:
    """Factory: return the correct bank client by bank_id."""
    clients = {
        "akbank":  AkbankClient,
        "garanti": GarantiClient,
    }
    cls = clients.get(bank_id.lower())
    if cls is None:
        raise ValueError(f"Unsupported bank: '{bank_id}'. Supported: {list(clients)}")
    return cls(client_id=client_id, client_secret=client_secret, sandbox=sandbox)
