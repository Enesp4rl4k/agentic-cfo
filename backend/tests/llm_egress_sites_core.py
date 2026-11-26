"""Canary drivers for the call sites that are not agent narratives: the router, the retrieval path, the worker.

A driver is `async def (env: SiteEnv)`: it runs the real code with canary-bearing input. It must not catch the
product's own fallbacks away: if the site swallows an exception and answers from a template, the matrix sees
zero provider calls and fails the driver by name.
"""
from __future__ import annotations

from tests.llm_egress_harness import CANARY, DESCRIPTION, Site, SiteEnv

SYSTEM = f"Sen {CANARY.company} için çalışan bir danışmansın."
PROMPT = f"{DESCRIPTION}. Tutar 1.234.567,89 TL, tarih 15.03.2026. VKN: {CANARY.vkn}."


async def _router(env: SiteEnv) -> None:
    from app.services.llm_router import LLMTaskRouter

    await LLMTaskRouter().complete("deep_analysis", PROMPT, SYSTEM)  # off: the router answers with its error text


async def _index_job_text(env: SiteEnv) -> None:
    from app.services.rag_service import index_job_text

    async with env.maker() as db:
        await index_job_text(db, org_id=env.org_id, job_id="job-1", source_type="upload", raw_text=DESCRIPTION * 3)
        await db.rollback()


async def _embed_texts(env: SiteEnv) -> None:
    from app.services.rag_service import _embed_texts as embed

    await embed([DESCRIPTION], org_id=env.org_id)


SITES: dict[str, Site] = {
    "services/llm_router.py::LLMTaskRouter._call_llm": Site(_router),
    "services/rag_service.py::index_job_text": Site(_index_job_text),
    "services/rag_service.py::_embed_texts": Site(_embed_texts),
}
ALIASED: dict[str, str] = {}
