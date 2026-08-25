"""
SMMM (Mali Müşavir) Turkish Tax Calculator & Cash Flow Tax Schedule Engine.
Calculates:
1. Monthly KDV1 Declaration (Hesaplanan KDV vs İndirilecek KDV -> Ödenecek / Devreden KDV)
2. Muhtasar ve Prim Hizmet Beyannamesi (Kira Stopajı, SMM Stopajı, Ücret SGK/Gelir Vergisi)
3. 3-Aylık Geçici Kurumlar Vergisi (%25 Vergi Oranı)
4. 30/60/90 Günlük Vergi Ödeme Takvimi & Nakit Çıkış Projeksiyonu
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class KDVDeclarationResult(BaseModel):
    period_year_month: str
    hesaplanan_kdv_391: Decimal    # Satışlardan doğan KDV
    indirilecek_kdv_191: Decimal   # Alış/Giderlerden doğan KDV
    onceki_donem_devreden_kdv: Decimal
    odenecek_kdv: Decimal          # Devlete ödenecek vergi
    sonraki_doneme_devreden_kdv: Decimal
    odeme_vadesi: date             # İlgili ayı takip eden ayın 26'sı
    status_summary: str


class MuhtasarStopajResult(BaseModel):
    period_year_month: str
    kira_stopaji: Decimal          # %20 Kira Stopajı
    smm_stopaji: Decimal           # %20 Serbest Meslek Makbuzu Stopajı
    toplam_stopaj: Decimal
    odeme_vadesi: date
    status_summary: str


class GeciciVergiResult(BaseModel):
    quarter: str                   # 2024-Q1, 2024-Q2 vb.
    ticari_kar: Decimal
    kanunen_kabul_edilmeyen_giderler: Decimal = Decimal("0.0")
    mali_kar_matrahi: Decimal
    kurumlar_vergisi_orani_pct: Decimal = Decimal("25.0")
    tahakkuk_eden_gecici_vergi: Decimal
    onceki_donemlerde_odenmis_gecici_vergi: Decimal = Decimal("0.0")
    odenecek_gecici_vergi: Decimal
    odeme_vadesi: date


class TaxCashOutflowItem(BaseModel):
    payment_date: date
    tax_type: str                  # KDV, MUHTASAR_SGK, GECICI_VERGI
    amount: Decimal
    priority: str = "HIGH"
    description: str


class TurkishTaxEngine:
    """Production SMMM Tax Calculation & Statutory Deadlines Engine."""

    @classmethod
    def calculate_monthly_kdv(
        cls,
        year: int,
        month: int,
        sales_kdv_391: Decimal,
        purchase_kdv_191: Decimal,
        previous_carryover_kdv: Decimal = Decimal("0.0"),
    ) -> KDVDeclarationResult:
        """
        Calculates monthly Turkish VAT (KDV-1) declaration.
        Formula: Net = 391 - (191 + Previous Devreden)
        If Net > 0: Ödenecek KDV
        If Net <= 0: Sonraki Döneme Devreden KDV
        """
        net_tax = sales_kdv_391 - (purchase_kdv_191 + previous_carryover_kdv)

        if net_tax > 0:
            odenecek = net_tax
            devreden = Decimal("0.0")
            summary = f"{year}/{month:02d} döneminde {odenecek:,.2f} TL Ödenecek KDV tahakkuk etmiştir."
        else:
            odenecek = Decimal("0.0")
            devreden = abs(net_tax)
            summary = f"{year}/{month:02d} döneminde ödenecek KDV çıkmamıştır. {devreden:,.2f} TL sonraki döneme devretmiştir."

        # Tax payment deadline: 26th of following month
        due_month = month + 1 if month < 12 else 1
        due_year = year if month < 12 else year + 1
        due_date = date(due_year, due_month, 26)

        return KDVDeclarationResult(
            period_year_month=f"{year}-{month:02d}",
            hesaplanan_kdv_391=sales_kdv_391,
            indirilecek_kdv_191=purchase_kdv_191,
            onceki_donem_devreden_kdv=previous_carryover_kdv,
            odenecek_kdv=odenecek,
            sonraki_doneme_devreden_kdv=devreden,
            odeme_vadesi=due_date,
            status_summary=summary,
        )

    @classmethod
    def calculate_muhtasar(
        cls,
        year: int,
        month: int,
        gross_rent_amount: Decimal = Decimal("0.0"),
        gross_smm_amount: Decimal = Decimal("0.0"),
    ) -> MuhtasarStopajResult:
        """Calculates Turkish Withholding Tax (Stopaj) for rent (%20) and freelance/consulting (%20)."""
        rent_tax = gross_rent_amount * Decimal("0.20")
        smm_tax = gross_smm_amount * Decimal("0.20")
        total_stopaj = rent_tax + smm_tax

        due_month = month + 1 if month < 12 else 1
        due_year = year if month < 12 else year + 1
        due_date = date(due_year, due_month, 26)

        return MuhtasarStopajResult(
            period_year_month=f"{year}-{month:02d}",
            kira_stopaji=rent_tax,
            smm_stopaji=smm_tax,
            toplam_stopaj=total_stopaj,
            odeme_vadesi=due_date,
            status_summary=f"Toplam {total_stopaj:,.2f} TL Muhtasar / Stopaj ödemesi hesaplanmıştır.",
        )

    @classmethod
    def calculate_gecici_vergi(
        cls,
        year: int,
        quarter: int,
        commercial_profit: Decimal,
        disallowed_expenses: Decimal = Decimal("0.0"),
        previously_paid_advance_tax: Decimal = Decimal("0.0"),
    ) -> GeciciVergiResult:
        """
        Calculates Turkish Corporate Advance Tax (Geçici Vergi %25).
        Quarter 1 (Jan-Mar): Due May 17
        Quarter 2 (Jan-Jun): Due Aug 17
        Quarter 3 (Jan-Sep): Due Nov 17
        Quarter 4 (Jan-Dec): Due Feb 17
        """
        matrah = commercial_profit + disallowed_expenses
        total_tax = max(Decimal("0.0"), matrah * Decimal("0.25"))
        payable = max(Decimal("0.0"), total_tax - previously_paid_advance_tax)

        due_dates = {
            1: date(year, 5, 17),
            2: date(year, 8, 17),
            3: date(year, 11, 17),
            4: date(year + 1, 2, 17),
        }
        due_date = due_dates.get(quarter, date(year, 5, 17))

        return GeciciVergiResult(
            quarter=f"{year}-Q{quarter}",
            ticari_kar=commercial_profit,
            kanunen_kabul_edilmeyen_giderler=disallowed_expenses,
            mali_kar_matrahi=matrah,
            kurumlar_vergisi_orani_pct=Decimal("25.0"),
            tahakkuk_eden_gecici_vergi=total_tax,
            onceki_donemlerde_odenmis_gecici_vergi=previously_paid_advance_tax,
            odenecek_gecici_vergi=payable,
            odeme_vadesi=due_date,
        )

    @classmethod
    def generate_30_day_tax_calendar(
        cls,
        current_date: date,
        kdv_res: KDVDeclarationResult,
        muhtasar_res: MuhtasarStopajResult,
        gecici_res: Optional[GeciciVergiResult] = None,
    ) -> List[TaxCashOutflowItem]:
        """Projects tax payment spikes within 30-60 days for cash flow forecasting."""
        items: List[TaxCashOutflowItem] = []

        if kdv_res.odenecek_kdv > 0:
            items.append(
                TaxCashOutflowItem(
                    payment_date=kdv_res.odeme_vadesi,
                    tax_type="KDV_1",
                    amount=kdv_res.odenecek_kdv,
                    description=f"{kdv_res.period_year_month} Dönemi Katma Değer Vergisi",
                )
            )

        if muhtasar_res.toplam_stopaj > 0:
            items.append(
                TaxCashOutflowItem(
                    payment_date=muhtasar_res.odeme_vadesi,
                    tax_type="MUHTASAR_SGK",
                    amount=muhtasar_res.toplam_stopaj,
                    description=f"{muhtasar_res.period_year_month} Dönemi Muhtasar ve Prim Hizmet",
                )
            )

        if gecici_res and gecici_res.odenecek_gecici_vergi > 0:
            items.append(
                TaxCashOutflowItem(
                    payment_date=gecici_res.odeme_vadesi,
                    tax_type="GECICI_VERGI",
                    amount=gecici_res.odenecek_gecici_vergi,
                    description=f"{gecici_res.quarter} Dönemi Geçici Kurumlar Vergisi",
                )
            )

        # Sort by payment date
        items.sort(key=lambda x: x.payment_date)
        return items
