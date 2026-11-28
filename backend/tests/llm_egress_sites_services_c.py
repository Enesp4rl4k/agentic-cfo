"""Canary drivers (services, part C): scheduler brief, THP classifier, structured helpers, boardroom, retriever,
reasoning loop and the two streaming API sites.

Each driver runs the REAL product function with canary-bearing input. Where a function swallows its own errors and
answers from a template, the input is built so the call still reaches the gateway (the matrix demands >= 1 call).
"""
from __future__ import annotations

from types import SimpleNamespace

from tests.llm_egress_harness import CANARY, Site, SiteEnv, dumps

QUESTION = (
    f"{CANARY.company} için {CANARY.counterparty} ödemesinden sonra nakit pisti ne olur? "
    f"İlgili kişi {CANARY.person}, {CANARY.email}"
)


def _chunk_text(env: SiteEnv) -> str:
    return f"{env.description} {CANARY.vendor} {CANARY.vkn}"


# ── scheduler.py ─────────────────────────────────────────────────────────────

async def _morning_brief(env: SiteEnv) -> None:
    from datetime import UTC, datetime

    from sqlalchemy import select

    import app.database as database
    import app.worker as worker
    from app.models.analysis_job import AnalysisJob
    from app.scheduler import _generate_morning_brief_for_org

    async with env.maker() as db:  # the brief only looks at jobs completed in the last 24 h
        job = (await db.execute(select(AnalysisJob))).scalars().first()
        job.completed_at = datetime.now(UTC)
        await db.commit()

    saved = (database.engine, database.get_session_factory, worker.get_arq_pool)

    async def _no_redis():  # the brief is stored in Redis at the end (unrelated infrastructure): fail fast, the
        raise RuntimeError("no redis in the proof")  # product already catches and logs it

    # The function opens `get_session_factory(engine())()`: point it at the test database, nothing else changes.
    database.engine = lambda: None  # type: ignore[assignment]
    database.get_session_factory = lambda eng=None: env.maker  # type: ignore[assignment]
    worker.get_arq_pool = _no_redis  # type: ignore[assignment]
    try:
        await _generate_morning_brief_for_org(env.org_id)
    finally:
        database.engine, database.get_session_factory, worker.get_arq_pool = saved


# ── services/accounting/thp_classifier.py ────────────────────────────────────

async def _thp(env: SiteEnv) -> None:
    from app.services.accounting.thp_classifier import _llm_siniflandir

    await _llm_siniflandir(env.description, env.canary.vendor, "expense", 1_234_567_89)


# ── services/llm_structured.py ───────────────────────────────────────────────

def _pnl_reply(schema: type):
    from app.services.llm_structured import ActionItem, PnLNarrative

    return PnLNarrative(summary="Özet.", actions=[ActionItem(action="İzleyin.")])


async def _structured_llm(env: SiteEnv) -> None:
    from app.services.llm_structured import PnLNarrative, _structured

    await _structured(
        task="short_narrative", schema=PnLNarrative,
        system_prompt=f"Sen {env.canary.company} için çalışan bir CFO asistanısın.",
        user_prompt=f"Gelir Tablosu:\n{dumps(env.figures())}\nEn büyük gider: {env.description}",
        temperature=0.1, max_tokens=512,
    )


async def _call_llm(env: SiteEnv) -> None:
    from app.services.llm_structured import call_llm

    await call_llm(f"{env.description}\n{dumps(env.figures())}", system_prompt=f"{env.canary.company} danışmanı.")


# ── services/negotiation/boardroom.py ────────────────────────────────────────

def _boardroom_reply(schema: type):
    from app.services.negotiation.boardroom import BoardroomConsensus, BoardroomStatement

    if schema is BoardroomConsensus:
        return BoardroomConsensus(topic="t", resolution_status="Uzlaşıldı", final_decision="d",
                                  confidence_score=0.8, action_items=["a"])
    return BoardroomStatement(agent_name="CFO", argument="a", proposed_solution="s")


