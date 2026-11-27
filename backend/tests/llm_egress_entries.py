"""How the app REALLY reaches each LLM call site, so the matrix proves masking with the context the app has.

The earlier matrix set the tenant context itself before every driver, so a site the app reaches without a
company (the review continuation, found in review) still looked masked. Here the matrix never sets it: each
site runs inside the production code that establishes the company for its real entry points, and only there.
Infrastructure that is not under test (Redis, the database engine) is pointed at the test world; the code
that decides the company is the product's own.

  request   the real `api.auth.get_current_user` resolves a bearer token of the seeded owner (as FastAPI does
            before the route body), then the site runs in the same task
  ws        the real `/ws/chat` handler (`api.ws_stream.websocket_chat`) with a token and one chat message
  cfo_job   the real worker wrapper `worker._records_run` (CFO analysis jobs) around the site
  review    the real `services.review_continuation.devam_et` (approved jobs, queued; also the reaper), with
            the continuation body replaced by the site
  ceo_job   the real `worker.run_ceo_analysis`, the CEO pipeline replaced by the site (the owner record that
            Redis holds is given)
  explicit  the site's real caller passes the company explicitly (scheduler brief, RAG index / re-index)

`SITE_ENTRIES` maps every call site to the entry points the code review found for it
(scripts are not entry points; dead code says so).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

from tests.llm_egress_harness import CANARY, SiteEnv

Driver = Callable[[SiteEnv], Awaitable[Any]]

_CFO = ("cfo_job", "review", "request")
_DOMAIN = ("request",)
_CHAIN = ("request", "review")

SITE_ENTRIES: dict[str, tuple[str, ...]] = {
    "agents/anomaly_agent.py::_generate_anomaly_narrative": _CFO,
    "agents/budget_agent.py::_generate_budget_narrative": _CFO,
    "agents/tax_agent.py::_generate_tax_narrative": _CFO,
    "agents/multi_period_agent.py::_generate_multiperiod_narrative": _CFO,
    "services/llm_structured.py::_structured": _CFO,
    "agents/data_ingestion.py::_extract_transactions_with_llm": ("cfo_job",),
    "agents/ceo/okr_agent.py::_generate_okr_narrative": ("request", "ceo_job"),
    "agents/ceo/strategic_priorities_agent.py::run_strategic_priorities_agent": ("request", "ceo_job", "review"),
    "services/llm_structured.py::call_llm": ("request", "ceo_job"),
    "agents/audit/orchestrator.py::node_audit_summary": _CHAIN,
    "agents/compliance/orchestrator.py::node_compliance_summary": _CHAIN,
    "agents/risk/orchestrator.py::node_risk_summary": _CHAIN,
    "agents/cto/incident_agent.py::_generate_incident_narrative": ("request", "ceo_job"),
    "agents/cto/infra_agent.py::_generate_infra_narrative": ("request", "ceo_job"),
    "agents/cto/tech_debt_agent.py::_generate_debt_narrative": ("request", "ceo_job"),
    "agents/cto/velocity_agent.py::_generate_velocity_narrative": ("request", "ceo_job"),
    "agents/cto/orchestrator.py::node_cto_summary": ("request", "ceo_job"),
    "agents/chro/attrition_agent.py::_generate_attrition_narrative": _DOMAIN,
    "agents/chro/orchestrator.py::node_chro_summary": _DOMAIN,
    "agents/cmo/campaign_agent.py::_generate_campaign_narrative": _DOMAIN,
    "agents/cmo/cohort_agent.py::_generate_cohort_narrative": _DOMAIN,
    "agents/cmo/funnel_agent.py::_generate_funnel_narrative": _DOMAIN,
    "agents/cmo/orchestrator.py::node_cmo_summary": _DOMAIN,
    "agents/coo/orchestrator.py::node_coo_summary": _DOMAIN,
    "agents/coo/process_agent.py::_generate_process_narrative": _DOMAIN,
    "agents/coo/resource_agent.py::_generate_resource_narrative": _DOMAIN,
    "agents/coo/sla_agent.py::_generate_sla_narrative": _DOMAIN,
    "agents/chat_agent.py::chat_with_ceo": _DOMAIN,
    "agents/chat_agent.py::chat_with_cfo": _DOMAIN,
    "agents/chat_agent.py::stream_chat_with_ceo": _DOMAIN,
    "agents/chat_agent.py::stream_chat_with_cfo": _DOMAIN,
    "agents/nl_query_engine.py::generate_nl_insight": _DOMAIN,
    "agents/nl_query_engine.py::generate_nl_insight_stream": _DOMAIN,
    "api/anomalies.py::explain_anomaly._generate": _DOMAIN,
    "api/ws_stream.py::_stream_llm_tokens": ("ws",),
    "services/accounting/thp_classifier.py::_llm_siniflandir": _DOMAIN,
    "services/llm_router.py::LLMTaskRouter._call_llm": _DOMAIN,
    "services/negotiation/boardroom.py::_structured": _DOMAIN,
    "services/reasoning_loop.py::ReasoningLoop._think": _DOMAIN,
    "services/reasoning_loop.py::ReasoningLoop._plan": _DOMAIN,
    "services/reasoning_loop.py::ReasoningLoop._act": _DOMAIN,
    "services/reasoning_loop.py::ReasoningLoop._synthesize": _DOMAIN,
    "scheduler.py::_generate_morning_brief_for_org": ("explicit",),
    "services/rag_service.py::index_job_text": ("explicit",),
    "services/rag_service.py::_embed_texts": ("explicit",),
    "services/rag_reindex.py::reindex_batch": ("explicit",),
    # never instantiated in production (the review found no caller); kept proven for when it is wired
    "services/rag/retriever.py::EmbeddingRagRetriever.retrieve": ("explicit",),
}


async def _owner(env: SiteEnv):
    from sqlalchemy import select

    from app.models.user import User

    async with env.maker() as db:
        return (await db.execute(select(User).where(User.org_id == env.org_id))).scalars().first()


async def _token(env: SiteEnv) -> str:
    from app.services.auth import create_access_token

    owner = await _owner(env)
    return create_access_token(str(owner.id), owner.email, str(owner.role), token_version=owner.token_version or 0)


async def _request(env: SiteEnv, driver: Driver, monkeypatch) -> None:
    from fastapi.security import HTTPAuthorizationCredentials
    from starlette.requests import Request

    from app.api.auth import get_current_user

    request = Request({"type": "http", "method": "GET", "path": "/api/v1/chat/ceo", "headers": [],
                       "query_string": b"", "client": ("127.0.0.1", 50000), "server": ("test", 80), "scheme": "http"})
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=await _token(env))
    async with env.maker() as db:
        await get_current_user(request, credentials, None, db)
    await driver(env)  # the route body, in the same task as its dependencies


class _FakeSocket:
    """Just enough of a Starlette WebSocket for the real handler: one chat message, then the client leaves."""

    def __init__(self, message: str) -> None:
        from starlette.websockets import WebSocketState

        self._inbox = [message]
        self.client = SimpleNamespace(host="127.0.0.1", port=50000)
        self.headers: dict[str, str] = {}
        self.client_state = WebSocketState.CONNECTED
        self.sent: list[str] = []

    async def accept(self) -> None:
        return None

    async def receive_text(self) -> str:
        from starlette.websockets import WebSocketDisconnect

        if not self._inbox:
            raise WebSocketDisconnect(code=1000)
        return self._inbox.pop(0)

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self, code: int = 1000) -> None:
        return None


async def _ws(env: SiteEnv, driver: Driver, monkeypatch) -> None:
    """The site is the handler's own stream helper: the driver is not used, the real handler sends the question."""
    import json

    from app.api import ws_auth, ws_stream

    monkeypatch.setattr(ws_auth, "session_factory", lambda: env.maker)
    question = f"{CANARY.counterparty_short} borcu ne kadar? {env.description}"
    socket = _FakeSocket(json.dumps({"type": "chat", "question": question}))
    await ws_stream.websocket_chat(socket, token=await _token(env))
    env.ws_sent = socket.sent  # type: ignore[attr-defined]


