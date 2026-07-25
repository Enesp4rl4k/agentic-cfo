"""
Tax Agent — Skill 8.

Sorumluluk: Muhasebe verisinden vergi yükümlülüklerini hesaplar.
Türk vergi sistemi odaklı (KDV, stopaj, kurumlar vergisi) ama
genel yapı uluslararası kullanıma da uygundur.

Hesaplamalar:
1. KDV — gelir işlemlerinden KDV tahmini
2. Stopaj — maaş ve hizmet ödemelerinden stopaj
3. Kurumlar Vergisi — EBITDA üzerinden tahmini kurumlar vergisi
4. Ödeme takvimi — aylık/çeyreklik yükümlülükler

done_when: state['tax'] contains vat_payable, withholding_tax,
           corporate_tax_estimate, payment_calendar, narrative
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, date
from typing import Any

from app.agents.state import CFOState, AgentRunConfig, SkillResult

logger = logging.getLogger(__name__)

# ── Turkish Tax Rates ─────────────────────────────────────────────────────────

VAT_RATE = 0.20          # KDV oranı (standart %20)
WITHHOLDING_RATE = 0.15  # Stopaj oranı (maaş ve hizmet)
CORPORATE_TAX_RATE = 0.25  # Kurumlar vergisi oranı %25 (2024)
SSI_RATE = 0.225         # SGK işveren payı %22.5

# ── Pure calculations ─────────────────────────────────────────────────────────

def _compute_vat(transactions: list[dict[str, Any]]) -> dict[str, int]:
    """KDV hesaplama: gelirden çıktı KDV, giderden girdi KDV."""
    output_vat = 0   # satışlardan tahsil edilen KDV
    input_vat = 0    # alışlardan indirilecek KDV

    for tx in transactions:
        amount = tx.get("amount_cents", 0)
        cat = tx.get("category", "")
        tx_type = tx.get("type", "")

        if tx_type == "income" and cat in ("revenue", "other_income"):
            output_vat += int(amount * VAT_RATE)
        elif tx_type == "expense" and cat in ("cogs", "technology", "marketing", "utilities", "rent"):
            input_vat += int(amount * VAT_RATE)

    net_vat_payable = max(0, output_vat - input_vat)
    return {
        "output_vat": output_vat,
        "input_vat": input_vat,
        "net_vat_payable": net_vat_payable,
    }


def _compute_withholding(transactions: list[dict[str, Any]]) -> dict[str, int]:
    """Stopaj hesaplama: maaş ve hizmet ödemelerinden."""
    salary_total = sum(
        t.get("amount_cents", 0)
        for t in transactions
        if t.get("type") == "expense" and t.get("category") == "salary"
    )
    withholding = int(salary_total * WITHHOLDING_RATE)
    ssi = int(salary_total * SSI_RATE)

    return {
        "salary_base": salary_total,
        "income_tax_withholding": withholding,
        "ssi_employer": ssi,
        "total_payroll_tax": withholding + ssi,
    }


def _compute_corporate_tax(pnl: dict[str, Any]) -> dict[str, int]:
    """Kurumlar vergisi tahmini: EBITDA üzerinden."""
    ebitda = pnl.get("ebitda", 0)
    if ebitda <= 0:
        return {"taxable_income": 0, "corporate_tax_estimate": 0}

    # Basitleştirilmiş: EBITDA - depreciation tahmini (sabit %5)
    depreciation_estimate = int(ebitda * 0.05)
    taxable_income = max(0, ebitda - depreciation_estimate)
    tax = int(taxable_income * CORPORATE_TAX_RATE)

    return {
        "taxable_income": taxable_income,
        "corporate_tax_estimate": tax,
        "effective_rate": round(tax / ebitda * 100, 1) if ebitda > 0 else 0,
    }


def _build_payment_calendar(
    vat: dict[str, int],
    withholding: dict[str, int],
    corp_tax: dict[str, int],
    reference_month: str,
) -> list[dict[str, Any]]:
    """
    Ödeme takvimi: Türk vergi sistemine göre son tarihler.
    KDV: sonraki ay 28'ine kadar
    Stopaj: sonraki ay 26'sına kadar (muhtasar beyanname)
    Kurumlar vergisi: Nisan'da yıllık + 4 geçici vergi (mart, haziran, eylül, aralık)
    """
    try:
        year, month = int(reference_month[:4]), int(reference_month[5:7])
    except (ValueError, IndexError):
        year, month = datetime.now().year, datetime.now().month

    # Next month
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    calendar = []

    if vat["net_vat_payable"] > 0:
        calendar.append({
            "type": "KDV (VAT)",
            "due_date": f"{next_year:04d}-{next_month:02d}-28",
            "amount": vat["net_vat_payable"],
            "description": f"KDV beyannamesi — net ödenecek KDV",
        })

    if withholding["income_tax_withholding"] > 0:
        calendar.append({
            "type": "Stopaj (Withholding Tax)",
            "due_date": f"{next_year:04d}-{next_month:02d}-26",
            "amount": withholding["income_tax_withholding"],
            "description": "Muhtasar beyanname — gelir vergisi stopajı",
        })

    if withholding["ssi_employer"] > 0:
        calendar.append({
            "type": "SGK İşveren Payı",
            "due_date": f"{next_year:04d}-{next_month:02d}-28",
            "amount": withholding["ssi_employer"],
            "description": "SGK işveren payı",
        })

    if corp_tax["corporate_tax_estimate"] > 0:
        # Quarterly prepayment
        quarter_months = {3: 3, 6: 6, 9: 9, 12: 12}
        if month in quarter_months:
            calendar.append({
                "type": "Geçici Vergi",
                "due_date": f"{year:04d}-{month:02d}-17",
                "amount": int(corp_tax["corporate_tax_estimate"] / 4),
                "description": "Kurumlar vergisi geçici vergi (çeyreklik)",
            })

    calendar.sort(key=lambda x: x["due_date"])
    return calendar


async def _generate_tax_narrative(
    tax: dict[str, Any], settings
) -> str:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.2,
        max_tokens=512,
        api_key=settings.openai_api_key,
        base_url=settings.llm_base_url or None,
    )

    cal_text = "\n".join(
        f"- {p['type']}: {p['amount']/100:,.0f} TL — due {p['due_date']}"
        for p in tax.get("payment_calendar", [])
    )

    messages = [
        SystemMessage(content=(
            "You are a Turkish tax accountant. Summarize the tax position "
            "in 2-4 sentences. Highlight upcoming deadlines and cash flow impact. "
            "Be specific and actionable."
        )),
        HumanMessage(content=(
            f"VAT payable: {tax['vat']['net_vat_payable']/100:,.0f} TL\n"
            f"Withholding tax: {tax['withholding']['income_tax_withholding']/100:,.0f} TL\n"
            f"SSI employer: {tax['withholding']['ssi_employer']/100:,.0f} TL\n"
            f"Corporate tax estimate: {tax['corporate']['corporate_tax_estimate']/100:,.0f} TL\n\n"
            f"Upcoming payments:\n{cal_text or 'None'}"
        )),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_tax(
    state: CFOState,
    config: AgentRunConfig,
) -> SkillResult:
    """
    Tax Skill.
    done_when: state['tax']['payment_calendar'] is a list.
    """
    transactions = state.get("transactions", [])
    pnl = state.get("pnl", {})

    if not transactions:
        return SkillResult(
            ok=True,
            patch={"tax": None},
            confidence=1.0,
            detail="No transactions — tax calculation skipped.",
        )

    try:
        from app.config import get_settings
        settings = get_settings()

        vat = _compute_vat(transactions)
        withholding = _compute_withholding(transactions)
        corp_tax = _compute_corporate_tax(pnl)

        # Determine reference month from transactions
        dates = [
            t.get("transaction_date", "")[:7]
            for t in transactions
            if t.get("transaction_date")
        ]
        reference_month = max(dates) if dates else datetime.now(timezone.utc).strftime("%Y-%m")

        calendar = _build_payment_calendar(vat, withholding, corp_tax, reference_month)

        total_tax_burden = (
            vat["net_vat_payable"]
            + withholding["total_payroll_tax"]
            + corp_tax["corporate_tax_estimate"]
        )

        tax = {
            "vat": vat,
            "withholding": withholding,
            "corporate": corp_tax,
            "payment_calendar": calendar,
            "total_tax_burden": total_tax_burden,
            "reference_month": reference_month,
        }

        narrative = await _generate_tax_narrative(tax, settings)
        tax["narrative"] = narrative

        logger.info(
            "Tax agent complete: job=%s vat=%d corp_tax=%d total=%d",
            state.get("job_id"),
            vat["net_vat_payable"],
            corp_tax["corporate_tax_estimate"],
            total_tax_burden,
        )

        return SkillResult(
            ok=True,
            patch={"tax": tax},
            confidence=0.85,
            detail=(
                f"Tax calculated: VAT={vat['net_vat_payable']/100:,.0f}, "
                f"corporate tax est.={corp_tax['corporate_tax_estimate']/100:,.0f}, "
                f"total burden={total_tax_burden/100:,.0f}"
            ),
        )

    except Exception as exc:
        logger.exception("Tax agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Tax error: {exc}")
