"""
HR export connector — payroll / headcount CSV via URL or inline base64.

source_config:
  csv_url: str
  csv_base64: str
"""
from __future__ import annotations

import base64
import csv
import io
import logging
from typing import Any

from app.services.connectors.csv_utils import transactions_to_csv

logger = logging.getLogger(__name__)

_AMOUNT_HEADERS = ("salary", "amount", "gross_pay", "payroll", "ücret", "maas", "maaş")
_DATE_HEADERS = ("date", "payroll_date", "period", "pay_date", "start_date")
_NAME_HEADERS = ("employee", "name", "employee_name", "full_name", "çalışan")
_ID_HEADERS = ("employee_id", "id", "staff_id", "reference")


def _header_map(fieldnames: list[str] | None) -> dict[str, str]:
    return {raw.strip().lower(): raw for raw in (fieldnames or [])}


def _col(hmap: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for key in candidates:
        if key in hmap:
            return hmap[key]
    return None


def normalize_hr_payroll_csv(raw: bytes) -> bytes:
    """Map HR payroll exports onto canonical expense transactions."""
    if not raw:
        return b""
    try:
        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        hmap = _header_map(list(reader.fieldnames or []))
        if "date" in hmap and "amount" in hmap:
            return raw
        amount_col = _col(hmap, _AMOUNT_HEADERS)
        date_col = _col(hmap, _DATE_HEADERS)
        if not amount_col or not date_col:
            return raw
        name_col = _col(hmap, _NAME_HEADERS)
        id_col = _col(hmap, _ID_HEADERS)
        rows: list[dict[str, Any]] = []
        for i, rec in enumerate(reader, start=1):
            rows.append(
                {
                    "date": rec.get(date_col) or "",
                    "amount": rec.get(amount_col) or "0",
                    "description": (rec.get(name_col) if name_col else None) or f"Payroll {i}",
                    "category": "salary",   # the vocabulary's term; "payroll" is not one
                    "reference": (rec.get(id_col) if id_col else None) or f"hr-{i}",
                }
            )
        if not rows:
            return b""
        return transactions_to_csv(rows)
    except Exception as exc:
        logger.warning("HR payroll normalize failed: %s", exc)
        return raw


async def pull_hr_export_csv(cfg: dict[str, Any]) -> tuple[bytes, str]:
    raw_b64 = cfg.get("csv_base64")
    payload = b""
    if raw_b64:
        try:
            blob = raw_b64.split(",", 1)[-1] if isinstance(raw_b64, str) else raw_b64
            payload = base64.b64decode(blob)
        except Exception as exc:
            logger.warning("HR base64 decode failed: %s", exc)
            return b"", ""
    else:
        url = cfg.get("csv_url")
        if not url:
            logger.debug("HR export pull skipped: no csv_url or csv_base64")
            return b"", ""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(str(url))
                resp.raise_for_status()
                payload = resp.content
        except Exception as exc:
            logger.warning("HR csv_url fetch failed: %s", exc)
            return b"", ""

    return normalize_hr_payroll_csv(payload), "hr_export.csv"