async def _boardroom(env: SiteEnv) -> None:
    # `_structured` is the call site; the three prompt builders that feed it are driven so the real prompts are sent.
    from app.services.negotiation.boardroom import (
        _generate_consensus,
        _generate_opening_statement,
        _generate_response_statement,
    )

    topic = f"{env.canary.counterparty} ile sözleşme"
    context = f"{env.description}\n{dumps(env.figures())}"
    await _generate_opening_statement("CFO", topic, context)
    await _generate_response_statement("CMO", topic, f"CFO: {env.description}")
    await _generate_consensus(topic, f"CFO: {env.description}", f"CFO önerisi: {env.canary.vendor} ile görüş")


# ── services/rag/retriever.py ────────────────────────────────────────────────

async def _retriever(env: SiteEnv) -> None:
    from app.services.rag.retriever import EmbeddingRagRetriever

    class _Empty:
        def all(self) -> list:
            return []

    class _PostgresFacade:
        """A real session that says it is PostgreSQL and answers the pgvector query with no rows (SQLite has no
        `<=>`): the retriever embeds the QUERY, then falls back to TF-IDF on the real session, as in production."""

        def __init__(self, real) -> None:
            self._real = real
            self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        async def execute(self, stmt, *args, **kwargs):
            if "<=>" in str(stmt if not hasattr(stmt, "text") else stmt.text):
                return _Empty()
            return await self._real.execute(stmt, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._real, name)

    async with env.maker() as db:
        await EmbeddingRagRetriever().retrieve(db=_PostgresFacade(db), org_id=env.org_id, query=QUESTION)


# ── services/reasoning_loop.py ───────────────────────────────────────────────

def _loop_context() -> dict:
    return {"pnl": {"revenue": 123_456_789, "net_margin": 0.08, "gross_margin": 0.3, "ebitda": 9_000_000},
            "cashflow": {"operating": 5_000_000, "net": 1_000_000}}


def _think_result(env: SiteEnv):
    from app.services.reasoning_loop import ThinkResult

    return ThinkResult(
        observations=[f"{env.canary.counterparty} ödemesi {env.canary.iban_spaced} hesabına yapıldı"],
        uncertainties=[f"{env.canary.person} ile görüşme notu yok"], relevant_data={"revenue": 123_456_789},
        domain_focus="cfo",
    )


def _loop():
    """The loop's phases call the Model Gateway themselves (`complete` / `complete_text` with `max_tokens`).
    Before, they called `LLMTaskRouter.complete(..., max_tokens=)`, which raised TypeError in every phase and
    always fell back to the template; this driver needed an adapter then. Now it runs the loop as is."""
    from app.services.reasoning_loop import ReasoningLoop

    return ReasoningLoop()


async def _loop_think(env: SiteEnv) -> None:
    await _loop()._think(QUESTION, _loop_context(), "cfo")


async def _loop_plan(env: SiteEnv) -> None:
    await _loop()._plan(QUESTION, _think_result(env))


async def _loop_act(env: SiteEnv) -> None:
    from app.services.reasoning_loop import ActionResult, PlanStep

    prior = ActionResult(1, "ön adım", f"{env.canary.vendor} faturası incelendi", tool_used="llm")
    step = PlanStep(step_id=2, description=f"{env.canary.counterparty} bakiyesini yorumla", tool="llm")
    await _loop()._act(step, QUESTION, _loop_context(), _think_result(env), [prior])


async def _loop_synthesize(env: SiteEnv) -> None:
    from app.services.reasoning_loop import ActionResult, PlanResult, PlanStep

    plan = PlanResult(steps=[PlanStep(1, f"{env.canary.vendor} ödemesini incele", "llm")],
                      reasoning_approach=f"{env.canary.company} için doğrudan analiz")
    actions = [ActionResult(1, "incele", f"{env.canary.counterparty}: {env.description}", tool_used="llm")]
    await _loop()._synthesize(QUESTION, _think_result(env), plan, actions, "cfo")


