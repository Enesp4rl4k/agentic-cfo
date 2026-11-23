"""Cash runway: how long the money in the bank lasts at the pace the documents show.

A runway is a balance divided by a burn. Both must be the company's own:

- the balance is the one a bank statement proves (`app.services.bank_balance`; the same
  source and the same staleness limit the cash radar uses, nothing computed a second time);
- the burn is the average monthly net cash movement of the latest `RUNWAY_MIN_MONTHS`
  COMPLETE, consecutive months: a month counts only when the statement(s) cover it from its
  first day to its last (`app.services.coverage`). A month the data only starts or ends in is
  named and left out; the burn says which months it used and what each came to.

Missing either is said as missing: there is no runway then, not a runway of one month.
Growth rates the forecast's scenarios assume are not measurements and never reach here.
"""
from __future__ import annotations

import statistics
from datetime import UTC, date, datetime
from typing import Any

from app.config import get_settings
from app.core.currency_totals import fmt_money
from app.services.bank_balance import (
    aged_basis,
    assess,
    balance_age,
    closing_balance,
    latest_balance,
)
from app.services.coverage import gaps, usable_months

RUNWAY_MIN_MONTHS = 3  # months of cash movement the burn average needs (the forecast's baseline window)
RUNWAY_CRITICAL_MONTHS = 3
RUNWAY_WARNING_MONTHS = 6
RUNWAY_LONG_MONTHS = 36  # beyond this the figure is stated as "longer than", not as a number

COMPUTED = "computed"
NOT_BURNING = "not_burning"
NO_BALANCE = "no_balance"
INSUFFICIENT_HISTORY = "insufficient_history"
NOT_CASH_BASIS = "not_cash_basis"
COVERAGE_UNKNOWN = "coverage_unknown"

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
    rows = list(state.get("transactions") or [])
    proof = state.get("balance_proof") or assess(rows, state.get("ingest_counts"))
    own = (state.get("statement_closing_balance") or closing_balance(rows)) if proof["basis"] else None
    if own:
        path = str(state.get("file_path") or "")
        own = {
            **own, "filename": path.replace("\\", "/").rsplit("/", 1)[-1] or None,
            "basis": proof["basis"], "basis_note": proof.get("reason"),
        }
    chosen = latest_balance(own, state.get("opening_cash"))
    if chosen is None:
        return None
    today = anchor or datetime.now(UTC).date()
    limit = get_settings().radar_balance_stale_after_days
    age, stale = balance_age(str(chosen["date"]), today, limit)
    basis, basis_note = aged_basis(chosen.get("basis"), chosen.get("basis_note"), age, str(chosen["date"])[:10])
    return {
        "balance_cents": int(chosen["balance_cents"]),
        "as_of": str(chosen["date"])[:10],
        "age_days": age,
        "stale": stale,
        "stale_after_days": limit,
        "filename": chosen.get("filename"),
        # "known", or "assumed" when the proof is thin (`bank_balance.assess`): said wherever it is shown.
        "basis": basis,
        "basis_note": basis_note,
        "accounts": list(chosen.get("accounts") or []),
        "excluded": list(chosen.get("excluded") or []),
    }


def _balance_notes(opening: dict[str, Any], money: Any) -> str:
    """What the balance is made of when it is not one plain statement: accounts, an old account, a thin
    proof, a statement left out. Each says its own date and reason; nothing is merged silently."""
    parts: list[str] = []
    accounts = opening.get("accounts") or []
    if len(accounts) > 1:
        listed = ", ".join(f"{a['name'] or 'adsız ekstre'} {_date_tr(a['as_of'])} {money(a['balance_cents'])}" for a in accounts)
        parts.append(f"Bakiye {len(accounts)} hesabın son ekstre bakiyelerinin toplamıdır ({listed})")
    for a in accounts:
        if a.get("lagging") and len(accounts) > 1:
            parts.append(f"{a['name'] or 'adsız ekstre'} bakiyesi {_date_tr(a['as_of'])} tarihli, diğerlerinden {a['behind_days']} gün eski")
    if opening.get("basis") == "assumed":
        notes = {a["basis_note"] for a in accounts if a.get("basis_note")} | ({opening["basis_note"]} if opening.get("basis_note") else set())
        why = "; ".join(sorted(notes or {"zayıf kanıt"}))
        parts.append(f"Bakiye zayıf kanıta dayanıyor ({why}), varsayım olarak alındı")
    if opening.get("identity_note"):
        parts.append(str(opening["identity_note"]))
    parts.extend(_excluded_note(opening.get("excluded") or []))
    return "".join(f" {p}." for p in parts)


def _excluded_note(excluded: list[dict[str, Any]]) -> list[str]:
    return [
        f"{e.get('filename') or 'adsız ekstre'} ekstresinin bakiyesi doğrulanamadığı için dışarıda bırakıldı ({e['reason']})"
        for e in excluded
    ]


