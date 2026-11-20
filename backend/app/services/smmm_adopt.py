"""Move a client's old analyses out of the accountant's organisation.

Before M1 a client was only a label on a job (`smmm_client_id`): its documents,
ledger rows and reports all sat in the accountant's own organisation. Clients
are now organisations of their own; this moves the old work into it.

What moves is chosen by one rule: a job belongs to the client when it carries
`smmm_client_id`, and it may only be taken from an organisation the accountant
is a member of. Then:

* the job and what is keyed to it (agent runs, review rows, defensibility
  packets, decision log, RAG chunks) change `org_id`;
* the ledger is *derived* data and its row identity includes the organisation,
  so it is not edited in place: the job's rows and open items are removed from
  the old organisation and appended again to the client's (`append_job`).

A job is **refused, not moved**, when the move would lose a person's decision:
a ledger row someone excluded, or an open-item match someone confirmed or
rejected, would come back as if nobody had looked. Refusals are reported with
the reason, and the job stays where it is.

Dry-run is the default and writes nothing. Re-running is safe: a moved job is
not selected again for the move, but its ledger append and the removal of its
old rows are repeated, so an interrupted run is finished by running it again.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.analysis_job import AnalysisJob
from app.models.canonical_transaction import CanonicalTransaction
from app.models.decision_log import DecisionLog
from app.models.defensibility_packet import DefensibilityPacket
from app.models.open_item import OpenItem
from app.models.open_item_match import OpenItemMatch
from app.models.organization import OrgMembership
from app.models.rag_chunk import RagChunk
from app.models.smmm_onay import SMMMOnayKaydi
from app.models.smmm_portal import SMMMMuhasebeci, SMMMMusteriKayit
from app.models.user import User
from app.services.org_membership import create_client_org

logger = logging.getLogger(__name__)

# Tables keyed to one job and one organisation: `org_id` follows the job.
_JOB_BOUND: tuple[Any, ...] = (AgentRun, SMMMOnayKaydi, DefensibilityPacket, DecisionLog, RagChunk)

EXCLUDED_ROW = "bir satır elle hariç tutulmuş"
DECIDED_MATCH = "bir eşleştirme bir kişi tarafından onaylanmış ya da reddedilmiş"


@dataclass
class AdoptReport:
    client_id: str
    client_org_id: str | None
    dry_run: bool
    created_org: bool = False
    moved: list[str] = field(default_factory=list)
    refused: dict[str, str] = field(default_factory=dict)
    ledger_appended: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "client_org_id": self.client_org_id,
            "dry_run": self.dry_run,
            "created_org": self.created_org,
            "moved": list(self.moved),
            "refused": dict(self.refused),
            "ledger_appended": self.ledger_appended,
        }


async def _decision_in_the_way(db: AsyncSession, org_id: str, job_id: str) -> str | None:
    """Why this job's derived rows cannot be rebuilt without losing a decision."""
    excluded = (
        await db.execute(
            select(func.count()).select_from(CanonicalTransaction).where(
                CanonicalTransaction.org_id == org_id,
                CanonicalTransaction.source_job_id == job_id,
                CanonicalTransaction.ledger_status == "excluded",
            )
        )
    ).scalar_one()
    if excluded:
        return EXCLUDED_ROW
    decided = (
        await db.execute(
            select(func.count())
            .select_from(OpenItemMatch)
            .join(OpenItem, OpenItem.id == OpenItemMatch.open_item_id)
            .where(
                OpenItem.org_id == org_id,
                OpenItem.source_job_id == job_id,
                # A person's decision. Matches the reconciler made itself have no
                # `decided_by` and are derived again from the moved rows.
                OpenItemMatch.decided_by.isnot(None),
            )
        )
    ).scalar_one()
    return DECIDED_MATCH if decided else None


async def adopt_client_jobs(
    db: AsyncSession, *, client_id: str, dry_run: bool = True
) -> AdoptReport:
    """Move the client's old jobs into the client's own organisation."""
    client = await db.get(SMMMMusteriKayit, client_id)
    if client is None:
        raise LookupError(f"client not found: {client_id}")
    accountant = await db.get(SMMMMuhasebeci, client.muhasebeci_id)
    user = await db.get(User, accountant.user_id) if accountant else None
    if accountant is None or user is None:
        raise LookupError("the client's accountant has no user")

    member_of = {
        str(r)
        for r in (
            await db.execute(select(OrgMembership.org_id).where(OrgMembership.user_id == user.id))
        ).scalars()
    }
    if user.org_id:
        member_of.add(str(user.org_id))

    jobs = (
        (await db.execute(select(AnalysisJob).where(AnalysisJob.smmm_client_id == client_id)))
        .scalars()
        .all()
    )
    report = AdoptReport(client_id=client_id, client_org_id=client.client_org_id, dry_run=dry_run)
    if not jobs:
        return report

    # Where the old work lives: the accountant's own organisation, i.e. a
    # membership that is not a client one. The client organisation itself is
    # excluded once it exists.
    sources = {str(j.org_id) for j in jobs if j.org_id and str(j.org_id) != client.client_org_id}

    client_org_id = client.client_org_id
    if client_org_id is None:
        report.created_org = True
        if not dry_run:
            home = next(iter(sorted(sources & member_of)), None)
            org = await create_client_org(
                db,
                name=client.firma_adi,
                accountant_user_id=str(user.id),
                home_org_id=home,
                home_role=str(user.role),
                vkn=client.vergi_no,
            )
            client.client_org_id = org.id
            client_org_id = org.id
            report.client_org_id = org.id

    to_append: list[str] = []
    for job in jobs:
        old_org = str(job.org_id) if job.org_id else None
        if old_org is not None and old_org == client_org_id:
            to_append.append(job.id)  # moved earlier: finish its ledger side
            continue
        if old_org is None or old_org not in member_of:
            report.refused[job.id] = "iş, müşavirin üyesi olmadığı bir organizasyonda"
            continue
        why = await _decision_in_the_way(db, old_org, job.id)
        if why:
            report.refused[job.id] = why
            continue
        report.moved.append(job.id)
        if dry_run:
            continue
        job.org_id = client_org_id
        for model in _JOB_BOUND:
            await db.execute(
                update(model).where(model.job_id == job.id, model.org_id == old_org).values(
                    org_id=client_org_id
                )
            )
        to_append.append(job.id)

    if dry_run:
        await db.rollback()
        return report

    await db.commit()

    # Derived data last, one job at a time: `append_job` commits. The old rows
    # go first so the same money is never counted in two companies.
    for job_id in to_append:
        stale_items = select(OpenItem.id).where(
            OpenItem.source_job_id == job_id, OpenItem.org_id != client_org_id
        )
        await db.execute(delete(OpenItemMatch).where(OpenItemMatch.open_item_id.in_(stale_items)))
        await db.execute(
            delete(OpenItem).where(OpenItem.source_job_id == job_id, OpenItem.org_id != client_org_id)
        )
        await db.execute(
            delete(CanonicalTransaction).where(
                CanonicalTransaction.source_job_id == job_id,
                CanonicalTransaction.org_id != client_org_id,
            )
        )
        await db.commit()
        from app.services.ledger import append_job

        await append_job(db, job_id)
        report.ledger_appended += 1
    logger.info(
        "smmm adopt: client=%s moved=%d refused=%d", client_id, len(report.moved), len(report.refused)
    )
    return report
