"""
Boardroom (Ajanlar Arası Müzakere Motoru) - FAZ 1 & FAZ 2 (Hafıza Entegrasyonu)

Bu modül, farklı departman ajanlarının (CFO, CMO, COO vb.)
belirli bir konu üzerinde tartıştığı, geçmiş kararları hatırladığı
ve oy birliğine vardığı LLM tabanlı çok turlu müzakere altyapısını barındırır.
"""
from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from app.services.negotiation.boardroom_memory import get_boardroom_memory

logger = logging.getLogger(__name__)

# ── Pydantic Schemas ─────────────────────────────────────────────────────────

class BoardroomStatement(BaseModel):
    agent_name: str = Field(..., description="Ajan rolü, örn: 'CFO', 'CMO'")
    argument: str = Field(..., description="Ajanın argümanı (Türkçe)")
    proposed_solution: str = Field(..., description="Ajanın çözüm önerisi (Türkçe)")


class BoardroomConsensus(BaseModel):
    topic: str = Field(..., description="Müzakere konusu")
    resolution_status: str = Field(..., description="'Uzlaşıldı' veya 'CEO Kararı Bekleniyor'")
    final_decision: str = Field(..., description="Vardıkları nihai ortak karar (Türkçe)")
    confidence_score: float = Field(..., description="Uzlaşma derecesi (0.0 ile 1.0 arası)")
    action_items: list[str] = Field(..., description="Alınacak aksiyon adımları listesi (Türkçe)")


class BoardroomDebateResult(BaseModel):
    topic: str
    round_1_statements: list[BoardroomStatement]
    round_2_statements: list[BoardroomStatement]
    consensus: BoardroomConsensus
    debate_id: str | None = None


# ── LLM Helpers ──────────────────────────────────────────────────────────────

async def _structured(schema, prompt: str, *, temperature: float):
    from app.platform.model_gateway import complete
    res = await complete(
        task="deep_analysis", prompt=prompt, schema=schema, temperature=temperature,
    )
    return res.parsed


# ── Debate Engine ────────────────────────────────────────────────────────────

async def run_boardroom_debate(
    topic: str,
    context: str,
    agents: list[str] | None = None,
    org_id: str | None = None,
) -> BoardroomDebateResult:
    """
    Belirli bir konu (topic) üzerinde verilen ajanlar arasında LLM tabanlı
    2 turlu bir tartışma ve uzlaşı süreci yürütür. Geçmiş hafızayı enjekte eder ve sonucu kaydeder.
    """
    if agents is None:
        agents = ["CFO", "CMO"]
    from app.config import get_settings

    settings = get_settings()
    memory = get_boardroom_memory()

    # 0. Hafıza Katmanı: Geçmiş benzer kararları çek ve bağlama ekle
    past_memory_context = memory.get_past_context_for_topic(topic, org_id=org_id)
    enriched_context = f"{context}\n\n[KURUMSAL HAFIZA & GEÇMİŞ KARARLAR]:\n{past_memory_context}"

    # Fallback/Mock mode for local dev without a real API key
    if settings.openai_api_key.startswith("llm-placeholder"):
        result = _mock_boardroom_debate(topic, agents)
        rec = memory.save_debate(topic, context, agents, result, org_id=org_id)
        result.debate_id = rec.id
        return result

    # 1. Tur: Ajanların Açılış Beyanları (Paralel)
    tasks = []
    for agent in agents:
        tasks.append(_generate_opening_statement(agent, topic, enriched_context))

    round_1_results = await asyncio.gather(*tasks)

    # 2. Tur: Ajanların Birbirlerine Cevapları ve Orta Yol Önerileri
    round_1_summary = "\n".join([f"{r.agent_name}: {r.argument}" for r in round_1_results])
    tasks = []
    for agent in agents:
        tasks.append(_generate_response_statement(agent, topic, round_1_summary))

    round_2_results = await asyncio.gather(*tasks)

    # 3. Faz: Uzlaşı (Consensus)
    round_2_summary = "\n".join([f"{r.agent_name} önerisi: {r.proposed_solution}" for r in round_2_results])
    consensus = await _generate_consensus(topic, round_1_summary, round_2_summary)

    debate_res = BoardroomDebateResult(
        topic=topic,
        round_1_statements=round_1_results,
        round_2_statements=round_2_results,
        consensus=consensus
    )

    # 4. Hafızaya Kaydet
    saved_record = memory.save_debate(topic, context, agents, debate_res, org_id=org_id)
    debate_res.debate_id = saved_record.id

    return debate_res


