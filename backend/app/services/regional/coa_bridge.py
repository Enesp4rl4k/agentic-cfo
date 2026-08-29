"""Bridge ChartOfAccountsAdapter → THPSonucu for double-entry compatibility."""
from __future__ import annotations

from typing import Any

from app.services.accounting.thp_classifier import THPSonucu
from app.services.regional.coa import ChartOfAccountsAdapter, CoaClassification, get_coa_adapter


def _tip_and_balance(code: str, label: str) -> tuple[str, str, str]:
    """Map generic / THP codes to (tip, normal_bakiye, ana_grup)."""
    c = (code or "").strip()
    if c.startswith(("1", "10", "11", "12", "15")) or c in {"1000", "1100", "1200", "1500"}:
        return "varlık", "borç", "Assets"
    if c.startswith(("2", "20", "21")) or c in {"2000", "2100"}:
        return "borç", "alacak", "Liabilities"
    if c.startswith("4") or c == "4000":
        return "gelir", "alacak", "Revenue"
    if c.startswith(("5", "6", "7")) or c in {"5000", "6100", "6200", "6300", "6400", "6500", "6900"}:
        return "gider", "borç", "Expenses"
    lower = (label or "").lower()
    if "revenue" in lower or "income" in lower or "gelir" in lower:
        return "gelir", "alacak", "Revenue"
    if "asset" in lower or "cash" in lower:
        return "varlık", "borç", "Assets"
    return "gider", "borç", "Expenses"


def coa_to_thp(result: CoaClassification) -> THPSonucu:
    extras = result.extras or {}
    if extras.get("hesap_kodu") and extras.get("hesap_adi"):
        tip = str(extras.get("tip") or "gider")
        normal = str(extras.get("normal_bakiye") or "borç")
        ana = str(extras.get("ana_grup") or "THP")
        # Prefer extras from THP when present
        from app.services.accounting.thp_classifier import THP_HESAPLARI

        thp = THP_HESAPLARI.get(result.account_code)
        if thp:
            tip, normal, ana = thp.tip, thp.normal_bakiye, thp.ana_grup
        return THPSonucu(
            hesap_kodu=result.account_code,
            hesap_adi=result.account_label,
            ana_grup=ana,
            normal_bakiye=normal,
            tip=tip,
            confidence=float(result.confidence),
            yontem=result.method,
            aciklama=f"adapter={result.adapter}",
        )

    tip, normal, ana = _tip_and_balance(result.account_code, result.account_label)
    return THPSonucu(
        hesap_kodu=result.account_code,
        hesap_adi=result.account_label,
        ana_grup=ana,
        normal_bakiye=normal,
        tip=tip,
        confidence=float(result.confidence),
        yontem=result.method,
        aciklama=f"adapter={result.adapter}",
    )


class CoaBackedClassifier:
    """
    Drop-in replacement for THPClassifier when using ChartOfAccountsAdapter.
    Double-entry engine still consumes THPSonucu.
    """

    def __init__(self, adapter: ChartOfAccountsAdapter) -> None:
        self._adapter = adapter

    def classify(
        self,
        description: str,
        amount_kurus: int,
        transaction_type: str,
        vendor: str | None = None,
    ) -> THPSonucu:
        raw = self._adapter.classify(
            description=description,
            amount_cents=amount_kurus,
            transaction_type=transaction_type,
            vendor=vendor,
        )
        return coa_to_thp(raw)

    async def async_classify(
        self,
        description: str,
        amount_kurus: int,
        transaction_type: str,
        vendor: str | None = None,
    ) -> THPSonucu:
        raw = await self._adapter.async_classify(
            description=description,
            amount_cents=amount_kurus,
            transaction_type=transaction_type,
            vendor=vendor,
        )
        return coa_to_thp(raw)


def build_classifier_for_packs(
    regional_packs: list[str] | None,
    *,
    use_llm_fallback: bool = True,
) -> Any:
    """
    TR pack → native THPClassifier (LLM fallback available).
    Otherwise → GenericCoaAdapter wrapped as CoaBackedClassifier.
    """
    packs = [p.lower() for p in (regional_packs or [])]
    if "tr" in packs:
        from app.services.accounting.thp_classifier import get_thp_classifier

        return get_thp_classifier()
    adapter = get_coa_adapter(regional_packs=packs)
    return CoaBackedClassifier(adapter)