def _point_engine_at_world(env: SiteEnv, monkeypatch) -> None:
    import app.database as database

    monkeypatch.setattr(database, "engine", lambda: None)
    monkeypatch.setattr(database, "get_session_factory", lambda eng=None: env.maker)


async def _job_id(env: SiteEnv) -> str:
    from sqlalchemy import select

    from app.models.analysis_job import AnalysisJob

    async with env.maker() as db:
        return str((await db.execute(select(AnalysisJob.id))).scalars().first())


async def _cfo_job(env: SiteEnv, driver: Driver, monkeypatch) -> None:
    from app import worker

    _point_engine_at_world(env, monkeypatch)

    async def job(ctx: dict, job_id: str) -> dict:
        await driver(env)
        return {"ok": True}

    await worker._records_run(job)({}, await _job_id(env))


async def _review(env: SiteEnv, driver: Driver, monkeypatch) -> None:
    import app.post_completion as post_completion
    from app.services import review_continuation

    async def body(job_id: str, org_id: str, result: Any, db: Any) -> None:
        await driver(env)

    async def saved(job_id: str, db: Any) -> dict:
        return {}

    monkeypatch.setattr(post_completion, "continue_after_completion", body)
    monkeypatch.setattr(post_completion, "saved_result", saved)
    out = await review_continuation.devam_et(await _job_id(env))
    assert out.get("ok"), f"the review continuation did not run: {out}"


async def _ceo_job(env: SiteEnv, driver: Driver, monkeypatch) -> None:
    import app.agents.ceo.orchestrator as ceo
    from app import worker

    async def pipeline(**_: Any) -> dict:
        await driver(env)
        return {}

    async def owner(job_id: str) -> dict:
        return {"org_id": env.org_id, "user_id": "u"}

    class _Pool:  # the result is stored in Redis for polling: not under test
        async def set(self, *_: Any, **__: Any) -> None:
            return None

    async def pool() -> _Pool:
        return _Pool()

    monkeypatch.setattr(ceo, "run_ceo_pipeline", pipeline)
    monkeypatch.setattr(worker, "get_ceo_job_owner", owner)
    monkeypatch.setattr(worker, "get_arq_pool", pool)
    out = await worker.run_ceo_analysis({}, "ceo-job-1")
    assert out.get("ok"), f"the CEO job did not run: {out}"


async def _explicit(env: SiteEnv, driver: Driver, monkeypatch) -> None:
    await driver(env)


ENTRIES: dict[str, Callable[[SiteEnv, Driver, Any], Awaitable[None]]] = {
    "request": _request, "ws": _ws, "cfo_job": _cfo_job, "review": _review, "ceo_job": _ceo_job, "explicit": _explicit,
}


async def run_entry(name: str, env: SiteEnv, driver: Driver, monkeypatch) -> None:
    await ENTRIES[name](env, driver, monkeypatch)
