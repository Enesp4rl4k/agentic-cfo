"""
Demo ön-hesaplama (DEMO_PLAN §D2) — golden demo org'unu bir kez doldurur.

Logo Tiger 2024 demo CSV'sini CFO pipeline'ından geçirir, C-suite ajanlarını
(cto/cmo/coo/chro/risk/audit) örnek girdilerle çalıştırır, CEO synthesis'i
tamamlar. Sonuç: golden org (slug=demo-golden) için AnalysisJob + Report JSON
+ company_context (`last_*_result`) + semantic snapshot DB'de hazır —
`/demo/guest` konuk org'unu buradan klonlar, ziyaret anında hydration yeter.

Harici servis gerekmez: Redis/ARQ yok (`run_cfo_analysis` inline çalışır),
LLM anahtarı placeholder ise şablon anlatım fallback'i devreye girer.

Kullanım (backend çalışma dizininden):
    python scripts/demo_prefill.py            # eksik parçaları tamamla (idempotent)
    python scripts/demo_prefill.py --force    # her şeyi yeniden üret

Çıkış kodu: last_cfo_result yazılmadan biterse 1 (kapı testleri için).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ── sys.path bootstrap (scripts/ is not a package) ────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.api.demo import _get_demo_csv_content
from app.api.org import _regional_defaults
from app.config import get_settings
from app.core.atomic_io import atomic_write_bytes
from app.database import engine, get_session_factory
from app.models.agent_job import AgentJob, AgentJobStatus
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.organization import Organization

logger = logging.getLogger("demo_prefill")

GOLDEN_SLUG = "demo-golden"
DEMO_FILENAME = "logo_tiger_2024_demo.csv"
PERIOD = "2024"

# ── C-suite sample inputs ─────────────────────────────────────────────────────
# CSV literals mirror the frontend's own sample data (the shapes the pipelines
# and the pages were built against):
#   cmo   ← (dashboard)/cmo/page.tsx   SAMPLE_CAMPAIGN / FUNNEL / COHORT
#   coo   ← (dashboard)/coo/page.tsx   SAMPLE_PROCESSES / SAMPLE_SLA
#   chro  ← (dashboard)/chro/page.tsx  PH.headcount / attrition / compensation
#   audit ← (dashboard)/audit/page.tsx SAMPLE_DATA findings / controls / coverage
# cto/risk ship no sample CSVs anywhere — they run on empty inputs and rely on
# their pipelines' built-in fallbacks.
_CMO_INPUTS = {
    "campaign_csv": """Campaign,Channel,Spend,Revenue,Conversions
Summer Sale,google,5000,18000,120
Brand Awareness,meta,3200,9600,85
Product Launch,email,800,4200,210""",
    "funnel_csv": """id,stage,source,created,closed
1,Won,google,2024-01-05,2024-02-10
2,Lost,meta,2024-01-08,2024-02-15
3,Won,email,2024-01-12,2024-02-20""",
    "cohort_csv": """cohort,users,retention_30d,retention_90d,ltv,cac
2024-01,200,45%,28%,1200,150
2024-02,180,42%,25%,1100,165
2024-03,220,48%,31%,1350,140""",
}
_COO_INPUTS = {
    "process_csv": """process_name,cycle_time,throughput,wip,constraint_type,impact_score
Order Processing,5,20,45,resource,92
Payment Verification,3,30,25,policy,78
Inventory Check,2,40,15,material,65
Shipping Preparation,4,25,35,resource,88
Quality Inspection,3,15,20,resource,72""",
    "sla_csv": """ticket_id,title,assigned_to,created_date,due_date,priority,status
T001,Sistem Entegrasyonu,Ali,2024-06-20,2024-07-25,critical,in_progress
T002,Veri Aktarımı,Fatma,2024-06-18,2024-07-20,high,in_progress
T003,API Geliştirme,Mehmet,2024-06-22,2024-07-30,high,in_progress
T004,Raporlama,Ayşe,2024-06-15,2024-07-18,medium,in_progress
T005,Kullanıcı Arayüzü,Can,2024-06-25,2024-08-05,medium,in_progress""",
}
_CHRO_INPUTS = {
    "headcount_csv": """employee_id,name,department,level,role,location,fte,start_date,status
