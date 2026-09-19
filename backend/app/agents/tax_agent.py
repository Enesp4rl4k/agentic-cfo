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
from datetime import UTC, datetime
from typing import Any

from app.agents.state import AgentRunConfig, CFOState, SkillResult

logger = logging.getLogger(__name__)

# ── S1-5 / S4-1: Türkiye Vergi Oranları ve Takvimi ───────────────────────────

# KDV oranları (2024 — Hazine ve Maliye Bakanlığı)
KDV_ORANLARI = {
    "standart":      0.20,   # %20 — genel (2024'te %18'den %20'ye çıktı)
    "indirimli_1":   0.10,   # %10 — gıda, ilaç, temel tüketim
    "indirimli_2":   0.01,   # %1 — konut, tarımsal
}
# Satış işlemleri için varsayılan KDV oranı
VAT_RATE = KDV_ORANLARI["standart"]

# Stopaj oranları (GVK Madde 94)
STOPAJ_ORANLARI = {
    "ucret":               0.15,   # Ücret → kademeli, %15 ortalama
    "serbest_meslek":      0.20,   # Serbest meslek (avukat, danışman)
    "kira":                0.20,   # Kira stopajı
    "faiz":                0.15,   # Mevduat faizi
    "temettü":             0.10,   # Temettü dağıtımı
}
WITHHOLDING_RATE = STOPAJ_ORANLARI["ucret"]

# Kurumlar vergisi (KVK Madde 32)
CORPORATE_TAX_RATE = 0.25  # %25 (2024)
KURUMLAR_VERGISI_AVANSI_ORANI = 0.25  # Geçici vergi = kurumlar vergisi oranı

# SGK
SSI_RATE = 0.225         # SGK işveren payı %22.5 (uzun vadeli sigorta dahil)
SSI_CALISMA_SAATI_RATE = 0.02  # İşsizlik sigortası %2

# Geçici vergi dönemleri ve son tarihleri (GVK Mükerrer Madde 120)
GECICI_VERGI_TAKVIMI = {
    # dönem_sonu: beyanname_son_tarihi (son ödeme tarihi 3 gün sonra)
    "03": "05-17",   # Q1 (Ocak-Mart) → 17 Mayıs
    "06": "08-17",   # Q2 (Nisan-Haziran) → 17 Ağustos
    "09": "11-17",   # Q3 (Temmuz-Eylül) → 17 Kasım
    "12": "02-17",   # Q4 (Ekim-Aralık) → bir sonraki yıl 17 Şubat
}

