"""
Enflasyon Muhasebesi Motoru — TMS 29 / VUK Geçici 33. Madde (Phase 2 & Mevzuat).

Türkiye'deki yüksek enflasyon dönemlerinde mali tabloların
TÜİK TÜFE/Yİ-ÜFE endeks katsayıları ile düzeltilmesini sağlar:
1. Parasal ve Parasal Olmayan Varlık/Kaynak Sınıflandırması
2. Parasal Olmayan Kıymetlerin (Stoklar, MDV, Özkaynaklar) Endekslenmesi
3. Net Parasal Pozisyon (NPP) Enflasyon Kâr/Zarar Hesabı
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.financial import cents_to_amount, safe_div

logger = logging.getLogger(__name__)

# Örnek TÜİK Fiyat Endeks Tablosu (2023 - 2024 Referans Endeksleri)
SAMPLE_CPI_INDEX = {
    "2023-01": 1203.0,
    "2023-06": 1350.0,
    "2023-12": 1859.0,
    "2024-01": 1984.0,
    "2024-03": 2139.0,
    "2024-06": 2340.0,
    "2024-12": 2680.0,
}


@dataclass
class AdjustedAssetItem:
    item_name: str
    is_monetary: bool
    acquisition_period: str
    nominal_amount_cents: int
    adjustment_factor: float
    adjusted_amount_cents: int
    inflation_difference_cents: int


@dataclass
class InflationAdjustmentResult:
    reporting_period: str
    base_index: float
    monetary_assets_cents: int
    monetary_liabilities_cents: int
    net_monetary_position_cents: int  # Varlıklar - Borçlar
    net_monetary_loss_cents: int      # Enflasyon erimesinden kaynaklanan net kayıp
    adjusted_assets: list[AdjustedAssetItem] = field(default_factory=list)
    adjusted_equity_difference_cents: int = 0
    cfo_commentary: str = ""


class InflationAccountingEngine:
    """TMS 29 ve VUK uyumlu Enflasyon Düzeltmesi Motoru."""

    @classmethod
    def calculate_adjustment(
        cls,
        reporting_period: str,
        balance_sheet_items: list[dict[str, Any]],
        cpi_table: dict[str, float] | None = None,
    ) -> InflationAdjustmentResult:
        """
        Calculate inflation restatements for a set of balance sheet items.
        """
        cpi = cpi_table or SAMPLE_CPI_INDEX
        end_index = cpi.get(reporting_period, 2340.0)

        adjusted_items: list[AdjustedAssetItem] = []
        monetary_assets = 0
        monetary_liabilities = 0
        total_equity_diff = 0

        for item in balance_sheet_items:
            name = item.get("name", "Varlık/Kaynak")
            is_monetary = item.get("is_monetary", True)
            is_liability = item.get("is_liability", False)
            acq_period = item.get("acquisition_period", reporting_period)
            nominal_cents = item.get("amount_cents", 0)

            if is_monetary:
                # Parasal kalemler nominal değerinde kalır
                if is_liability:
                    monetary_liabilities += nominal_cents
                else:
                    monetary_assets += nominal_cents

                adjusted_items.append(AdjustedAssetItem(
                    item_name=name,
                    is_monetary=True,
                    acquisition_period=acq_period,
                    nominal_amount_cents=nominal_cents,
                    adjustment_factor=1.0,
                    adjusted_amount_cents=nominal_cents,
                    inflation_difference_cents=0,
                ))
            else:
                # Parasal olmayan kalemler TÜFE katsayısıyla endekslenir
                start_index = cpi.get(acq_period, end_index)
                factor = round(safe_div(end_index, start_index, default=1.0), 4)
                adjusted_cents = round(nominal_cents * factor)
                diff_cents = adjusted_cents - nominal_cents

                if "özkaynak" in name.lower() or "sermaye" in name.lower():
                    total_equity_diff += diff_cents

                adjusted_items.append(AdjustedAssetItem(
                    item_name=name,
                    is_monetary=False,
                    acquisition_period=acq_period,
                    nominal_amount_cents=nominal_cents,
                    adjustment_factor=factor,
                    adjusted_amount_cents=adjusted_cents,
                    inflation_difference_cents=diff_cents,
                ))

        # Net Parasal Pozisyon Kâr/Zarar Hesabı:
        # Net Parasal Pozisyon (NPP) = Parasal Varlıklar - Parasal Borçlar
        # Pozitif NPP enflasyon döneminde satın alma gücü kaybı (Zarar) yaratır.
        npp_cents = monetary_assets - monetary_liabilities
        avg_inflation_rate = safe_div(end_index - 1859.0, 1859.0, default=0.25)
        net_monetary_loss = round(npp_cents * avg_inflation_rate)

        commentary = (
            f"{reporting_period} dönemi enflasyon düzeltmesinde Net Parasal Pozisyon "
            f"{cents_to_amount(npp_cents):,.2f} TL olarak belirlenmiştir. Yüksek enflasyon ortamında "
            f"parasal varlıkların erimesinden doğan net satın alma gücü kaybı "
            f"{cents_to_amount(net_monetary_loss):,.2f} TL'dir."
        )

        return InflationAdjustmentResult(
            reporting_period=reporting_period,
            base_index=end_index,
            monetary_assets_cents=monetary_assets,
            monetary_liabilities_cents=monetary_liabilities,
            net_monetary_position_cents=npp_cents,
            net_monetary_loss_cents=net_monetary_loss,
            adjusted_assets=adjusted_items,
            adjusted_equity_difference_cents=total_equity_diff,
            cfo_commentary=commentary,
        )