EMP001,Alice Chen,Engineering,L4,Senior Engineer,Istanbul,1.0,2021-03-15,active
EMP002,Bob Kim,Engineering,L3,Engineer,Istanbul,1.0,2022-07-01,active
EMP003,Carol Davis,Product,L5,Principal PM,Remote,1.0,2020-01-10,active
EMP004,Dan Ortiz,Sales,L2,Account Executive,Ankara,1.0,2023-02-28,active
EMP005,Eva Müller,HR,L3,HR Business Partner,Istanbul,1.0,2021-09-20,active""",
    "attrition_csv": """employee_id,department,level,role,tenure_years,departure_date,departure_type,reason,replaced
EMP010,Engineering,L3,Engineer,1.5,2024-01-15,voluntary,better_offer,no
EMP011,Sales,L2,Account Executive,0.8,2024-02-01,voluntary,compensation,yes
EMP012,Product,L4,Senior PM,3.2,2024-02-20,voluntary,career_growth,no
EMP013,Engineering,L5,Staff Engineer,4.1,2024-03-10,voluntary,better_offer,no
EMP014,Marketing,L2,Marketing Analyst,1.1,2024-03-25,involuntary,performance,yes""",
    "compensation_csv": """employee_id,department,level,role,base_salary,equity_annual,benefits_annual,market_rate,location
EMP001,Engineering,L4,Senior Engineer,95000,15000,12000,105000,Istanbul
EMP002,Engineering,L3,Engineer,72000,8000,10000,78000,Istanbul
EMP003,Product,L5,Principal PM,115000,20000,14000,120000,Remote
EMP004,Sales,L2,Account Executive,55000,0,8000,58000,Ankara
EMP005,HR,L3,HR Business Partner,68000,5000,10000,70000,Istanbul""",
}
_AUDIT_INPUTS = {
    "findings_csv": """finding_id,title,severity,status,due_date,owner,category,remediation_status
F001,Şifrelenmemiş veri tabanı yedeklemesi,critical,open,2024-02-15,IT Security,data_security,in_progress
F002,Finansmanda görev ayrımı ihlali,high,open,2024-03-01,Finance,access_control,not_started
F003,Eksik felaket kurtarma planı,high,closed,2024-01-20,Operations,business_continuity,completed
F004,Zayıf şifre politikası uygulaması,medium,open,2024-03-10,IT,identity_management,in_progress
F005,Satıcı sözleşme inceleme süreci,medium,open,2024-02-28,Procurement,third_party_risk,not_started""",
    "controls_csv": """control_id,name,category,design_effectiveness,operating_effectiveness,last_tested,owner
C001,Güvenlik duvarı kuralı incelemesi,it_security,85,80,2024-01-15,CTO
C002,Görev ayrımı matrisi,access_control,90,75,2023-11-20,CFO
C003,Veri yedekleme doğrulaması,data_security,95,90,2024-02-01,IT Manager
C004,Satıcı risk değerlendirmesi,third_party,80,65,2023-10-05,Procurement
C005,Değişim yönetimi onayı,it_operations,85,85,2024-01-25,CTO""",
    "audit_plan_csv": """unit_name,category,last_audit,frequency,risk_rating,scheduled_next
