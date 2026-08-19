"""
Router registry — single place that maps every FastAPI router to its tag and prefix.

SOLID-3: Extracted from main.py to follow the Open/Closed Principle.
Adding a new feature module only requires appending an entry here —
main.py never changes for new routes.

Usage (in main.py):
    from app.api.registry import register_routers
    register_routers(app)
"""
from __future__ import annotations

from fastapi import FastAPI

# Each entry: (import_path, attr_name, tag)
# Loaded lazily so import errors are isolated per-router.
_ROUTERS = [
    ("app.api.upload",              "router", "upload"),
    ("app.api.stream",              "router", "stream"),
    ("app.api.analysis",            "router", "analysis"),
    ("app.api.auth",                "router", "auth"),
    ("app.api.benchmark",           "router", "benchmark"),
    ("app.api.open_banking",        "router", "open-banking"),
    ("app.api.causal",              "router", "causal"),
    ("app.api.efatura",             "router", "e-fatura"),
    ("app.api.sensitivity",         "router", "sensitivity"),
    ("app.api.alerts",              "router", "alerts"),
    ("app.api.brief",               "router", "brief"),
    ("app.api.dashboard",           "router", "dashboard"),
    ("app.api.reports",             "router", "reports"),
    ("app.api.corrections",         "router", "corrections"),
    ("app.api.anomalies",           "router", "anomalies"),
    ("app.api.chat",                "router", "chat"),
    ("app.api.datasource",          "router", "datasource"),
    ("app.api.cto",                 "router", "cto"),
    ("app.api.ceo",                 "router", "ceo"),
    ("app.api.cmo",                 "router", "cmo"),
    ("app.api.coo",                 "router", "coo"),
    ("app.api.chro",                "router", "chro"),
    ("app.api.compliance",          "router", "compliance"),
    ("app.api.risk",                "router", "risk"),
    ("app.api.audit",               "router", "audit"),
    ("app.api.demo",                "router", "demo"),
    ("app.api.org",                 "router", "org"),
    ("app.api.pilot",               "router", "pilot"),
    ("app.api.context",             "router", "context"),
    ("app.api.notifications",       "router", "notifications"),
    ("app.api.agent_jobs",          "router", "agent-jobs"),
    ("app.api.integrations_github", "router", "integrations"),
    ("app.api.muhasebe",            "router", "muhasebe"),         # MUHASEBE-6
    ("app.api.counterfactual",      "router", "counterfactual"),   # S6
    ("app.api.cascade",             "router", "cascade"),          # Cascade Risk Simulator
    ("app.api.multidomain_cf",      "router", "multidomain-cf"),  # Multi-Domain Counterfactual
    ("app.api.swot",                "router", "swot"),             # SWOT Analysis
    ("app.api.risk_kernel",         "router", "risk-kernel"),      # Risk Kernel (otomatik KRI)
    ("app.api.risk_cascade",        "router", "risk-cascade"),     # Risk + Cascade Koprusu
    ("app.api.cto_cmo_kernel",      "router", "cto-cmo-kernel"),  # CTO + CMO Kernel
    ("app.api.chro_coo_kernel",          "router", "chro-coo-kernel"),         # CHRO + COO Kernel
    ("app.api.audit_compliance_kernel",  "router", "audit-compliance-kernel"), # Audit + Compliance Kernel
    ("app.api.cross_domain",             "router", "cross-domain"),            # Cross-Domain Intelligence Hub
    ("app.api.erp_integrations",         "router", "erp"),                     # ERP Integrations (Parasut, Logo Tiger)
    ("app.api.intelligence",             "router", "intelligence"),             # Temporal + Negotiation API
    ("app.api.advanced_intelligence",    "router", "advanced"),                 # NL-Simulate + Proactive + PDF
    ("app.api.smmm_benchmark",           "router", "smmm-benchmark"),           # SMMM Portal + Benchmark
    ("app.api.ws_stream",                "router", "ws"),                       # WebSocket token streaming
    ("app.api.smmm_onay",               "router", "smmm-onay"),                 # SMMM Onay Workflow
    ("app.api.email_ingest",            "router", "email"),                      # Email Parser + Ingest
    ("app.api.sso",                     "router", "sso"),                        # SSO / OAuth2 (SEC-1)
    ("app.api.compliance_gdpr",         "router", "compliance-gdpr"),            # KVKK / GDPR (SEC-3)
    ("app.api.security",                "router", "security"),                   # SOC2 + IP whitelist (SEC-4/5)
    ("app.api.analytics",               "router", "analytics"),                  # AN-1..6: TCMB, Monte Carlo, WC, Cohort
    ("app.api.integrations_extended",   "router", "integrations-ext"),           # INT-2,4,5,6: OB, Ecom, Sheets, Webhook
    ("app.api.agent_graph",             "router", "agent-graph"),                 # AGENT-2: Pipeline graph visualization
    ("app.api.billing",                 "router", "billing"),                     # STRIPE: Subscription plans
    ("app.api.data_quality",            "router", "data-quality"),                # DQ-1/2/3: CSV validation + auto-mapping
    ("app.api.comparison",              "router", "comparison"),                  # DQ-4: Multi-period comparison
    ("app.api.sync_schedules",          "router", "sync"),                        # DQ-5: Scheduled sync
    ("app.api.negotiation",             "router", "negotiation"),                 # L2: Agent consensus + conflict detection
    ("app.api.compliance_extended",     "router", "compliance-extended"),         # L3: SOX/ISO 27001/GDPR Article 30-33
    ("app.api.ws_alerts",               "router", "ws-alerts"),                   # M1: WebSocket org-channel + alert history
    ("app.api.reports_pdf",             "router", "reports-pdf"),                  # M2: PDF report generation (WeasyPrint)
    ("app.api.system",                  "router", "system"),                       # Global management/ops health
]

_API_PREFIX = "/api/v1"


def register_routers(app: FastAPI) -> None:
    """
    Import and register all API routers onto the FastAPI app.

    Import errors for individual routers are caught and logged so a broken
    optional module (e.g. integrations_github) doesn't crash the whole server.
    """
    import importlib
    import logging
    logger = logging.getLogger(__name__)

    registered: list[str] = []
    skipped: list[str] = []
    for module_path, attr, tag in _ROUTERS:
        try:
            module = importlib.import_module(module_path)
            router = getattr(module, attr)
            app.include_router(router, prefix=_API_PREFIX, tags=[tag])
            registered.append(module_path)
        except ImportError as exc:
            logger.warning("Skipping router %s — import error: %s", module_path, exc)
            skipped.append(module_path)
        except AttributeError as exc:
            logger.warning("Skipping router %s — attribute error: %s", module_path, exc)
            skipped.append(module_path)

    logger.info(
        "Router registry loaded: registered=%d skipped=%d",
        len(registered),
        len(skipped),
    )
    if skipped:
        logger.warning("Router registry skipped modules: %s", ", ".join(skipped))