# KDV beyanname takvimi: her ayın 28'i (ertesi ay)
KDV_BEYANNAME_GUN = 28
# Muhtasar: her ayın 26'sı (ertesi ay)
MUHTASAR_GUN = 26
# SGK son ödeme günü: ayın 28'i
SGK_SON_GUN = 28

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
    S1-5 / S4-1: Türk vergi sistemine göre doğru son tarihler.

    KDV:      ertesi ayın 28'i (KDVK Madde 41)
    Stopaj:   ertesi ayın 26'sı (GVK Madde 98 — muhtasar beyanname)
    SGK:      aynı ayın 28'i (5510 sayılı Kanun)
    Geçici:   Q1→17 Mayıs, Q2→17 Ağustos, Q3→17 Kasım, Q4→ertesi yıl 17 Şubat
    Yıllık KV: her yılın Nisan ayı (beyannameyi izleyen ay)
    """
    try:
        year, month = int(reference_month[:4]), int(reference_month[5:7])
    except (ValueError, IndexError):
        year, month = datetime.now().year, datetime.now().month

    # Bir sonraki ay
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    calendar: list[dict[str, Any]] = []

    # KDV beyannamesi
    if vat["net_vat_payable"] > 0:
        calendar.append({
            "type": "KDV (VAT)",
            "due_date": f"{next_year:04d}-{next_month:02d}-{KDV_BEYANNAME_GUN:02d}",
            "amount": vat["net_vat_payable"],
            "description": (
                f"KDV beyannamesi (KDVK Madde 41) — "
                f"Ödenecek KDV: ₺{vat['net_vat_payable']/100:,.0f}"
            ),
            "urgency": "high" if vat["net_vat_payable"] > 10_000_00 else "normal",
        })

    # Muhtasar beyanname (stopaj)
    if withholding["income_tax_withholding"] > 0:
        calendar.append({
            "type": "Stopaj (Withholding Tax)",
            "due_date": f"{next_year:04d}-{next_month:02d}-{MUHTASAR_GUN:02d}",
            "amount": withholding["income_tax_withholding"],
            "description": (
                f"Muhtasar beyanname (GVK Madde 98) — "
                f"Stopaj: ₺{withholding['income_tax_withholding']/100:,.0f}"
            ),
            "urgency": "normal",
        })


    # SGK işveren payı
    if withholding["ssi_employer"] > 0:
        calendar.append({
            "type": "SGK İşveren Payı",
            "due_date": f"{year:04d}-{month:02d}-{SGK_SON_GUN:02d}",
            "amount": withholding["ssi_employer"],
            "description": (
                f"SGK işveren payı (5510 sayılı Kanun) — "
                f"₺{withholding['ssi_employer']/100:,.0f}"
            ),
            "urgency": "normal",
        })

    # Geçici vergi (çeyreklik) — doğru dönem son tarihleri
    if corp_tax["corporate_tax_estimate"] > 0:
        month_str = f"{month:02d}"
        if month_str in GECICI_VERGI_TAKVIMI:
            beyanname_tarihi = GECICI_VERGI_TAKVIMI[month_str]
            # Q4 geçici vergisi ertesi yılda
            gv_year = year + 1 if month == 12 else year
            gv_ay, gv_gun = beyanname_tarihi.split("-")
            calendar.append({
                "type": "Geçici Vergi",
                "due_date": f"{gv_year:04d}-{gv_ay}-{gv_gun}",
                "amount": int(corp_tax["corporate_tax_estimate"] / 4),
                "description": (
                    f"Kurumlar vergisi geçici vergi (GVK Mükerrer Madde 120) — "
                    f"₺{corp_tax['corporate_tax_estimate']/4/100:,.0f}"
                ),
                "urgency": "high",
            })

    calendar.sort(key=lambda x: x["due_date"])
    return calendar


def _tax_narrative_template(tax: dict[str, Any]) -> str:
    vat = tax["vat"]["net_vat_payable"] / 100
    corp = tax["corporate"]["corporate_tax_estimate"] / 100
    total = tax.get("total_tax_burden", 0) / 100
    n_due = len(tax.get("payment_calendar", []))
    return (
        f"Toplam vergi yükü ~{total:,.0f} TL (KDV {vat:,.0f} TL, kurumlar vergisi "
        f"tahmini {corp:,.0f} TL). {n_due} yaklaşan ödeme takvimde. Nakit planlamasında "
        "bu tarihleri dikkate alın."
    )


async def _generate_tax_narrative(
    tax: dict[str, Any], settings
) -> str:
    try:
        from app.platform.model_gateway import complete_text

        cal_text = "\n".join(
            f"- {p['type']}: {p['amount']/100:,.0f} TL — due {p['due_date']}"
            for p in tax.get("payment_calendar", [])
        )
        text = await complete_text(
            task="metric_commentary",
            system_prompt=(
                "You are a Turkish tax accountant. Summarize the tax position "
                "in 2-4 sentences. Highlight upcoming deadlines and cash flow impact. "
                "Be specific and actionable."
            ),
            prompt=(
                f"VAT payable: {tax['vat']['net_vat_payable']/100:,.0f} TL\n"
                f"Withholding tax: {tax['withholding']['income_tax_withholding']/100:,.0f} TL\n"
                f"SSI employer: {tax['withholding']['ssi_employer']/100:,.0f} TL\n"
                f"Corporate tax estimate: {tax['corporate']['corporate_tax_estimate']/100:,.0f} TL\n\n"
                f"Upcoming payments:\n{cal_text or 'None'}"
            ),
            max_tokens=512,
        )
        return text.strip()
    except Exception as exc:
        logger.debug("LLM tax narrative fallback: %s", exc)
        return _tax_narrative_template(tax)


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
        reference_month = max(dates) if dates else datetime.now(UTC).strftime("%Y-%m")

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
