"""Paraşüt ERP connector adapter for the official Connector platform.

Implements the Connector protocol (ports & adapters), enabling the runner
to query health and fetch normalized transactions with cross-source deduplication.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from app.connectors.base import (
    CanonicalRow,
    Connector,
    ConnectorAuthError,
    ConnectorHealth,
    ConnectorPayload,
    Watermark,
)
from app.core.invoice_identity import canonical_invoice_id

logger = logging.getLogger(__name__)


class ParasutConnectorAdapter(Connector):
    name: ClassVar[str] = "parasut"
    domain: ClassVar[str] = "finance"
    kernel_role: ClassVar[str | None] = "cfo"

    async def health(
        self, *, config: Mapping[str, Any], secret: Mapping[str, Any]
    ) -> ConnectorHealth:
        token = (secret or {}).get("access_token")
        if not token:
            return ConnectorHealth(ok=False, detail="Paraşüt erişim anahtarı (access token) eksik")
        company_id = (config or {}).get("company_id")
        if not company_id:
            return ConnectorHealth(ok=False, detail="Paraşüt firma seçilmedi (company_id eksik)")
        return ConnectorHealth(ok=True, detail="Paraşüt bağlantısı aktif", account=str(company_id))

    async def fetch(
        self,
        *,
        org_id: str,
        config: Mapping[str, Any],
        secret: Mapping[str, Any],
        since: Watermark,
    ) -> ConnectorPayload:
        token = (secret or {}).get("access_token")
        if not token:
            raise ConnectorAuthError("parasut: missing access token")

        company_id = str((config or {}).get("company_id") or "")
        since_dt = since.since or (datetime.now(UTC) - timedelta(days=90))

        # In offline/mock test environments or when transport is intercepted,
        # we pull invoices using the existing parasut_connector helpers.
        import httpx

        from app.services.erp.parasut_connector import PARASUT_API_BASE, _transport

        rows: list[CanonicalRow] = []
        warnings: list[str] = []

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.api+json",
        }

        async with httpx.AsyncClient(transport=_transport, timeout=30.0) as client:
            for endpoint, tip in (("sales_invoices", "income"), ("purchase_bills", "expense")):
                try:
                    resp = await client.get(
                        f"{PARASUT_API_BASE}/{company_id}/{endpoint}",
                        headers=headers,
                        params={"sort": "-issue_date", "page[size]": 25},
                    )
                    if resp.status_code >= 400:
                        warnings.append(f"Paraşüt {endpoint} isteği {resp.status_code} döndürdü")
                        continue
                    data = resp.json().get("data") or []
                    for item in data:
                        attrs = item.get("attributes") or {}
                        issue_str = attrs.get("issue_date") or attrs.get("date")
                        if not issue_str:
                            continue
                        issue_dt = datetime.fromisoformat(str(issue_str)[:10]).replace(tzinfo=UTC)
                        if issue_dt < since_dt:
                            continue

                        raw_amount = attrs.get("gross_total") or attrs.get("net_total") or 0
                        try:
                            amount_cents = round(abs(float(raw_amount)) * 100)
                        except (TypeError, ValueError):
                            amount_cents = 0
                        if amount_cents == 0:
                            continue

                        inv_no = attrs.get("invoice_no") or attrs.get("invoice_number")
                        desc = attrs.get("description") or (
                            "Satış Faturası" if tip == "income" else "Alış Faturası"
                        )
                        doc_id = canonical_invoice_id(None, str(inv_no) if inv_no else None, desc)

                        source_record_id = (
                            f"doc:{doc_id}" if doc_id else f"parasut:{item.get('id')}"
                        )

                        rows.append(
                            CanonicalRow(
                                source_record_id=source_record_id,
                                signal_type="invoice",
                                occurred_at=issue_dt,
                                actor=attrs.get("customer_name") or attrs.get("supplier_name"),
                                title=f"{desc}{f' #{inv_no}' if inv_no else ''}",
                                magnitude=amount_cents,
                                attributes={
                                    "type": tip,
                                    "currency": attrs.get("currency") or "TRY",
                                    "invoice_no": inv_no,
                                    "document_id": doc_id,
                                    "source": "parasut",
                                },
                            )
                        )
                except Exception as exc:
                    logger.warning("Paraşüt fetch error on %s: %s", endpoint, exc)
                    warnings.append(str(exc))

        return ConnectorPayload(
            rows=rows,
            next_watermark=Watermark(since=datetime.now(UTC)),
            warnings=warnings,
        )
