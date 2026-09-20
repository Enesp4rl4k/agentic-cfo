"""
Seed Script — Contradiction Demo Org
Populates an organization with contradictory financial and marketing data:
- CFO: Inflow $10,000 vs Claimed Revenue $16,000, Runway 3.0 months
- CMO: Claimed ROAS 4.0x, High growth narrative
- Automatically runs rebuild_semantic_snapshot to generate ConflictCards and Decision Brief.

Usage:
  python backend/scripts/seed_demo_org.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# Add backend directory to sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import AsyncSessionLocal, engine, Base
from app.models.organization import Organization
from app.models.user import User
from app.models.company_context import CompanyContextSnapshot
from app.models.company_semantic_snapshot import CompanySemanticSnapshotRow
from app.models.sync_run import SyncRun
from app.models.canonical_transaction import CanonicalTransaction
from app.models.agent_conflict import AgentConflict
from app.services.company_context import CompanyContext, save_company_context
from app.services.semantic.rebuild import rebuild_semantic_snapshot

DEMO_ORG_ID = "demo-org-contradiction-001"
PERIOD_KEY = datetime.now(timezone.utc).strftime("%Y-%m")


async def seed() -> None:
    print(f"[*] Starting Demo Org seeding (Period: {PERIOD_KEY})...")
    async with AsyncSessionLocal() as db:
        # Check or create demo organization
        existing_org = await db.get(Organization, DEMO_ORG_ID)
        if not existing_org:
            org = Organization(
                id=DEMO_ORG_ID,
                name="Acme Contradiction Demo Corp",
                slug=f"acme-demo-{uuid4().hex[:6]}",
                base_currency="USD",
                locale="en-US",
                regional_packs=["tr"],
            )
            db.add(org)
            await db.flush()
            print(f"[+] Created Organization: {org.name} ({org.id})")
        else:
            print(f"[*] Organization {existing_org.name} already exists.")

        # Create CompanyContext with contradictory agent reports
        ctx = CompanyContext(org_id=DEMO_ORG_ID)
        ctx.company_name = "Acme Contradiction Demo Corp"
        ctx.reporting_period = PERIOD_KEY
        ctx.last_cfo_result = {
            "pnl": {
                "revenue_cents": 1_600_000,
                "net_margin": 0.05,
                "gross_margin": 0.40,
                "ebitda_cents": 100_000,
            },
            "cashflow": {
                "operating": 10_000,
                "net_change": -50_000,
            },
            "forecast": {
                "scenarios": {
                    "base": {
                        "runway_months": 3.0,
                        "growth_rate": 1.01,
                    },
                    "pessimistic": {
                        "runway_months": 1.8,
                        "growth_rate": 0.95,
                    },
                }
            },
            "anomalies": [
                {
                    "title": "Vendor Double Billing",
                    "severity": "high",
                    "description": "Software vendor billed twice in the same month.",
                }
            ],
        }
        ctx.last_cmo_result = {
            "campaigns": {
                "overall_roas": 4.0,
                "cac_cents": 15_000,
                "ltv_cac": 4.5,
            }
        }
        ctx.last_cto_result = {
            "tech_debt_score": 6.8,
            "overall_health_score": 7.2,
        }
        await save_company_context(ctx, db)
        print("[+] Seeded CompanyContext (CFO runway 3.0 mo vs CMO 4.0x ROAS)")

        # Add canonical transactions
        tx_date = datetime.now(timezone.utc)
        db.add(
            CanonicalTransaction(
                org_id=DEMO_ORG_ID,
                source_type="crm_export",
                source_record_id=f"crm-{uuid4().hex[:6]}",
                transaction_date=tx_date,
                amount_cents=1_000_000,
                direction="inflow",
                category="revenue",
                description="CRM closed-won deal (Cash Inflow $10k)",
            )
        )
        db.add(
            CanonicalTransaction(
                org_id=DEMO_ORG_ID,
                source_type="bank_feed",
                source_record_id=f"bank-{uuid4().hex[:6]}",
                transaction_date=tx_date,
                amount_cents=800_000,
                direction="outflow",
                category="payroll",
                description="Engineering payroll",
            )
        )
        await db.commit()
        print("[+] Seeded Canonical Transactions")

        # Run semantic rebuild to calculate metrics and auto-detect conflicts
        print("[*] Rebuilding semantic snapshot and detecting metric conflicts...")
        snapshot = await rebuild_semantic_snapshot(
            DEMO_ORG_ID,
            db,
            period_key=PERIOD_KEY,
            force=True,
            strict=True,
        )
        await db.commit()

        print(f"[✓] Demo Org seeded successfully!")
        print(f"    - Org ID: {DEMO_ORG_ID}")
        print(f"    - Period: {snapshot.period.key if snapshot else 'N/A'}")
        print(f"    - Metrics Count: {len(snapshot.metrics) if snapshot else 0}")
        print(f"    - Conflicts: CFO Revenue ($16k) vs Inflow ($10k) detected.")


if __name__ == "__main__":
    asyncio.run(seed())