def _block(status: str, message: str, opening: dict[str, Any] | None, **extra: Any) -> dict[str, Any]:
    return {
        "status": status,
        "opening_cash_cents": opening["balance_cents"] if opening else None,
        "as_of": opening["as_of"] if opening else None,
        "age_days": opening["age_days"] if opening else None,
        "stale": opening["stale"] if opening else None,
        "source_filename": opening["filename"] if opening else None,
        "balance_basis": (opening.get("basis") or "known") if opening else None,
        "identity_uncertain": bool(opening.get("uncertain")) if opening else False,
        "identity_note": opening.get("identity_note") if opening else None,
        "accounts": [dict(a) for a in opening.get("accounts") or []] if opening else [],
        "months_needed": RUNWAY_MIN_MONTHS,
        "months_used": 0,
        "months": [],
        # How firmly the months are known: "known" (stated period, joined statements, or edges
        # reaching the month's first and last day) or "assumed" (an edge within the tolerance).
        "basis": None,
        "assumptions": [],
        "avg_monthly_net_cents": None,
        "runway_months": None,
        "beyond_horizon": False,
        "level": None,
        "message": message,
        **extra,
    }


def _month_name(month: str, with_year: bool = False) -> str:
    name = _MONTHS_TR[int(month[5:7]) - 1]
    return f"{name} {month[:4]}" if with_year else name


def _span(first: str, last: str) -> str:
    return _month_name(first) if first == last else f"{_month_name(first)}–{_month_name(last)}"


def _notes(series: list[dict[str, Any]], window: list[dict[str, Any]], opening: dict[str, Any]) -> str:
    """What the burn left out, said plainly: incomplete months, and the balance's date."""
    incomplete = [m for m in series if m.get("complete") is False and not m.get("short")]
    parts = []
    for m in incomplete:
        if m.get("missing_statement"):
            parts.append(f"{_month_name(m['month'])} için {m['missing_statement']} ekstresi eksik; hesaba katılmadı")
            continue
        days = m.get("covered")
        span = f"yalnızca {days[0]}–{days[1]} arası" if days else "yalnızca kısmen"
        later = not window or m["month"] > window[-1]["month"]
        tail = " (hareketleri bakiyeye zaten yansımıştır)" if later else ""
        parts.append(f"{_month_name(m['month'])} {span} var; hesaba katılmadı{tail}")
    if window and not any(m["month"] > window[-1]["month"] for m in incomplete):
        end_of_window = f"{window[-1]['month']}-31"
        if opening["as_of"] > end_of_window:
            parts.append(
                f"Bakiye {_date_tr(opening['as_of'])} tarihli, son tam ay {_month_name(window[-1]['month'])}; "
                "aradaki hareketler bakiyeye yansımıştır ama aylık çıkış hesabına girmemiştir"
            )
    return "".join(f" {p}." for p in parts) + _mismatch_note(series)


def _mismatch_note(series: list[dict[str, Any]]) -> str:
    """Where the file's header and its rows disagree: said, and the header was not trusted."""
    seen: list[tuple[str, str, str]] = []
    for m in series:
        for x in m.get("header_mismatch") or []:
            key = (x["edge"], x["stated"], x["actual"])
            if key not in seen:
                seen.append(key)
    return "".join(
        f" Ekstre başlığındaki {'başlangıç' if edge == 'start' else 'bitiş'} tarihi {_date_tr(stated)}, "
        f"satırların {'ilk' if edge == 'start' else 'son'} tarihi {_date_tr(actual)}: başlığa güvenilmedi."
        for edge, stated, actual in seen
    )


def _assumed_text(edges: list[dict[str, Any]]) -> str:
    parts = [
        f"{_month_name(e['month'])} ayının {'ilk' if e['edge'] == 'start' else 'son'} {e['days']} günü"
        for e in edges
    ]
    return f" {' ve '.join(parts)} için işlem yok; ay tam sayıldı (varsayım)." if parts else ""


