"""
Agent Message Bus — Ajan Iletisim Agi

Sistemin sinir sistemi. Agent'larin birbirleriyle gercek zamanli
iletisim kurmalarini saglar.

Mimari:
  - AgentMessage: tip guvenceli mesaj schemasi
  - AgentBus: Redis pub/sub uzerinden async mesajlasma
  - InMemoryBus: test/dev icin Redis gerektirmeyen fallback
  - Negotiation pattern: soru sor → bekle → cevap al

Desteklenen mesaj tipleri:
  query        : baska bir agent'a soru sor (cevap bekler)
  response     : query'e cevap
  broadcast    : tum agent'lara duyuru (cevap beklemiyor)
  alert        : kritik durum bildirimi
  data_request : baska agent'tan veri talep et
  data_response: data_request'e cevap

Akis ornegi:
  CFO detects: cash runway = 2.1 months
  CFO → CHRO: "Onumuzdeki 3 ayda kac yeni ise alim planlanıyor?"
  CHRO → CFO: {"planned_hires": 3, "monthly_cost": 135000}
  CFO recalculates: revised_runway = 1.6 months (daha kritik!)
  CFO → CEO: broadcast "Kritik: revize senaryo hazır"

Kullanim:
    bus = get_agent_bus()
    
    # Soru sor, cevap bekle (max 10 saniye)
    response = await bus.ask(
        from_agent="cfo",
        to_agent="chro", 
        query_type="hiring_plan",
        payload={"months_ahead": 3},
        timeout=10.0,
    )
    
    # Dinle (agent tarafinda)
    async for message in bus.listen("chro"):
        if message.query_type == "hiring_plan":
            await bus.reply(message, payload={"planned_hires": 3})
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


# ── Mesaj schemasi ────────────────────────────────────────────────────────────

@dataclass
class AgentMessage:
    """Agent'lar arasi mesaj."""
    msg_id:     str
    msg_type:   str          # query | response | broadcast | alert | data_request | data_response
    from_agent: str          # "cfo" | "chro" | "cto" | "cmo" | "coo" | "risk" | "ceo"
    to_agent:   str          # hedef agent veya "all" (broadcast)
    query_type: str          # "hiring_plan" | "tech_budget" | "cash_runway" | ...
    payload:    dict[str, Any]
    org_id:     str
    job_id:     str | None   = None
    reply_to:   str | None   = None   # hangi msg_id'ye cevap
    created_at: float        = field(default_factory=time.time)
    ttl:        float        = 30.0   # saniye, bu sure sonra expire

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> "AgentMessage":
        d = json.loads(data)
        return cls(**d)

    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl

    def make_response(self, payload: dict[str, Any], from_agent: str) -> "AgentMessage":
        """Bu mesaja cevap olustur."""
        return AgentMessage(
            msg_id     = str(uuid.uuid4()),
            msg_type   = "response",
            from_agent = from_agent,
            to_agent   = self.from_agent,
            query_type = self.query_type,
            payload    = payload,
            org_id     = self.org_id,
            job_id     = self.job_id,
            reply_to   = self.msg_id,
        )


# ── In-Memory Bus (test/dev) ──────────────────────────────────────────────────

