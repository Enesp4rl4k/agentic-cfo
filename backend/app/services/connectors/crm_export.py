"""
CRM export connector — HubSpot/Salesforce CSV via URL or inline base64.

source_config:
  csv_url: str       — fetch CSV over HTTP(S)
  csv_base64: str    — inline CSV (manual schedule / staging)
"""
from __future__ import annotations

import base64
import csv
import io
import logging
from typing import Any

from app.services.connectors.csv_utils import transactions_to_csv

logger = logging.getLogger(__name__)

_WON_STAGES = {
    "closedwon",
    "closed won",
    "closed-won",
    "won",
    "closed",
    "kazanıldı",
    "kazanildi",
    "satış kazanıldı",
}

_AMOUNT_HEADERS = ("amount", "deal amount", "amount_usd", "deal_value", "value", "tutar")
_DATE_HEADERS = ("close date", "closedate", "close_date", "date", "createdate", "created_at")
_NAME_HEADERS = ("deal name", "opportunity name", "name", "deal_name", "title", "açıklama", "description")
_STAGE_HEADERS = ("deal stage", "stagename", "stage", "status", "dealstage")
_ID_HEADERS = ("deal id", "id", "opportunity id", "record_id", "reference")


def _header_map(fieldnames: list[str] | None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for raw in fieldnames or []:
        mapping[raw.strip().lower()] = raw
    return mapping


def _col(hmap: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for key in candidates:
        if key in hmap:
            return hmap[key]
    return None


def _is_won(stage: str) -> bool:
    token = (stage or "").strip().lower()
    if not token:
        return True
    compact = token.replace("_", " ")
    return compact in _WON_STAGES or token.replace(" ", "") in {s.replace(" ", "") for s in _WON_STAGES}


def normalize_crm_deals_csv(raw: bytes) -> bytes:
    """Map HubSpot/Salesforce-style deal CSVs onto canonical transaction columns."""
    if not raw:
        return b""
    try:
        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        hmap = _header_map(list(reader.fieldnames or []))
        # Already canonical
        if "date" in hmap and "amount" in hmap:
            return raw
        amount_col = _col(hmap, _AMOUNT_HEADERS)
        date_col = _col(hmap, _DATE_HEADERS)
        if not amount_col or not date_col:
            return raw
        name_col = _col(hmap, _NAME_HEADERS)
        stage_col = _col(hmap, _STAGE_HEADERS)
        id_col = _col(hmap, _ID_HEADERS)
        rows: list[dict[str, Any]] = []
        for i, rec in enumerate(reader, start=1):
            if stage_col and not _is_won(str(rec.get(stage_col) or "")):
                continue
            amount_raw = rec.get(amount_col) or "0"
            rows.append(
                {
                    "date": rec.get(date_col) or "",
                    "amount": amount_raw,
                    "description": (rec.get(name_col) if name_col else None) or f"CRM deal {i}",
                    "category": "revenue",
                    "reference": (rec.get(id_col) if id_col else None) or f"crm-{i}",
                }
            )
        if not rows:
            return b""
        return transactions_to_csv(rows)
    except Exception as exc:
        logger.warning("CRM deal normalize failed: %s", exc)
        return raw


async def pull_crm_export_csv(cfg: dict[str, Any]) -> tuple[bytes, str]:
    """Return (csv_bytes, filename) from CRM export configuration."""
    raw_b64 = cfg.get("csv_base64")
    payload = b""
    if raw_b64:
        try:
            blob = raw_b64.split(",", 1)[-1] if isinstance(raw_b64, str) else raw_b64
            payload = base64.b64decode(blob)
        except Exception as exc:
            logger.warning("CRM base64 decode failed: %s", exc)
            return b"", ""
    else:
        url = cfg.get("csv_url")
        if url:
            try:
                import httpx

                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(str(url))
                    resp.raise_for_status()
                    payload = resp.content
            except Exception as exc:
                logger.warning("CRM csv_url fetch failed: %s", exc)
                return b"", ""
        else:
            logger.debug("CRM export pull skipped: no csv_url or csv_base64 in source_config")
            return b"", ""

    return normalize_crm_deals_csv(payload), "crm_export.csv"