def _assumed_note(window: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """The edges counted as complete on the tolerance, said as the assumption they are."""
    edges = [{"month": m["month"], **a} for m in window for a in m.get("assumed") or []]
    return _assumed_text(edges), edges


def _short_note(series: list[dict[str, Any]]) -> str:
    """Which account (statement) is short, when a month is incomplete because of another bank's file."""
    by_name: dict[str, dict[str, Any]] = {}
    for m in series:
        if m.get("complete") is False:
            for a in m.get("short") or []:
                by_name.setdefault(a["name"], {**a, "months": []})["months"].append(m["month"])
    return "".join(
        f" {name} ekstresi {_date_tr(v['start'])} – {_date_tr(v['end'])} arasını kapsıyor; "
        f"{', '.join(_month_name(x) for x in v['months'])} bu hesap için eksik, hesaba katılmadı."
        for name, v in by_name.items()
    )


def _one_off(window: list[dict[str, Any]], burn_total: int, currency: str | None) -> str:
    """A plain note when one outflow is more than half of the window's net outflow; no adjustment."""
    tops = [m["top_out"] for m in window if m.get("top_out")]
    if not tops or burn_total <= 0:
        return ""
    top = max(tops, key=lambda t: t["amount_cents"])
    if top["amount_cents"] * 2 <= burn_total:
        return ""
    what = f" ({top['description']})" if top.get("description") else ""
    return (
        f" Not: {_date_tr(top['date'])} tarihli {fmt_money(top['amount_cents'], currency)} tutarındaki "
        f"çıkış{what}, bu aylardaki net çıkışın yarısından fazlası; tek seferlik olabilir, olduğu gibi hesaba katıldı."
    )


def compute_runway(
    opening: dict[str, Any] | None, cashflow: dict[str, Any], currency: str | None = None,
    unproven: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The runway of this company, or the reason there is none.

    `status`: computed | not_burning | no_balance | insufficient_history | not_cash_basis |
    coverage_unknown. The burn is the average net of the latest `RUNWAY_MIN_MONTHS` COMPLETE,
    consecutive months (`app.services.coverage`); the months and their totals are in the block
    and the message. `currency` is the one the figures are written in (none known: bare numbers).
    `unproven` names statements whose balance could not be proven, said when there is no balance.
    """
    def money(cents: int) -> str:
        return fmt_money(cents, currency)

    if opening is None:
        return _block(
            NO_BALANCE,
            "Kasa bakiyesi bilinmiyor — nakit pisti hesaplanamadı. "
            "Satır bakiyeleri birbirini tutan bir banka ekstresi yüklenince hesaplanır."
            + "".join(f" {x}." for x in _excluded_note(unproven or [])),
            None,
        )
    basis = f"{_date_tr(opening['as_of'])} ekstresindeki bakiyeye göre kasa {money(opening['balance_cents'])}"
    stale_note = (
        f" Bu bakiye {opening['age_days']} gün önceki ekstreden; güncel olmayabilir."
        if opening["stale"] else ""
    ) + _balance_notes(opening, money)
    if cashflow.get("esas") == "tahakkuk":
        return _block(
            NOT_CASH_BASIS,
            f"{basis}. Aylık hareketler muhasebe kayıtlarından (tahakkuk) türetildi, gerçek nakit "
            f"çıkışı değil: nakit pisti hesaplanmadı.{stale_note}",
            opening,
        )
    series = list(cashflow.get("monthly_series") or [])
    if series and all(m.get("complete") is None for m in series):
        return _block(
            COVERAGE_UNKNOWN,
            f"{basis}. Ekstrenin hangi tarihleri kapsadığı bilinmediği için hangi ayların tam olduğu "
            f"söylenemiyor: nakit pisti hesaplanmadı.{stale_note}",
            opening,
        )
    window = usable_months(series)[-RUNWAY_MIN_MONTHS:]
    months = [{"month": m["month"], "net_cents": int(m["net"])} for m in window]
    notes = _notes(series, window, opening) + _short_note(series)
    if len(window) < RUNWAY_MIN_MONTHS:
        gap = "".join(f" {_span(a, b)} verisi yok." for a, b in gaps(series))
        return _block(
            INSUFFICIENT_HISTORY,
            f"{basis}. Üst üste {len(window)} tam ay var; aylık nakit çıkışı için en az "
            f"{RUNWAY_MIN_MONTHS} tam ay gerekir: nakit pisti hesaplanmadı.{gap}{notes}{stale_note}",
            opening,
            months_used=len(window),
            months=months,
        )
    nets = [int(m["net"]) for m in window]
    avg_net = int(statistics.mean(nets))
    assumed_text, assumptions = _assumed_note(window)
    notes = assumed_text + notes
    basis_tag = "assumed" if assumptions or opening.get("basis") == "assumed" else "known"
    with_year = len({m["month"][:4] for m in window}) > 1
    listing = ", ".join(f"{_month_name(m['month'], with_year)} {money(int(m['net']))}" for m in window)
    if avg_net >= 0:
        return _block(
            NOT_BURNING,
            f"{basis}. {listing} → ortalama aylık net nakit akışı {money(avg_net)} (pozitif): nakit "
            f"azalmıyor, nakit pisti hesaplanmadı.{notes}{stale_note}",
            opening,
            months_used=len(window),
            months=months,
            basis=basis_tag,
            assumptions=assumptions,
            avg_monthly_net_cents=avg_net,
        )
    balance = opening["balance_cents"]
    runway = balance / -avg_net if balance > 0 else 0.0
    beyond = runway > RUNWAY_LONG_MONTHS
    level = (
        "critical" if runway <= RUNWAY_CRITICAL_MONTHS
        else "warning" if runway <= RUNWAY_WARNING_MONTHS
        else None
    )
    if opening.get("uncertain") and level == "critical":
        level = "warning"  # the cash is the newest of statements that may be one account: not measured
    if opening.get("basis") == "assumed" and level == "critical":
        level = "warning"  # only a measured, current balance may raise a critical alert (stale and thin proofs are assumed)
    if balance <= 0:
        verdict = "Kasa bakiyesi sıfırın altında: nakit bitmiş."
    elif beyond:
        verdict = f"Bu hızla nakit {RUNWAY_LONG_MONTHS} aydan uzun yeter."
    else:
        verdict = "Bu hızla nakit yaklaşık " + f"{runway:.1f}".replace(".", ",") + " ay yeter."
    return _block(
        COMPUTED,
        f"{basis}; {listing} → ortalama aylık net nakit çıkışı {money(-avg_net)}. {verdict}"
        f"{_one_off(window, -sum(nets), currency)}{notes}{stale_note}",
        opening,
        months_used=len(window),
        months=months,
        basis=basis_tag,
        assumptions=assumptions,
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
    if status in (NO_BALANCE, INSUFFICIENT_HISTORY, NOT_CASH_BASIS, COVERAGE_UNKNOWN):
        return {"level": "info", "message": runway["message"], "basis": "runway"}
    return None


def can_project(runway: dict[str, Any]) -> bool:
    """Whether scenario runways may be read off a balance: it is known and the burn is measured."""
    return runway["status"] in (COMPUTED, NOT_BURNING)


def runway_line(block: dict[str, Any]) -> str:
    """The runway in one short passage for the Monday briefing: the same block, worded for reading aloud.

    A measured runway gives its months, the balance with its date, the months the burn was read from and
    any assumption in plain words; a critical one opens with "KRİTİK". No runway gives the reason and no
    number ("Kasa bakiyesi bilinmiyor"). Never a figure that is not in the block.
    """
    status = block["status"]
    cur = block.get("currency")
    if status == NO_BALANCE:
        return str(block["message"])
    if status == INSUFFICIENT_HISTORY:
        return (
            f"Nakit pisti hesaplanamadı: üst üste {block['months_used']} tam ay var, "
            f"en az {block['months_needed']} gerekir."
        )
    if status in (NOT_CASH_BASIS, COVERAGE_UNKNOWN):
        why = "aylık hareketler gerçek nakit değil, muhasebe kaydı" if status == NOT_CASH_BASIS else "ekstrenin kapsadığı tarihler bilinmiyor"
        return f"Nakit pisti hesaplanamadı: {why}."
    months = block["months"]
    with_year = len({m["month"][:4] for m in months}) > 1
    span = f"{_month_name(months[0]['month'], with_year)}–{_month_name(months[-1]['month'], with_year)}"
    avg = block["avg_monthly_net_cents"]
    where = f"{_date_tr(block['as_of'])} ekstresindeki kasa {fmt_money(block['opening_cash_cents'], cur)}"
    stale = f" Bu bakiye {block['age_days']} gün önceki ekstreden; güncel olmayabilir." if block.get("stale") else ""
    if status == NOT_BURNING:
        return (
            f"Nakit azalmıyor: son {len(months)} tam ayın ({span}) ortalama net nakit akışı "
            f"{fmt_money(avg, cur)} (pozitif); nakit pisti hesaplanmadı. {where}.{stale}"
        )
    if block["beyond_horizon"]:
        head = f"Nakit pisti {RUNWAY_LONG_MONTHS} aydan uzun"
    elif not block["opening_cash_cents"] or block["opening_cash_cents"] <= 0:
        head = "Kasa bakiyesi sıfırın altında: nakit bitmiş"
    else:
        head = "Nakit pisti yaklaşık " + f"{block['runway_months']:.1f}".replace(".", ",") + " ay"
    level = {"critical": "KRİTİK: ", "warning": "Uyarı: "}.get(block.get("level") or "", "")
    out = (
        f"{level}{head} ({where}; son {len(months)} tam ayın ({span}) ortalama net çıkışı "
        f"{fmt_money(-avg, cur)}/ay)."
    )
    caveats = _assumed_text(block.get("assumptions") or [])
    if block.get("identity_note"):
        caveats += f" {block['identity_note']}."
    if block.get("balance_basis") == "assumed" and not block.get("identity_note"):
        why = "; ".join(sorted({a["basis_note"] for a in block.get("accounts") or [] if a.get("basis_note")})) or "zayıf kanıt"
        caveats += f" Bakiye zayıf kanıta dayanıyor ({why}), varsayım."
    return out + (f" Varsayım:{caveats}" if block.get("basis") == "assumed" and caveats else "") + stale
