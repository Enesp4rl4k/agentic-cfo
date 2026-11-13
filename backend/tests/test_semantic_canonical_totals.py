"""G4 — the semantic summary must total every canonical row, not the first 5,000.

`_load_canonical` used to `limit(5000)` with no ordering, so a ledger past that
size silently dropped arbitrary rows: inflow/outflow came out wrong and the
mismatch against the CFO figures raised a false contradiction.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models.canonical_transaction import CanonicalTransaction
from app.services.semantic.rebuild import _load_canonical
from tests.api_helpers import bellek_istemcisi

DATE = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
ROWS = 6000  # past the old 5,000 cut


def _row(org_id: str, i: int, direction: str, amount: int, confidence: int = 90):
    return CanonicalTransaction(
        org_id=org_id,
        source_type="bulk",
        source_record_id=f"r-{i}",
        transaction_date=DATE,
        amount_cents=amount,
        currency="TRY",
        direction=direction,
        confidence=confidence,
    )


@pytest.mark.asyncio
async def test_totals_cover_rows_past_5000():
    async with bellek_istemcisi() as client:
        org_id = "org-g4-bulk"
        async with client._maker() as session:
            session.add_all(
                _row(org_id, i, "inflow" if i % 2 == 0 else "outflow", 100 + (i % 7))
                for i in range(ROWS)
            )
            await session.commit()

            totals, quality = await _load_canonical(org_id, session)

        inflow = sum(100 + (i % 7) for i in range(ROWS) if i % 2 == 0)
        outflow = sum(100 + (i % 7) for i in range(ROWS) if i % 2 == 1)
        assert totals.count == ROWS
        assert totals.inflow_cents == inflow
        assert totals.outflow_cents == outflow
        assert quality == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_totals_use_absolute_amounts_and_skip_document_basis():
    async with bellek_istemcisi() as client:
        org_id = "org-g4-abs"
        async with client._maker() as session:
            session.add(_row(org_id, 1, "income", -500))
            session.add(_row(org_id, 2, "expense", -300))
            doc = _row(org_id, 3, "income", 9_999)
            doc.basis = "document"
            session.add(doc)
            await session.commit()

            totals, _ = await _load_canonical(org_id, session)

        assert (totals.count, totals.inflow_cents, totals.outflow_cents) == (2, 500, 300)
