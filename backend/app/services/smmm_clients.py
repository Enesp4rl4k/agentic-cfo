"""Müşavirin müşterisi ile uyum zinciri arasındaki bağ.

`SMMMMusteriKayit` carries `client_org_id`, `last_job_id`, `last_analysis_at`,
`health_score` and `health_label`, described in the model as a denormalized
cache. Nothing ever wrote any of them, so the portal's dashboard counted
analysed clients from a field that was always null and reported zero for every
accountant who ever used it.

They stay unwritten, deliberately. A cache drifts from what it caches, and this
one would drift silently — the same shape as every other invented value this
codebase has had to unpick. Per-client status is derived here from the jobs
themselves, which cannot be stale by construction.

What an accountant needs on a Monday is not a health score nobody computes. It
is: which of my clients has something waiting for me.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob
from app.models.defensibility_packet import DefensibilityPacket
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi


class ClientNotOwned(LookupError):
    """The caller's SMMM record does not have this client."""

    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        super().__init__(f"Müşteri bulunamadı veya size ait değil: {client_id}")


@dataclass
class ClientStatus:
    """What has actually happened for one client company."""

    client_id: str
    job_count: int
    last_job_id: str | None
    last_job_status: str | None
    last_analysis_at: datetime | None
    pending_review: int
    packet_sealed: bool

    @property
    def needs_attention(self) -> bool:
        """Something is waiting for the accountant."""
        return self.pending_review > 0 or self.last_job_status == "failed"

    @property
    def stage(self) -> str:
        """Where this client is in the chain, in one word."""
        if self.job_count == 0:
            return "veri_yok"
        if self.last_job_status == "failed":
            return "basarisiz"
        if self.pending_review > 0:
            return "onay_bekliyor"
        if self.packet_sealed:
            return "muhurlendi"
        return "analiz_edildi"

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "job_count": self.job_count,
            "last_job_id": self.last_job_id,
            "last_job_status": self.last_job_status,
            "last_analysis_at": (
                self.last_analysis_at.isoformat() if self.last_analysis_at else None
            ),
            "pending_review": self.pending_review,
            "packet_sealed": self.packet_sealed,
            "needs_attention": self.needs_attention,
            "stage": self.stage,
        }


async def status_for_clients(
    db: AsyncSession, client_ids: list[str]
) -> dict[str, ClientStatus]:
    """Derive each client's position in the chain from the jobs themselves.

    Four grouped queries rather than one per client: an accountant's book is
    tens to low hundreds of companies, and a per-client round trip would make
    the dashboard slower the more successful the accountant is.
    """
    empty = {
        cid: ClientStatus(
            client_id=cid,
            job_count=0,
            last_job_id=None,
            last_job_status=None,
            last_analysis_at=None,
            pending_review=0,
            packet_sealed=False,
        )
        for cid in client_ids
    }
    if not client_ids:
        return empty

    # A client's work is whatever carries its label (the old "upload for a client"
    # form) OR sits in the client's own organisation (what an accountant creates after
    # switching into the client, M1). Only the first was read, so every client that is an
    # organisation showed "veri_yok" forever, with work and approvals sitting in it.
    from app.models.smmm_portal import SMMMMusteriKayit

    org_of = {
        str(cid): str(org)
        for cid, org in (
            await db.execute(
                select(SMMMMusteriKayit.id, SMMMMusteriKayit.client_org_id).where(
                    SMMMMusteriKayit.id.in_(client_ids),
                    SMMMMusteriKayit.client_org_id.isnot(None),
                )
            )
        ).all()
    }
    client_of_org = {org: cid for cid, org in org_of.items()}

    where = AnalysisJob.smmm_client_id.in_(client_ids)
    if client_of_org:
        where = where | AnalysisJob.org_id.in_(list(client_of_org))
    rows = (
        await db.execute(select(AnalysisJob).where(where).order_by(desc(AnalysisJob.created_at)))
    ).scalars().all()

    jobs_of: dict[str, list[AnalysisJob]] = {}
    for job in rows:  # newest first; a job is one job however many ways it is linked
        cid = str(job.smmm_client_id) if job.smmm_client_id else client_of_org.get(str(job.org_id))
        if cid in empty:
            jobs_of.setdefault(cid, []).append(job)
    counts = {cid: len(js) for cid, js in jobs_of.items()}
    latest = {cid: js[0] for cid, js in jobs_of.items()}

    all_job_ids = [str(j.id) for js in jobs_of.values() for j in js]
    latest_ids = [str(j.id) for j in latest.values()]

    pending_by_job: dict[str, int] = {}
    sealed: set[str] = set()
    if all_job_ids:
        pending_by_job = {
            str(job_id): int(n)
            for job_id, n in (
                await db.execute(
                    select(SMMMOnayKaydi.job_id, func.count())
                    .where(
                        SMMMOnayKaydi.job_id.in_(all_job_ids),
                        SMMMOnayKaydi.durum == OnayDurumu.BEKLIYOR,
                    )
                    .group_by(SMMMOnayKaydi.job_id)
                )
            ).all()
        }
        sealed = {
            str(job_id)
            for (job_id,) in (
                await db.execute(
                    select(DefensibilityPacket.job_id).where(
                        DefensibilityPacket.job_id.in_(latest_ids),
                        DefensibilityPacket.status == "finalized",
                    )
                )
            ).all()
        }
    # Waiting for the accountant is waiting on *any* of the client's jobs, not only the
    # newest: an older upload's open entries do not stop being open.
    pending = {
        cid: sum(pending_by_job.get(str(j.id), 0) for j in js) for cid, js in jobs_of.items()
    }

    for cid, job in latest.items():
        empty[cid] = ClientStatus(
            client_id=cid,
            job_count=int(counts.get(cid, 0)),
            last_job_id=str(job.id),
            last_job_status=str(job.status),
            last_analysis_at=job.completed_at or job.created_at,
            pending_review=pending.get(cid, 0),
            packet_sealed=str(job.id) in sealed,
        )
    return empty


async def assert_owns_client(
    db: AsyncSession, user_id: str, client_id: str
) -> str:
    """Return the client id if this user's SMMM record owns it, else raise.

    Ownership is checked here rather than trusted from the request: a client id
    is a plain string on an upload form, and without this an accountant could
    file work against somebody else's client by guessing one.
    """
    from app.models.smmm_portal import SMMMMuhasebeci, SMMMMusteriKayit

    row = (
        await db.execute(
            select(SMMMMusteriKayit.id)
            .join(SMMMMuhasebeci, SMMMMusteriKayit.muhasebeci_id == SMMMMuhasebeci.id)
            .where(
                SMMMMusteriKayit.id == client_id,
                SMMMMuhasebeci.user_id == user_id,
                SMMMMusteriKayit.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ClientNotOwned(client_id)
    return str(row)
