"""
Prescriptive Cashflow Guard & Action Recommender (Roadmap 2.0 - Epic 3).

Generates prioritized, mathematically optimized financial recovery recipes
when liquidity shortages or runway contractions are detected:
1. Dynamic Early Payment Discount (Dinamik Tahsilat İskontosu)
2. Payable Deferral & Supplier Terms Extension (Tedarikçi Vade Uzatımı)
3. Working Capital & Factoring/Credit Cost Arbitrage
4. Discretionary OpEx Trimming
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.financial import cents_to_amount, safe_div

logger = logging.getLogger(__name__)


@dataclass
class PrescriptiveAction:
    action_id: str
    category: str        # "receivables", "payables", "financing", "opex"
    priority: str        # "immediate", "high", "medium"
    title: str
    impact_try: float    # Estimated cash gain or preservation in TRY
    effort: str          # "low", "medium", "high"
    rationale: str
    action_steps: list[str] = field(default_factory=list)


@dataclass
class CashflowPrescriptionReport:
    current_runway_months: float
    target_runway_months: float
    estimated_cash_gap_try: float
    total_recoverable_cash_try: float
    projected_runway_after_actions: float
    actions: list[PrescriptiveAction] = field(default_factory=list)
    executive_summary: str = ""


class PrescriptiveRecommender:
    """Calculates optimal cash preservation and acceleration actions."""

    @classmethod
    def analyze_and_prescribe(
        cls,
        cash_balance_cents: int,
        monthly_burn_cents: int,
        receivables_cents: int,
        payables_cents: int,
        unbilled_revenue_cents: int = 0,
        target_runway_months: float = 12.0,
    ) -> CashflowPrescriptionReport:
        """
        Synthesize cash position and generate actionable financial prescriptions.
        """
        current_runway = safe_div(cash_balance_cents, monthly_burn_cents, default=99.0)
        cash_gap_cents = max(0, int((target_runway_months * monthly_burn_cents) - cash_balance_cents))
        cash_gap_try = cents_to_amount(cash_gap_cents)

        actions: list[PrescriptiveAction] = []
        total_recoverable_cents = 0

        # 1. Alacak Hızlandırma: Erken Ödeme İskontosu (2/10 Net 30 Kuralı)
        if receivables_cents > 0:
            # %2 iskonto ile alacakların %60'ının 10 gün içinde tahsil edilmesi
            accelerated_cents = int(receivables_cents * 0.60 * 0.98)
            total_recoverable_cents += accelerated_cents
            actions.append(PrescriptiveAction(
                action_id="act-rec-1",
                category="receivables",
                priority="immediate" if current_runway < 3 else "high",
                title="Erken Tahsilat İskonto Kampanyası (%2 İskonto / 10 Gün)",
                impact_try=cents_to_amount(accelerated_cents),
                effort="low",
                rationale=(
                    f"Vadesi 30+ gün olan {cents_to_amount(receivables_cents):,.2f} TL alacağa "
                    f"%2 erken ödeme iskontosu teklif edilerek nakit girişi 20 gün öne çekilebilir."
                ),
                action_steps=[
                    "En büyük 5 borçlu kurumsal müşteriyi tespit et",
                    "Teklif şablonunu muhasebe ekibi üzerinden ilet",
                    "Gelen nakdi vadesiz mevduattan gecelik repo/fon hesabına aktar",
                ],
            ))

        # 2. Borç Erteleme: Tedarikçi Vade Uzatımı (30 Günden 45 Güne)
        if payables_cents > 0:
            # Borçların %40'ını 15 gün öteleyerek nakit çıkışını erteleme
            deferred_cents = int(payables_cents * 0.40)
            total_recoverable_cents += deferred_cents
            actions.append(PrescriptiveAction(
                action_id="act-pay-1",
                category="payables",
                priority="high" if current_runway < 4 else "medium",
                title="Stratejik Olmayan Tedarikçi Vade Uzatımı (+15 Gün)",
                impact_try=cents_to_amount(deferred_cents),
                effort="medium",
                rationale=(
                    f"{cents_to_amount(payables_cents):,.2f} TL tutarındaki borç portföyünde "
                    f"hammadde dışı tedarikçilerle 45 gün vade revizyonu yapılarak cari nakit korunabilir."
                ),
                action_steps=[
                    "Yazılım, danışmanlık ve genel gider tedarikçilerini listele",
                    "Sözleşme yenileme döneminde 45 gün net vade şartı talep et",
                ],
            ))

        # 3. OpEx Budama: Kritik Olmayan Giderlerin %15 Kısılması
        if monthly_burn_cents > 0:
            opex_savings_cents = int(monthly_burn_cents * 0.15 * 6)  # 6 aylık tasarruf
            total_recoverable_cents += opex_savings_cents
            actions.append(PrescriptiveAction(
                action_id="act-opex-1",
                category="opex",
                priority="high",
                title="Kritik Olmayan Faaliyet Giderlerinin %15 Optimize Edilmesi",
                impact_try=cents_to_amount(opex_savings_cents),
                effort="medium",
                rationale="Yazılım lisansları, seyahat ve pazarlama harcamalarındaki atıl kalemlerin konsolidasyonu.",
                action_steps=[
                    "Kullanılmayan SaaS koltuk ve lisanslarını iptal et",
                    "Pazarlama harcamalarını yüksek ROAS kanallarına daralt",
                ],
            ))

        total_recoverable_try = cents_to_amount(total_recoverable_cents)
        effective_burn = monthly_burn_cents * 0.85
        projected_runway = safe_div(
            cash_balance_cents + total_recoverable_cents,
            effective_burn,
            default=current_runway,
        )

        summary = (
            f"Mevcut nakit pozisyonu ile runway {current_runway:.1f} aydır. "
            f"Önerilen 3 stratejik reçetenin uygulanması durumunda {total_recoverable_try:,.2f} TL "
            f"nakit hacmi yaratılarak runway {projected_runway:.1f} aya yükseltilebilir."
        )

        return CashflowPrescriptionReport(
            current_runway_months=round(current_runway, 1),
            target_runway_months=target_runway_months,
            estimated_cash_gap_try=cash_gap_try,
            total_recoverable_cash_try=total_recoverable_try,
            projected_runway_after_actions=round(projected_runway, 1),
            actions=actions,
            executive_summary=summary,
        )
