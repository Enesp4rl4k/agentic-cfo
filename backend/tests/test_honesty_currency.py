"""Faz 1.4 honesty gate (U1): org data never renders with a hardcoded `$`.

TRY org'larında backend anlatı/expanter metinleri `$` basıyordu (33 site,
2026-10-14 süpürmesiyle ₺'ye çevrildi). Bu kapı, geri kaymayı testle kilitler.

Allowlist (gerçekten USD veya para birimi değil):
- core/financial.py      → format_currency_usd (bilinçli USD formatter)
- platform/model_gateway.py, platform/llm_router.py → LLM API harcaması/model
  fiyatı gerçekten USD cinsinden faturalanır
- api/stream.py, api/ws_alerts.py → gömülü JS template literal'ları (`${...}`)
"""

from __future__ import annotations

import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"

ALLOWLIST_FILES = {
    "api/stream.py",
    "api/ws_alerts.py",
    "core/financial.py",
    "platform/model_gateway.py",
    "services/llm_router.py",
}

# `$` + rakam (`$1M` yorum, `$1` SQL parametresi) veya `${` (f-string para, template).
DOLLAR_CURRENCY = re.compile(r"\$\d|\$\{")

# SQL positional parametre zinciri: `$1${suffix}` (pg_advisory lock key).
SQL_PARAM_LINE = re.compile(r"\$\d+\$\{[a-z_]+\}")

# `$1, $2, ...` placeholders — para değil, raw SQL (asyncpg).
SQL_PLACEHOLDER = re.compile(r"\$\d+\b")
SQL_KEYWORDS = re.compile(
    r"\b(WHERE|VALUES|ORDER BY|LIMIT|SELECT|INSERT|UPDATE|DELETE|AND|OR)\b"
)


def test_no_hardcoded_dollar_currency_in_app() -> None:
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        rel = path.relative_to(APP_DIR).as_posix()
        if rel in ALLOWLIST_FILES:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "$" not in line:
                continue
            if SQL_PARAM_LINE.search(line):
                continue
            if SQL_PLACEHOLDER.search(line) and SQL_KEYWORDS.search(line):
                continue
            if DOLLAR_CURRENCY.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:90]}")
    assert not offenders, (
        "Hardcoded `$` currency in backend app/ — org verisi ₺ "
        "(format_currency_try / inline ₺ kullan):\n" + "\n".join(offenders)
    )
