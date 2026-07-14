"""
Tax Agent — Skill 6 of 8.

Responsibility: Calculate Turkish tax obligations from transactions.
Computes:
  - KDV (VAT): collected (on revenue) vs paid (on expenses), net payable
  - Stopaj (Withholding Tax): on salary, rent, professional services
  - Geçici Vergi (Provisional Corporate Tax): quarterly estimate
  - Kurumlar Vergisi (Corporate Tax): annual estimate at 25%

All amounts in cents (kuruş). Uses Turkish tax law defaults (2024):
  - Standard KDV rate: 20%
  - Reduced KDV rate: 10% (food, health)
  - Zero KDV: exports
  - Stopaj on salary: 15–35% progressive (simplified to 20% flat for estimate)
  - Stopaj on rent to individuals: 20%
  - Kurumlar vergisi: 25%

done_when: state['tax_analysis'] contains kdv_net, stopaj_total, kurumlar_vergisi_estimate.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import CFOState, AgentRunConfig, SkillResult
from app.config import get_settings

logger = logging.getLogger(__name__)

# Turkish tax rates (2024)
KDV_STANDARD_RATE = 0.20      # 20% — genel oran
KDV_REDUCED_RATE = 0.10       # 10% — indirimli oran (gıda, sağlık)
STOPAJ_SALARY_RATE = 0.20     # simplified 20% flat estimate
STOPAJ_RENT_RATE = 0.20       # kiradan stopaj
STOPAJ_PROFESSIONAL_RATE = 0.20  # serbest meslek stopajı
KURUMLAR_VERGISI_RATE = 0.25  # 25% kurumlar vergisi


def _fmt(cents: int) -> str:
    return f"₺{cents / 100:,.2f}"


def _compute_kdv(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    """
    KDV hesaplama:
    - Tahsil edilen KDV: gelir işlemlerinden (revenue, other_income)
    - Ödenen KDV: gider işlemlerinden (iş giderleri — salary ve loan hariç)
    - KDV net: tahsil - ödenen (pozitif = vergi dairesine ödenecek)
    """
    kdv_non_applicable_categories = {"salary", "loan", "tax"}

    kdv_collected = 0  # revenue üzerinden
    kdv_paid = 0       # gider üzerinden

    kdv_by_month: dict[str, dict[str, int]] = {}

    for tx in transactions:
        amount = tx.get("amount_cents", 0)
        tx_type = tx.get("type", "expense")
        category = tx.get("category", "other_expense")
        raw_date = tx.get("transaction_date")
        month_key = str(raw_date)[:7] if raw_date else "unknown"

        if tx_type == "income" and category in ("revenue", "other_income"):
            # KDV tahsil edildi (alıcıdan)
            kdv = int(amount * KDV_STANDARD_RATE)
            kdv_collected += kdv
            bucket = kdv_by_month.setdefault(month_key, {"collected": 0, "paid": 0})
            bucket["collected"] += kdv

        elif tx_type == "expense" and category not in kdv_non_applicable_categories:
            # KDV ödendi (tedarikçiye)
            kdv = int(amount * KDV_STANDARD_RATE)
            kdv_paid += kdv
            bucket = kdv_by_month.setdefault(month_key, {"collected": 0, "paid": 0})
            bucket["paid"] += kdv

    kdv_net = kdv_collected - kdv_paid  # pozitif → ödeme, negatif → iade hakkı

    monthly_kdv = [
        {
            "month": k,
            "collected": v["collected"],
            "paid": v["paid"],
            "net": v["collected"] - v["paid"],
        }
        for k, v in sorted(kdv_by_month.items())
    ]

    return {
        "kdv_collected": kdv_collected,
        "kdv_paid": kdv_paid,
        "kdv_net": kdv_net,
        "kdv_payable": max(0, kdv_net),
        "kdv_refundable": max(0, -kdv_net),
        "monthly_kdv": monthly_kdv,
    }


def _compute_stopaj(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Stopaj (Withholding Tax) hesaplama:
    - Maaş ödemeleri: %20 stopaj (basitleştirilmiş)
    - Kira ödemeleri: %20 stopaj
    - Serbest meslek: %20 stopaj
    """
    salary_total = sum(
        t.get("amount_cents", 0)
        for t in transactions
        if t.get("type") == "expense" and t.get("category") == "salary"
    )
    rent_total = sum(
        t.get("amount_cents", 0)
        for t in transactions
        if t.get("type") == "expense" and t.get("category") == "rent"
    )

    stopaj_salary = int(salary_total * STOPAJ_SALARY_RATE)
    stopaj_rent = int(rent_total * STOPAJ_RENT_RATE)
    stopaj_total = stopaj_salary + stopaj_rent

    return {
        "salary_gross": salary_total,
        "stopaj_salary": stopaj_salary,
        "rent_gross": rent_total,
        "stopaj_rent": stopaj_rent,
        "stopaj_total": stopaj_total,
    }