async def _generate_opening_statement(agent: str, topic: str, context: str) -> BoardroomStatement:
    prompt = (
        f"Sen şirketin {agent} (Yönetim Kurulu Üyesi) rolündesin.\n"
        f"Konu: {topic}\n"
        f"Bağlam ve Şirket Hafızası:\n{context}\n\n"
        f"Kendi departmanının ve şirketin genel çıkarlarını gözeterek bu konudaki duruşunu net ve profesyonel bir dille açıkla."
    )
    result = await _structured(BoardroomStatement, prompt, temperature=0.7)
    result.agent_name = agent
    return result


async def _generate_response_statement(agent: str, topic: str, round_1_summary: str) -> BoardroomStatement:
    prompt = (
        f"Sen şirketin {agent} (Yönetim Kurulu Üyesi) rolündesin.\n"
        f"Konu: {topic}\n"
        f"İşte Yönetim Kurulundaki ilk tur tartışma:\n{round_1_summary}\n\n"
        f"Diğer ajanların argümanlarını değerlendir ve hem kendi hedeflerine hem de şirketin geneline uyan bir 'orta yol' çözüm önerisi sun."
    )
    result = await _structured(BoardroomStatement, prompt, temperature=0.7)
    result.agent_name = agent
    return result


async def _generate_consensus(topic: str, round_1_summary: str, round_2_summary: str) -> BoardroomConsensus:
    prompt = (
        f"Sen şirketin tarafsız Yönetim Kurulu Sekreterisin. Aşağıdaki tartışmayı analiz et ve nihai bir uzlaşı (consensus) metni çıkar.\n"
        f"Konu: {topic}\n"
        f"Tur 1 Argümanlar:\n{round_1_summary}\n"
        f"Tur 2 Öneriler:\n{round_2_summary}\n\n"
        f"Ortak bir karar metni ve uygulanabilir aksiyon listesi oluştur."
    )
    return await _structured(BoardroomConsensus, prompt, temperature=0.2)


def _mock_boardroom_debate(topic: str, agents: list[str]) -> BoardroomDebateResult:
    """LLM anahtarı olmadığında UI testi için dummy veri döner."""
    return BoardroomDebateResult(
        topic=topic,
        round_1_statements=[
            BoardroomStatement(
                agent_name="CMO",
                argument="Büyüme hedeflerini tutturmak için pazarlama bütçesini %30 artırmamız şart.",
                proposed_solution="Bütçe artışını 3 aya yayarak uygulayabiliriz."
            ),
            BoardroomStatement(
                agent_name="CFO",
                argument="Yaklaşan vergi ödemeleri var, nakit akışımız %30'luk anlık artışı kaldıramaz.",
                proposed_solution="Bu ay sadece %10 artış yapıp, nakit durumuna göre önümüzdeki ay tekrar değerlendirelim."
            )
        ],
        round_2_statements=[
            BoardroomStatement(
                agent_name="CMO",
                argument="CFO'nun nakit kaygısını anlıyorum, ancak momentumu kaybetmemeliyiz.",
                proposed_solution="Tamam, bu ay %15 artış yapalım, en yüksek ROI getiren kampanyalara odaklanalım."
            ),
            BoardroomStatement(
                agent_name="CFO",
                argument="Eğer sadece yüksek ROI kampanyalarına odaklanılacaksa, %15 bütçe esnemesini tolere edebiliriz.",
                proposed_solution="%15 artışa onay veriyorum, 15 gün sonra ROI raporu isterim."
            )
        ],
        consensus=BoardroomConsensus(
            topic=topic,
            resolution_status="Uzlaşıldı",
            final_decision="Pazarlama bütçesi bu ay %15 oranında artırılacak ve bütçe yüksek ROI sağlayan Google Ads kampanyalarına yönlendirilecek.",
            confidence_score=0.85,
            action_items=[
                "CFO: Bütçede %15'lik artış kalemi açılacak.",
                "CMO: Sadece yüksek dönüşüm sağlayan kampanyalara harcama yapılacak.",
                "CFO & CMO: 15 gün sonra ortak bir ara değerlendirme toplantısı yapılacak."
            ]
        )
    )
