"""
DataSource model — stores domain-specific uploaded files tied to an analysis job.

Each job can have one primary CFO file (bank statement) plus optional domain files:
  - cto:  cloud_billing, git_log, incident_log, sprint_data
  - chro: headcount, attrition, compensation
  - cmo:  campaign, funnel, cohort
  - coo:  sla, process, resource

When the CEO pipeline is triggered, it queries DataSource to find all
available files for the job and passes them to the appropriate sub-pipelines.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import String, DateTime, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DataSourceDomain(StrEnum):
    CFO  = "cfo"
    CTO  = "cto"
    CHRO = "chro"
    CMO  = "cmo"
    COO  = "coo"


class DataSourceType(StrEnum):
    # CFO
    BANK_STATEMENT  = "bank_statement"

    # CTO
    CLOUD_BILLING   = "cloud_billing"
    GIT_LOG         = "git_log"
    INCIDENT_LOG    = "incident_log"
    SPRINT_DATA     = "sprint_data"

    # CHRO
    HEADCOUNT       = "headcount"
    ATTRITION       = "attrition"
    COMPENSATION    = "compensation"

    # CMO
    CAMPAIGN        = "campaign"
    FUNNEL          = "funnel"
    COHORT          = "cohort"

    # COO
    SLA             = "sla"
    PROCESS         = "process"
    RESOURCE        = "resource"


# Maps each (domain, source_type) to the kwarg name expected by the pipeline
# e.g. CTO orchestrator expects cloud_billing_csv=<text content>
DOMAIN_SOURCE_KWARGS: dict[tuple[str, str], str] = {
    (DataSourceDomain.CTO,  DataSourceType.CLOUD_BILLING):  "cloud_billing_csv",
    (DataSourceDomain.CTO,  DataSourceType.GIT_LOG):         "git_log_text",
    (DataSourceDomain.CTO,  DataSourceType.INCIDENT_LOG):    "incident_csv",
    (DataSourceDomain.CTO,  DataSourceType.SPRINT_DATA):     "sprint_csv",
    (DataSourceDomain.CHRO, DataSourceType.HEADCOUNT):       "headcount_csv",
    (DataSourceDomain.CHRO, DataSourceType.ATTRITION):       "attrition_csv",
    (DataSourceDomain.CHRO, DataSourceType.COMPENSATION):    "compensation_csv",
    (DataSourceDomain.CMO,  DataSourceType.CAMPAIGN):        "campaign_csv",
    (DataSourceDomain.CMO,  DataSourceType.FUNNEL):          "funnel_csv",
    (DataSourceDomain.CMO,  DataSourceType.COHORT):          "cohort_csv",
    (DataSourceDomain.COO,  DataSourceType.SLA):             "sla_csv",
    (DataSourceDomain.COO,  DataSourceType.PROCESS):         "process_csv",
    (DataSourceDomain.COO,  DataSourceType.RESOURCE):        "resource_csv",
}


class DataSource(Base):
    """One uploaded file for one domain/type, tied to an AnalysisJob."""
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # The parent job this data source belongs to.
    # Intentionally no FK relationship object — we query by job_id directly
    # to avoid circular imports with AnalysisJob.
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    domain: Mapped[str] = mapped_column(String(20), nullable=False)
    # e.g. "cto", "chro", "cmo", "coo", "cfo"

    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # e.g. "cloud_billing", "headcount", "campaign"

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Optional human-readable label (e.g. "Q1 2024 AWS Billing")
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def pipeline_kwarg(self) -> str | None:
        """
        Returns the keyword argument name this source maps to in its pipeline.
        e.g. DataSource(domain='cto', source_type='cloud_billing') → 'cloud_billing_csv'
        Returns None if the mapping is not defined (should not happen for valid sources).
        """
        return DOMAIN_SOURCE_KWARGS.get((self.domain, self.source_type))