IT Altyapısı,technology,2023-06-15,annual,high,2024-06-15
Ödenecek Hesaplar,finance,2023-09-01,annual,medium,2024-09-01
İK Bordrosu,hr,2024-01-10,annual,medium,2025-01-10
Üçüncü Taraf Satıcılar,procurement,2023-03-20,annual,high,2024-03-20
Fiziksel Güvenlik,operations,2023-08-15,annual,low,2024-08-15""",
}
_SUITE_INPUTS: dict[str, dict[str, Any]] = {
    "cto": {},
    "cmo": _CMO_INPUTS,
    "coo": _COO_INPUTS,
    "chro": _CHRO_INPUTS,
    "risk": {},
    "audit": _AUDIT_INPUTS,
}
_SUITE_AGENTS: tuple[str, ...] = ("cto", "cmo", "coo", "chro", "risk", "audit")


async def _ensure_golden_org(db: Any) -> Organization:
    """Upsert the showcase org the guests are cloned from."""
    result = await db.execute(
        select(Organization).where(Organization.slug == GOLDEN_SLUG)
    )
    org = result.scalar_one_or_none()
    if org is not None:
        return org

    org = Organization(
        name=get_settings().demo_company_name,
        slug=GOLDEN_SLUG,
        description="Altın demo veri şablonu — demo_prefill.py üretir, /demo/guest klonlar.",
        **_regional_defaults("TR"),
    )
    db.add(org)
    await db.commit()
    logger.info("Golden org created: %s", org.id)
    return org


async def _create_cfo_job(db: Any, org_id: str) -> str:
    """Mirror of api/demo.py seed: write the bundled CSV, insert a PENDING job."""
    settings = get_settings()
    content = await _get_demo_csv_content()
    upload_dir = Path(settings.storage_local_path)
    upload_dir.mkdir(parents=True, exist_ok=True)

    job_id = str(uuid.uuid4())
    file_path = upload_dir / f"{job_id}_{DEMO_FILENAME}"
    atomic_write_bytes(file_path, content)

    job = AnalysisJob(
        id=job_id,
        status=JobStatus.PENDING,
        filename=DEMO_FILENAME,
        file_path=str(file_path),
        file_type="csv",
        org_id=org_id,
        user_id=None,  # golden org is ownerless — the column is nullable
    )
    db.add(job)
    await db.commit()
    return job_id


async def _approve_if_held(db: Any, job_id: str) -> bool:
    """Standing approval for the showcase analysis (mirrors api/analysis.py).

    The confidence gate may hold the run (AWAITING_REVIEW); the demo org's
    analysis is pre-approved, so flip the flag atomically and run the held
    continuation (company context + semantic + auto-chain) once.
    """
    from sqlalchemy import update

    from app.services.review_continuation import devam_et

    job = await db.get(AnalysisJob, job_id)
    if job is None or not job.awaiting_review:
        return False

    now = datetime.now(UTC)
    meta = dict(job.result_metadata or {})
    meta["review"] = {
        "approved_by": "demo-prefill",
        "approved_at": now.isoformat(),
        "devam": "bekliyor",
    }
    stmt = (
        update(AnalysisJob)
        .where(AnalysisJob.id == job_id, AnalysisJob.awaiting_review.is_(True))
        .values(
            awaiting_review=False,
            status=JobStatus.COMPLETED,
            updated_at=now,
            result_metadata=meta,
        )
        .execution_options(synchronize_session=False)
    )
    res = await db.execute(stmt)
    await db.commit()
    if res.rowcount != 1:
        return False

    logger.info("Job %s held for review — approved, running continuation", job_id)
    outcome = await devam_et(job_id)
    logger.info("Continuation: %s", outcome)
    return True


async def _run_cfo(db: Any, org_id: str, force: bool) -> bool:
    """Run the CFO pipeline for the golden org unless context already exists."""
    from app.services.company_context import get_company_context
    from app.worker import run_cfo_analysis

    ctx = await get_company_context(org_id, db)
    if ctx.last_cfo_result and not force:
        logger.info("CFO context already present — skipping (use --force to redo)")
        return True

    job_id = await _create_cfo_job(db, org_id)
    logger.info("CFO pipeline starting (job=%s) …", job_id)
    t0 = time.monotonic()
    await run_cfo_analysis({}, job_id, None)
    logger.info("CFO pipeline finished in %.1fs", time.monotonic() - t0)

    await _approve_if_held(db, job_id)

    db.expire_all()
    job = await db.get(AnalysisJob, job_id)
    if job is not None:
        logger.info(
            "CFO job status: %s (awaiting_review=%s)", job.status, job.awaiting_review
        )

    ctx = await get_company_context(org_id, db)
    return bool(ctx.last_cfo_result)


async def _run_suite_agent(db: Any, org_id: str, agent_type: str, force: bool) -> bool:
    """Run one C-suite agent pipeline and persist it to company context."""
    from app.api.agent_jobs import _run_agent_pipeline
    from app.services.company_context import get_company_context

    ctx = await get_company_context(org_id, db)
    if getattr(ctx, f"last_{agent_type}_result", None) and not force:
        logger.info("%s context already present — skipping", agent_type.upper())
        return True

    inputs: dict[str, Any] = {
        "company_name": get_settings().demo_company_name,
        "reporting_period": PERIOD,
        **_SUITE_INPUTS.get(agent_type, {}),
    }

    job = AgentJob(
        agent_type=agent_type,
        user_id=None,          # nullable — golden org is ownerless
        org_id=org_id,
        status=AgentJobStatus.PENDING,
        input_data=inputs,
        progress=0,
    )
    db.add(job)
    await db.commit()
    job_id = job.id

    logger.info("%s pipeline starting (job=%s) …", agent_type.upper(), job_id)
    t0 = time.monotonic()
    await _run_agent_pipeline(job_id, agent_type, inputs)
    logger.info("%s pipeline finished in %.1fs", agent_type.upper(), time.monotonic() - t0)

    db.expire_all()
    row = await db.get(AgentJob, job_id)
    ok = bool(row is not None and row.status == AgentJobStatus.COMPLETED)
    if not ok:
        logger.error(
            "%s FAILED: %s", agent_type.upper(),
            row.error_message if row else "row missing",
        )

    ctx = await get_company_context(org_id, db)
    persisted = bool(getattr(ctx, f"last_{agent_type}_result", None))
    return ok and persisted


async def _run_ceo(db: Any, org_id: str, force: bool) -> bool:
    """Run CEO synthesis (auto-chain may already have done it during the runs)."""
    from app.agents.orchestration.auto_chain import _run_ceo_synthesis
    from app.services.company_context import get_company_context

    ctx = await get_company_context(org_id, db)
    if ctx.last_ceo_result and not force:
        logger.info("CEO context already present — skipping")
        return True

    logger.info("CEO synthesis starting …")
    t0 = time.monotonic()
    await _run_ceo_synthesis(org_id, ctx, db)
    logger.info("CEO synthesis finished in %.1fs", time.monotonic() - t0)

    db.expire_all()
    ctx = await get_company_context(org_id, db)
    return bool(ctx.last_ceo_result)


async def prefill(force: bool = False) -> dict[str, Any]:
    """Fill the golden org. Returns a summary dict (also printed)."""
    factory = get_session_factory(engine())
    summary: dict[str, Any] = {"org_slug": GOLDEN_SLUG}

    async with factory() as db:
        org = await _ensure_golden_org(db)
        org_id = str(org.id)
        summary["org_id"] = org_id

        summary["agents"] = {"cfo": await _run_cfo(db, org_id, force)}
        for agent in _SUITE_AGENTS:
            summary["agents"][agent] = await _run_suite_agent(db, org_id, agent, force)

        # Background auto-chain spawns may still be writing CEO; give them a
        # moment before the explicit run (which then skips if they won).
        await asyncio.sleep(2)
        summary["agents"]["ceo"] = await _run_ceo(db, org_id, force)

        from app.services.company_context import get_company_context

        ctx = await get_company_context(org_id, db)
        summary["context"] = {
            agent: bool(getattr(ctx, f"last_{agent}_result", None))
            for agent in ("cfo", "ceo", "cto", "cmo", "coo", "chro", "risk", "audit")
        }
        summary["active_cfo_job"] = getattr(ctx, "active_cfo_job_id", None)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Golden demo org ön-hesaplama")
    parser.add_argument(
        "--force", action="store_true", help="existing results are redone"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    # The summary must survive Windows ANSI codepages (cp1254 has no box
    # drawing chars): utf-8 stdout with replacement as the safety net.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - exotic stdio
        pass

    summary = asyncio.run(prefill(force=args.force))
    print("\n-- demo_prefill summary " + "-" * 40)
    for key, value in summary.items():
        print(f"  {key}: {value}")

    if not summary.get("context", {}).get("cfo"):
        print("FAILED: last_cfo_result missing after prefill")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