class InMemoryBus:
    """
    Redis gerektirmeyen in-memory mesaj kutusu.
    Test ve gelistirme icin. Production'da RedisAgentBus kullanin.
    """

    def __init__(self) -> None:
        # agent_name → asyncio.Queue
        self._queues: dict[str, asyncio.Queue[AgentMessage]] = {}
        # msg_id → Future (query/response eslestirme icin)
        self._pending: dict[str, asyncio.Future[AgentMessage]] = {}

    def _get_queue(self, agent: str) -> asyncio.Queue[AgentMessage]:
        if agent not in self._queues:
            self._queues[agent] = asyncio.Queue(maxsize=100)
        return self._queues[agent]

    async def publish(self, message: AgentMessage) -> None:
        """Mesaj yayinla."""
        if message.to_agent == "all":
            # Broadcast: tum agent kuyruklarina ekle
            for q in self._queues.values():
                try:
                    q.put_nowait(message)
                except asyncio.QueueFull:
                    logger.warning("Queue full for broadcast, dropping message")
        else:
            q = self._get_queue(message.to_agent)
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("Queue full for agent %s", message.to_agent)

        # Response ise bekleyen Future'i coz
        if message.msg_type == "response" and message.reply_to:
            fut = self._pending.get(message.reply_to)
            if fut and not fut.done():
                fut.set_result(message)

    async def ask(
        self,
        from_agent: str,
        to_agent:   str,
        query_type: str,
        payload:    dict[str, Any],
        org_id:     str,
        job_id:     str | None = None,
        timeout:    float = 10.0,
    ) -> AgentMessage | None:
        """
        Soru sor ve cevabi bekle.
        Returns None if timeout veya error.
        """
        msg = AgentMessage(
            msg_id     = str(uuid.uuid4()),
            msg_type   = "query",
            from_agent = from_agent,
            to_agent   = to_agent,
            query_type = query_type,
            payload    = payload,
            org_id     = org_id,
            job_id     = job_id,
        )

        # Cevap beklemek icin Future olustur
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[AgentMessage] = loop.create_future()
        self._pending[msg.msg_id] = fut

        try:
            await self.publish(msg)
            response = await asyncio.wait_for(fut, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            logger.debug("Agent query timeout: %s → %s (%s)", from_agent, to_agent, query_type)
            return None
        except Exception as exc:
            logger.warning("Agent query error: %s", exc)
            return None
        finally:
            self._pending.pop(msg.msg_id, None)

    async def reply(self, original: AgentMessage, payload: dict[str, Any], from_agent: str) -> None:
        """Gelen mesaja cevap ver."""
        response = original.make_response(payload=payload, from_agent=from_agent)
        await self.publish(response)

    async def broadcast(
        self,
        from_agent: str,
        query_type: str,
        payload:    dict[str, Any],
        org_id:     str,
        job_id:     str | None = None,
    ) -> None:
        """Tum agent'lara duyuru yap."""
        msg = AgentMessage(
            msg_id     = str(uuid.uuid4()),
            msg_type   = "broadcast",
            from_agent = from_agent,
            to_agent   = "all",
            query_type = query_type,
            payload    = payload,
            org_id     = org_id,
            job_id     = job_id,
        )
        await self.publish(msg)

    async def listen(
        self,
        agent:   str,
        timeout: float = 0.1,
    ) -> AsyncIterator[AgentMessage]:
        """Agent kuyrugundan mesajlari oku."""
        q = self._get_queue(agent)
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=timeout)
                if not msg.is_expired():
                    yield msg
            except asyncio.TimeoutError:
                break

    async def drain(self, agent: str) -> list[AgentMessage]:
        """Agent kuyrugundan tum bekleyen mesajlari al."""
        q   = self._get_queue(agent)
        msgs: list[AgentMessage] = []
        while not q.empty():
            try:
                msg = q.get_nowait()
                if not msg.is_expired():
                    msgs.append(msg)
            except asyncio.QueueEmpty:
                break
        return msgs


# ── Redis Bus (production) ─────────────────────────────────────────────────────

class RedisAgentBus:
    """
    Redis pub/sub uzerinden agent mesajlasma.
    Production icin InMemoryBus yerine bu kullanilmali.
    
    Redis channel naming:
      agent:{agent_name}:{org_id}  → tek agent'a mesaj
      agent:all:{org_id}           → broadcast
      agent:response:{msg_id}      → query response
    """

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis_url = redis_url
        self._redis: Any = None
        self._pubsub: Any = None

    async def _get_redis(self) -> Any:
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = await aioredis.from_url(self._redis_url, decode_responses=True)
            except ImportError:
                raise RuntimeError("redis paketi yuklenmemis. pip install redis")
        return self._redis

    async def publish(self, message: AgentMessage) -> None:
        redis = await self._get_redis()
        data  = message.to_json()

        if message.to_agent == "all":
            channel = f"agent:all:{message.org_id}"
        else:
            channel = f"agent:{message.to_agent}:{message.org_id}"

        await redis.publish(channel, data)

        # Response channel'ine da yayinla (ask/wait icin)
        if message.msg_type == "response" and message.reply_to:
            await redis.publish(f"agent:response:{message.reply_to}", data)

    async def ask(
        self,
        from_agent: str,
        to_agent:   str,
        query_type: str,
        payload:    dict[str, Any],
        org_id:     str,
        job_id:     str | None = None,
        timeout:    float = 10.0,
    ) -> AgentMessage | None:
        redis = await self._get_redis()

        msg = AgentMessage(
            msg_id     = str(uuid.uuid4()),
            msg_type   = "query",
            from_agent = from_agent,
            to_agent   = to_agent,
            query_type = query_type,
            payload    = payload,
            org_id     = org_id,
            job_id     = job_id,
        )

        # Cevap kanalini dinle
        pubsub = redis.pubsub()
        response_channel = f"agent:response:{msg.msg_id}"
        await pubsub.subscribe(response_channel)

        try:
            await self.publish(msg)

            deadline = time.time() + timeout
            while time.time() < deadline:
                data = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if data and data.get("type") == "message":
                    try:
                        response = AgentMessage.from_json(data["data"])
                        if not response.is_expired():
                            return response
                    except Exception:
                        continue
            return None
        finally:
            await pubsub.unsubscribe(response_channel)
            await pubsub.close()

    async def reply(self, original: AgentMessage, payload: dict[str, Any], from_agent: str) -> None:
        response = original.make_response(payload=payload, from_agent=from_agent)
        await self.publish(response)

    async def broadcast(
        self,
        from_agent: str,
        query_type: str,
        payload:    dict[str, Any],
        org_id:     str,
        job_id:     str | None = None,
    ) -> None:
        msg = AgentMessage(
            msg_id     = str(uuid.uuid4()),
            msg_type   = "broadcast",
            from_agent = from_agent,
            to_agent   = "all",
            query_type = query_type,
            payload    = payload,
            org_id     = org_id,
            job_id     = job_id,
        )
        await self.publish(msg)

    async def listen(self, agent: str, org_id: str) -> AsyncIterator[AgentMessage]:
        redis  = await self._get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(
            f"agent:{agent}:{org_id}",
            f"agent:all:{org_id}",
        )
        try:
            async for data in pubsub.listen():
                if data.get("type") == "message":
                    try:
                        msg = AgentMessage.from_json(data["data"])
                        if not msg.is_expired():
                            yield msg
                    except Exception:
                        continue
        finally:
            await pubsub.close()