# ── api/anomalies.py, api/ws_stream.py ───────────────────────────────────────

async def _explain_anomaly(env: SiteEnv) -> None:
    # The real endpoint function is called (no HTTP client): its `_generate` closure is the site, so the response's
    # body iterator is consumed to the end. The caller is the seeded owner, the anomaly cites the seeded transaction.
    from sqlalchemy import select

    from app.api.anomalies import explain_anomaly
    from app.models.anomaly import Anomaly
    from app.models.transaction import Transaction
    from app.models.user import User

    async with env.maker() as db:
        owner = (await db.execute(select(User).where(User.org_id == env.org_id))).scalars().first()
        tx = (await db.execute(select(Transaction))).scalars().first()
        anomaly = Anomaly(
            job_id=tx.job_id, anomaly_type="unusual_vendor", severity="high",
            title=f"{env.canary.counterparty} için olağandışı ödeme",
            description=f"{env.description}; {env.canary.company} hesabından çıkış",
            transaction_ids=[str(tx.id)],
            evidence={"vendor": env.canary.vendor, "iban": env.canary.iban_spaced, "z_score": 4.2},
        )
        db.add(anomaly)
        await db.flush()
        response = await explain_anomaly(anomaly.id, current_user=owner, db=db)
        async for _ in response.body_iterator:
            pass
        await db.rollback()


async def _ws_stream(env: SiteEnv) -> None:
    from app.api.ws_stream import _stream_llm_tokens

    async for _ in _stream_llm_tokens(
        prompt=f"{QUESTION}\n{env.description}",
        system_prompt=f"Sen {env.canary.company} için çalışan bir CFO asistanısın.",
        settings=None,
    ):
        pass


SITES: dict[str, Site] = {
    "scheduler.py::_generate_morning_brief_for_org": Site(
        _morning_brief, carries=False,
        note="the morning-brief prompt is built from ledger FIGURES only (morning_brief.llm_prompt: amounts, dates, "
             "alert counts); no counterparty, company or member text is ever formatted into it"),
    "services/accounting/thp_classifier.py::_llm_siniflandir": Site(_thp, reply="770"),
    "services/llm_structured.py::_structured": Site(
        _structured_llm, structured=_pnl_reply, off_raises=True,
        note="a thin helper: its contract is to propagate LLMUnavailable; the get_*_narrative callers catch it"),
    "services/llm_structured.py::call_llm": Site(_call_llm),
    "services/negotiation/boardroom.py::_structured": Site(
        _boardroom, structured=_boardroom_reply, off_raises=True,
        note="run_boardroom_debate refuses a debate without a model (raises LLMUnavailable); the helpers propagate it"),
    "services/rag/retriever.py::EmbeddingRagRetriever.retrieve": Site(_retriever),
    "services/reasoning_loop.py::ReasoningLoop._think": Site(_loop_think, reply=dumps({"observations": ["x"]})),
    "services/reasoning_loop.py::ReasoningLoop._plan": Site(
        _loop_plan, reply=dumps({"reasoning_approach": "a", "steps": [{"step_id": 1, "description": "d", "tool": "llm"}]})),
    "services/reasoning_loop.py::ReasoningLoop._act": Site(_loop_act),
    "services/reasoning_loop.py::ReasoningLoop._synthesize": Site(_loop_synthesize),
    "api/anomalies.py::explain_anomaly._generate": Site(_explain_anomaly),
    "api/ws_stream.py::_stream_llm_tokens": Site(
        _ws_stream, off_raises=True,
        note="the helper re-raises; the websocket handler turns it into an error frame for the client"),
}

ALIASED: dict[str, str] = {
    "services/llm_structured.py::_router_model_for":
        "covered by services/llm_structured.py::call_llm because it only selects a model id and sends no payload",
}
