"""Chart of Accounts adapters — international core + regional packs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class CoaClassification:
    account_code: str
    account_label: str
    confidence: float
    method: str
    adapter: str
    # Optional regional extras (e.g. THP group)
    extras: dict[str, Any] | None = None


class ChartOfAccountsAdapter(Protocol):
    name: str

    def classify(
        self,
        *,
        description: str,
        amount_cents: int,
        transaction_type: str = "expense",
        vendor: str | None = None,
    ) -> CoaClassification: ...

    async def async_classify(
        self,
        *,
        description: str,
        amount_cents: int,
        transaction_type: str = "expense",
        vendor: str | None = None,
    ) -> CoaClassification: ...


class GenericCoaAdapter:
    """
    Locale-agnostic CoA buckets (US GAAP-ish labels).
    Used when no regional accounting pack is enabled.
    """

    name = "generic_gaap"

    _RULES: list[tuple[str, str, list[str], str]] = [
        ("1000", "Cash & Cash Equivalents", ["cash", "bank", "transfer", "wire", "ach"], "asset"),
        ("1100", "Accounts Receivable", ["receivable", "invoice paid", "customer payment"], "asset"),
        ("1200", "Inventory", ["inventory", "stock", "goods"], "asset"),
        ("1500", "Fixed Assets", ["equipment", "laptop", "furniture", "capex"], "asset"),
        ("2000", "Accounts Payable", ["payable", "vendor bill", "supplier"], "liability"),
        ("2100", "Taxes Payable", ["tax", "vat", "gst", "withholding", "payroll tax"], "liability"),
        ("4000", "Revenue", ["revenue", "sales", "subscription", "mrr", "invoice"], "income"),
        ("5000", "Cost of Goods Sold", ["cogs", "cost of sales", "fulfillment"], "expense"),
        ("6100", "Payroll Expense", ["salary", "payroll", "wage", "contractor"], "expense"),
        ("6200", "Rent Expense", ["rent", "lease", "office space"], "expense"),
        ("6300", "Software & SaaS", ["saas", "software", "aws", "cloud", "subscription fee"], "expense"),
        ("6400", "Marketing Expense", ["ads", "marketing", "advertising", "campaign"], "expense"),
        ("6500", "Travel & Entertainment", ["travel", "flight", "hotel", "uber"], "expense"),
        ("6900", "General & Administrative", ["office", "admin", "legal", "insurance"], "expense"),
    ]

    def classify(
        self,
        *,
        description: str,
        amount_cents: int,
        transaction_type: str = "expense",
        vendor: str | None = None,
    ) -> CoaClassification:
        text = f"{description or ''} {vendor or ''}".lower()
        tx = (transaction_type or "expense").lower()

        if tx in ("income", "revenue", "credit"):
            return CoaClassification(
                account_code="4000",
                account_label="Revenue",
                confidence=0.7,
                method="type_default",
                adapter=self.name,
            )

        best: tuple[float, tuple[str, str, list[str], str]] | None = None
        for rule in self._RULES:
            code, label, keywords, _kind = rule
            hits = sum(1 for kw in keywords if kw in text)
            if hits:
                score = min(0.95, 0.55 + 0.15 * hits)
                if best is None or score > best[0]:
                    best = (score, rule)

        if best:
            score, (code, label, _, _) = best
            return CoaClassification(
                account_code=code,
                account_label=label,
                confidence=score,
                method="keyword",
                adapter=self.name,
            )

        return CoaClassification(
            account_code="6900",
            account_label="General & Administrative",
            confidence=0.4,
            method="fallback",
            adapter=self.name,
        )

    async def async_classify(
        self,
        *,
        description: str,
        amount_cents: int,
        transaction_type: str = "expense",
        vendor: str | None = None,
    ) -> CoaClassification:
        return self.classify(
            description=description,
            amount_cents=amount_cents,
            transaction_type=transaction_type,
            vendor=vendor,
        )


class TrThpAdapter:
    """Wraps THPClassifier as a ChartOfAccountsAdapter (Turkey pack)."""

    name = "tr_thp"

    def __init__(self) -> None:
        from app.agents.accounting.thp_classifier import get_thp_classifier

        self._inner = get_thp_classifier()

    def classify(
        self,
        *,
        description: str,
        amount_cents: int,
        transaction_type: str = "expense",
        vendor: str | None = None,
    ) -> CoaClassification:
        result = self._inner.classify(
            description=description,
            amount_kurus=amount_cents,
            transaction_type=transaction_type,
            vendor=vendor,
        )
        return CoaClassification(
            account_code=result.hesap_kodu,
            account_label=result.hesap_adi,
            confidence=float(result.confidence),
            method=str(getattr(result, "yontem", "thp") or "thp"),
            adapter=self.name,
            extras={
                "ana_grup": getattr(result, "ana_grup", None),
                "hesap_kodu": result.hesap_kodu,
                "hesap_adi": result.hesap_adi,
            },
        )

    async def async_classify(
        self,
        *,
        description: str,
        amount_cents: int,
        transaction_type: str = "expense",
        vendor: str | None = None,
    ) -> CoaClassification:
        if hasattr(self._inner, "async_classify"):
            result = await self._inner.async_classify(
                description=description,
                amount_kurus=amount_cents,
                transaction_type=transaction_type,
                vendor=vendor,
            )
        else:
            result = self._inner.classify(
                description=description,
                amount_kurus=amount_cents,
                transaction_type=transaction_type,
                vendor=vendor,
            )
        return CoaClassification(
            account_code=result.hesap_kodu,
            account_label=result.hesap_adi,
            confidence=float(result.confidence),
            method=str(getattr(result, "yontem", "thp") or "thp"),
            adapter=self.name,
            extras={
                "ana_grup": getattr(result, "ana_grup", None),
                "hesap_kodu": result.hesap_kodu,
                "hesap_adi": result.hesap_adi,
            },
        )


def get_coa_adapter(*, regional_packs: list[str] | None = None) -> ChartOfAccountsAdapter:
    packs = [p.lower() for p in (regional_packs or [])]
    if "tr" in packs:
        return TrThpAdapter()
    return GenericCoaAdapter()