def _compute_kurumlar_vergisi(pnl: dict[str, Any]) -> dict[str, Any]:
    """
    Kurumlar Vergisi (Corporate Tax) ve Geçici Vergi tahmini.
    - Kurumlar vergisi: net_income * 25% (yıllık)
    - Geçici vergi: kurumlar vergisi / 4 (çeyrek)
    """
    net_income = pnl.get("net_income", 0)
    taxable_income = max(0, net_income)
    kurumlar_vergisi = int(taxable_income * KURUMLAR_VERGISI_RATE)
    gecici_vergi_quarterly = kurumlar_vergisi // 4

    return {
        "taxable_income": taxable_income,
        "kurumlar_vergisi_rate": KURUMLAR_VERGISI_RATE,
        "kurumlar_vergisi_annual": kurumlar_vergisi,
        "gecici_vergi_quarterly": gecici_vergi_quarterly,
        "net_income_after_tax": net_income - kurumlar_vergisi,
    }


def _build_tax_alerts(kdv: dict, stopaj: dict, kurumlar: dict) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    if kdv["kdv_payable"] > 0:
        alerts.append({
            "level": "info",
            "message": f"KDV ödemesi: {_fmt(kdv['kdv_payable'])} — aylık beyanname kontrol edin.",
        })
    if kdv["kdv_refundable"] > 0:
        alerts.append({
            "level": "info",
            "message": f"KDV iade hakkı: {_fmt(kdv['kdv_refundable'])} — iade başvurusu yapılabilir.",
        })
    if stopaj["stopaj_total"] > 0:
        alerts.append({
            "level": "info",
            "message": f"Stopaj yükümlülüğü: {_fmt(stopaj['stopaj_total'])} — muhtasar beyanname.",
        })
    if kurumlar["kurumlar_vergisi_annual"] > 0:
        alerts.append({
            "level": "warning",
            "message": (
                f"Tahmini kurumlar vergisi: {_fmt(kurumlar['kurumlar_vergisi_annual'])} "
                f"(geçici vergi: {_fmt(kurumlar['gecici_vergi_quarterly'])}/çeyrek)."
            ),
        })

    return alerts


async def _generate_tax_narrative(
    kdv: dict, stopaj: dict, kurumlar: dict, alerts: list[dict], settings
) -> str:
    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.1,
        max_tokens=600,
        api_key=settings.openai_api_key,
    )
    summary = (
        f"KDV Tahsil Edilen: {_fmt(kdv['kdv_collected'])}\n"
        f"KDV Ödenen: {_fmt(kdv['kdv_paid'])}\n"
        f"KDV Net (Ödenecek/İade): {_fmt(kdv['kdv_net'])}\n"
        f"Stopaj Toplamı: {_fmt(stopaj['stopaj_total'])}\n"
        f"  - Maaş Stopajı: {_fmt(stopaj['stopaj_salary'])}\n"
        f"  - Kira Stopajı: {_fmt(stopaj['stopaj_rent'])}\n"
        f"Tahmini Kurumlar Vergisi (Yıllık): {_fmt(kurumlar['kurumlar_vergisi_annual'])}\n"
        f"Geçici Vergi (Çeyrek): {_fmt(kurumlar['gecici_vergi_quarterly'])}\n"
    )
    messages = [
        SystemMessage(content=(
            "Sen deneyimli bir Türk mali müşavirisin. "
            "Vergi yükümlülüklerini analiz et ve yöneticiye özlü, "
            "uygulanabilir bir vergi planlama özeti sun (3-5 cümle). "
            "Önemli beyanname tarihlerini ve riskleri vurgula. "
            "Türkçe yanıt ver."
        )),
        HumanMessage(content=f"Vergi Özeti:\n{summary}"),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


async def run_tax(state: CFOState, config: AgentRunConfig) -> SkillResult:
    """
    Tax Skill.
    done_when: state['tax_analysis']['kdv_net'] is an integer AND
               state['tax_analysis']['kurumlar_vergisi_annual'] is an integer.
    """
    transactions = state.get("transactions", [])
    pnl = state.get("pnl", {})

    if not transactions:
        return SkillResult(ok=False, detail="İşlem verisi bulunamadı — vergi hesaplaması yapılamıyor.", halt=False)

    try:
        settings = get_settings()

        kdv = _compute_kdv(transactions)
        stopaj = _compute_stopaj(transactions)
        kurumlar = _compute_kurumlar_vergisi(pnl)
        alerts = _build_tax_alerts(kdv, stopaj, kurumlar)
        narrative = await _generate_tax_narrative(kdv, stopaj, kurumlar, alerts, settings)

        total_tax_burden = (
            kdv["kdv_payable"]
            + stopaj["stopaj_total"]
            + kurumlar["kurumlar_vergisi_annual"]
        )

        tax_analysis = {
            "kdv": kdv,
            "stopaj": stopaj,
            "kurumlar_vergisi": kurumlar,
            "total_tax_burden": total_tax_burden,
            "effective_tax_rate": (
                round(total_tax_burden / max(1, pnl.get("revenue", 1)), 4)
                if pnl.get("revenue")
                else 0.0
            ),
            "alerts": alerts,
            "narrative": narrative,
        }

        return SkillResult(
            ok=True,
            patch={"tax_analysis": tax_analysis},
            confidence=0.88,
            detail=(
                f"Vergi analizi: KDV net={_fmt(kdv['kdv_net'])}, "
                f"stopaj={_fmt(stopaj['stopaj_total'])}, "
                f"kurumlar vergisi={_fmt(kurumlar['kurumlar_vergisi_annual'])}"
            ),
        )
    except Exception as exc:
        logger.exception("Tax agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Vergi analizi hatası: {exc}")