# ── Global singleton + factory ────────────────────────────────────────────────

_bus_instance: InMemoryBus | RedisAgentBus | None = None


def get_agent_bus(use_redis: bool = False, redis_url: str = "redis://localhost:6379") -> InMemoryBus | RedisAgentBus:
    """
    Global agent bus singleton al.

    Gelistirme/test: InMemoryBus (Redis gerektirmez)
    Production:      RedisAgentBus (AGENT_BUS_REDIS=true env var)
    """
    global _bus_instance
    if _bus_instance is None:
        import os
        use_redis = use_redis or os.environ.get("AGENT_BUS_REDIS", "").lower() == "true"
        if use_redis:
            url = os.environ.get("REDIS_URL", redis_url)
            _bus_instance = RedisAgentBus(redis_url=url)
            logger.info("AgentBus: Redis backend (%s)", url)
        else:
            _bus_instance = InMemoryBus()
            logger.info("AgentBus: InMemory backend (dev mode)")
    return _bus_instance


def reset_agent_bus() -> None:
    """Test isolation icin bus'u sifirla."""
    global _bus_instance
    _bus_instance = None


# ── Query type constants ──────────────────────────────────────────────────────

class QueryType:
    """Standart query type sabitleri."""
    # CFO → CHRO
    HIRING_PLAN        = "hiring_plan"         # Kac ise alim planlanıyor?
    SALARY_FORECAST    = "salary_forecast"     # Maas gideri tahmini nedir?
    ATTRITION_RISK     = "attrition_risk"      # Attrition riski nedir?
    HEADCOUNT_IMPACT   = "headcount_impact"    # Kadro degisimi nakit etkisi?

    # CFO → CTO
    TECH_BUDGET_CUT    = "tech_budget_cut"     # Tech butce kesilebilir mi?
    VELOCITY_IMPACT    = "velocity_impact"     # Butce kesintisi velocity'yi etkiler mi?
    CLOUD_SAVINGS      = "cloud_savings"       # Cloud optimizasyondan tasarruf?
    INFRA_COST         = "infra_cost"          # Altyapi maliyeti nedir?

    # CFO → CMO
    MARKETING_ROI      = "marketing_roi"       # Pazarlama ROI'si nedir?
    CAC_TREND          = "cac_trend"           # CAC trendi nasil?
    REVENUE_FORECAST   = "revenue_forecast"    # Gelir tahmini nedir?

    # CEO → All
    STRATEGIC_STATUS   = "strategic_status"   # Stratejik durum nedir?
    RISK_ASSESSMENT    = "risk_assessment"     # Risk degerlendirmen nedir?
    BOARD_BRIEF        = "board_brief"         # Board brief icin ozet?

    # Broadcast types
    CASH_CRISIS        = "cash_crisis"         # Nakit krizi bildirimi
    SCENARIO_UPDATE    = "scenario_update"     # Senaryo guncellendi
    KRI_BREACH         = "kri_breach"          # KRI ihlali
