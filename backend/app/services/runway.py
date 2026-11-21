"""Cash runway: how long the money in the bank lasts at the pace the documents show.

A runway is a balance divided by a burn. Both must be the company's own:

- the balance is the one a bank statement proves (`app.services.bank_balance`; the same
  source and the same staleness limit the cash radar uses, nothing computed a second time);
- the burn is the average monthly net cash movement of the months actually present, at
  least `RUNWAY_MIN_MONTHS` of them.

Missing either is said as missing: there is no runway then, not a runway of one month.
Growth rates the forecast's scenarios assume are not measurements and never reach here.
"""
from __future__ import annotations

import statistics
from datetime import UTC, date, datetime
from typing import Any

from app.config import get_settings
from app.core.currency_totals import fmt_money
from app.services.bank_balance import balance_age, closing_balance, latest_balance

RUNWAY_MIN_MONTHS = 3  # months of cash movement the burn average needs (the forecast's baseline window)
RUNWAY_CRITICAL_MONTHS = 3
RUNWAY_WARNING_MONTHS = 6
RUNWAY_LONG_MONTHS = 36  # beyond this the figure is stated as "longer than", not as a number

COMPUTED = "computed"
NOT_BURNING = "not_burning"
NO_BALANCE = "no_balance"
INSUFFICIENT_HISTORY = "insufficient_history"
NOT_CASH_BASIS = "not_cash_basis"

_MONTHS_TR = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)


def _date_tr(iso: str) -> str:
    d = date.fromisoformat(str(iso)[:10])
    return f"{d.day} {_MONTHS_TR[d.month - 1]} {d.year}"


def opening_cash_for(state: dict[str, Any], anchor: date | None = None) -> dict[str, Any] | None:
    """The proven balance this run may start from, with its age, or None when none is proven.

    The newest of: the balance this run's own statement proves, and the one the company's
    completed statements prove (loaded by the caller, as the radar reads it).
    """
    own = state.get("statement_closing_balance") or closing_balance(list(state.get("transactions") or []))
    if own:
        path = str(state.get("file_path") or "")
        own = {**own, "filename": path.replace("\\", "/").rsplit("/", 1)[-1] or None}
    chosen = latest_balance(own, state.get("opening_cash"))
    if chosen is None:
        return None
    today = anchor or datetime.now(UTC).date()
    limit = get_settings().radar_balance_stale_after_days
    age, stale = balance_age(str(chosen["date"]), today, limit)
    return {
        "balance_cents": int(chosen["balance_cents"]),
        "as_of": str(chosen["date"])[:10],
        "age_days": age,
        "stale": stale,
        "stale_after_days": limit,
        "filename": chosen.get("filename"),
    }


def _block(status: str, message: str, opening: dict[str, Any] | None, **extra: Any) -> dict[str, Any]:
    return {
        "status": status,
        "opening_cash_cents": opening["balance_cents"] if opening else None,
        "as_of": opening["as_of"] if opening else None,
        "age_days": opening["age_days"] if opening else None,
        "stale": opening["stale"] if opening else None,
        "source_filename": opening["filename"] if opening else None,
        "months_needed": RUNWAY_MIN_MONTHS,
        "months_used": 0,
        "avg_monthly_net_cents": None,
        "runway_months": None,
        "beyond_horizon": False,
        "level": None,
        "message": message,
        **extra,
    }


def compute_runway(
    opening: dict[str, Any] | None, cashflow: dict[str, Any], currency: str | None = None
) -> dict[str, Any]:
    """The runway of this company, or the reason there is none.

    `status`: computed | not_burning | no_balance | insufficient_history | not_cash_basis.
    `currency` is the company's currency the figures are written in (none known: bare numbers).
    """
    def _lira(cents: int) -> str:
        return fmt_money(cents, currency)

    if opening is None:
        return _block(
            NO_BALANCE,
            "Kasa bakiyesi bilinmiyor — nakit pisti hesaplanamadı. "
            "Satır bakiyeleri birbirini tutan bir banka ekstresi yüklenince hesaplanır.",
            None,
        )
    basis = f"{_date_tr(opening['as_of'])} ekstresindeki bakiyeye göre kasa {_lira(opening['balance_cents'])}"
    stale_note = (
        f" Bu bakiye {opening['age_days']} gün önceki ekstreden; güncel olmayabilir."
        if opening["stale"] else ""
    )
    if cashflow.get("esas") == "tahakkuk":
        return _block(
            NOT_CASH_BASIS,
            f"{basis}. Aylık hareketler muhasebe kayıtlarından (tahakkuk) türetildi, gerçek nakit "
            f"çıkışı değil: nakit pisti hesaplanmadı.{stale_note}",
            opening,
        )
    recent = list(cashflow.get("monthly_series") or [])[-RUNWAY_MIN_MONTHS:]
    if len(recent) < RUNWAY_MIN_MONTHS:
        return _block(
            INSUFFICIENT_HISTORY,
            f"{basis}. Aylık nakit çıkışı için {len(recent)} aylık veri var; en az "
            f"{RUNWAY_MIN_MONTHS} ay gerekir: nakit pisti hesaplanmadı.{stale_note}",
            opening,
            months_used=len(recent),
        )
    avg_net = int(statistics.mean(int(m["net"]) for m in recent))
    if avg_net >= 0:
        return _block(
            NOT_BURNING,
            f"{basis}. Son {len(recent)} ayda ortalama aylık net nakit akışı {_lira(avg_net)} "
            f"(pozitif): nakit azalmıyor, nakit pisti hesaplanmadı.{stale_note}",
            opening,
            months_used=len(recent),
            avg_monthly_net_cents=avg_net,
        )
    runway = max(0.0, opening["balance_cents"] / -avg_net)
    beyond = runway > RUNWAY_LONG_MONTHS
    level = (
        "critical" if runway <= RUNWAY_CRITICAL_MONTHS
        else "warning" if runway <= RUNWAY_WARNING_MONTHS
        else None
    )
    lasts = (
        f"{RUNWAY_LONG_MONTHS} aydan uzun" if beyond
        else "bitmiş (bakiye sıfırın altında)" if opening["balance_cents"] <= 0
        else f"yaklaşık {runway:.1f} ay".replace(".", ",")
    )
    return _block(
        COMPUTED,
        f"{basis}; son {len(recent)} ayın ortalama aylık net nakit çıkışı {_lira(-avg_net)}. "
        f"Bu hızla nakit {lasts} yeter.{stale_note}",
        opening,
        months_used=len(recent),
        avg_monthly_net_cents=avg_net,
        # Past the long horizon it is no figure: "longer than 36 months" is in the message.
        runway_months=None if beyond else round(runway, 1),
        beyond_horizon=beyond,
        level=level,
    )


def runway_alert(runway: dict[str, Any]) -> dict[str, str] | None:
    """What the runway says as an alert: severe only when both balance and burn are measured."""
    status = runway["status"]
    if status == COMPUTED and runway["level"]:
        return {"level": runway["level"], "message": runway["message"], "basis": "runway"}
    if status in (NO_BALANCE, INSUFFICIENT_HISTORY, NOT_CASH_BASIS):
        return {"level": "info", "message": runway["message"], "basis": "runway"}
    return None


def can_project(runway: dict[str, Any]) -> bool:
    """Whether scenario runways may be read off a balance: it is known and the burn is measured."""
    return runway["status"] in (COMPUTED, NOT_BURNING)
