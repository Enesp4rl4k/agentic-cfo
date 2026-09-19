"""
Reasoning Loop — "Think → Plan → Act" pattern for CFO agents.

Problem: Current agents call LLM directly with a big prompt and get a response.
This works but the model tends to skip reasoning steps, especially for:
  - Multi-step financial calculations
  - Cross-domain trade-off decisions
  - Questions with ambiguous data

Solution: ReAct-style (Reasoning + Acting) loop with explicit Think → Plan → Act phases.
Each phase is a separate LLM call with a focused prompt, making the reasoning
transparent, auditable, and higher quality.

Architecture
------------
Phase 1 — THINK:
  "Given the data, what do I know? What are the key facts? What is uncertain?"
  Output: ThinkResult (observations, uncertainties, relevant_data)

Phase 2 — PLAN:
  "What steps should I take to answer this question well?"
  Output: PlanResult (steps: list[str], tool_calls: list[str])

Phase 3 — ACT:
  Execute the plan: each step either calls a tool or calls LLM.
  Output: ActionResult per step

Phase 4 — SYNTHESIZE:
  Merge all action results into a coherent final answer.
  Output: str (the final narrative)

Token Budget Management
-----------------------
- THINK: max 300 tokens (observations only)
- PLAN: max 200 tokens (steps only)
- ACT per step: max 400 tokens
- SYNTHESIZE: max 800 tokens
Total: ~2000 tokens per reasoning loop (vs ~1500 direct) — worth the quality gain.

Usage
-----
    loop = ReasoningLoop(settings=get_settings())

    result = await loop.run(
        question="Pazarlama harcamam %20 artarsa nakit runway ne olur?",
        context=dashboard_dict,
        domain="cfo",
    )

    print(result.answer)         # final answer
    print(result.think.observations)  # reasoning trace
    print(result.plan.steps)     # execution plan
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class ThinkResult:
    """Output of the THINK phase."""
    observations: list[str]        # key facts extracted from context
    uncertainties: list[str]       # what we don't know / data gaps
    relevant_data: dict[str, Any]  # extracted numeric values
    domain_focus: str              # "cfo" | "cto" | "cross-domain" etc.
    duration_ms: int = 0

    def to_prompt_block(self) -> str:
        lines = ["### THINK PHASE OUTPUT"]
        lines.append("**Gözlemler:**")
        for o in self.observations:
            lines.append(f"- {o}")
        if self.uncertainties:
            lines.append("**Belirsizlikler:**")
            for u in self.uncertainties:
                lines.append(f"- {u}")
        if self.relevant_data:
            lines.append("**Anahtar Veriler:**")
            for k, v in self.relevant_data.items():
                lines.append(f"- {k}: {v}")
        return "\n".join(lines)


@dataclass
class PlanStep:
    """A single planned action."""
    step_id: int
    description: str
    tool: str | None = None        # "calculate" | "lookup" | "llm" | "summarise"
    input_keys: list[str] = field(default_factory=list)


@dataclass
class PlanResult:
    """Output of the PLAN phase."""
    steps: list[PlanStep]
    reasoning_approach: str        # brief description of strategy
    duration_ms: int = 0

    def to_prompt_block(self) -> str:
        lines = ["### PLAN PHASE OUTPUT", f"Strateji: {self.reasoning_approach}", "Adımlar:"]
        for s in self.steps:
            tool_note = f" [{s.tool}]" if s.tool else ""
            lines.append(f"  {s.step_id}. {s.description}{tool_note}")
        return "\n".join(lines)


@dataclass
class ActionResult:
    """Output of a single ACT step."""
    step_id: int
    description: str
    output: str
    tool_used: str | None = None
    duration_ms: int = 0
    ok: bool = True
    error: str | None = None

    def to_prompt_block(self) -> str:
        status = "✓" if self.ok else "✗"
        return f"  {status} Adım {self.step_id} ({self.description}): {self.output[:300]}"


@dataclass
class ReasoningResult:
    """Complete output of a full reasoning loop."""
    question: str
    answer: str
    think: ThinkResult
    plan: PlanResult
    actions: list[ActionResult]
    total_duration_ms: int
    domain: str
    confidence: float = 0.8

    def to_trace(self) -> dict[str, Any]:
        """Serializable trace for debugging/audit."""
        return {
            "question": self.question,
            "domain": self.domain,
            "think": {
                "observations": self.think.observations,
                "uncertainties": self.think.uncertainties,
                "relevant_data": self.think.relevant_data,
            },
            "plan": {
                "reasoning_approach": self.plan.reasoning_approach,
                "steps": [{"id": s.step_id, "desc": s.description, "tool": s.tool}
                          for s in self.plan.steps],
            },
            "actions": [
                {"step_id": a.step_id, "ok": a.ok, "output_preview": a.output[:100]}
                for a in self.actions
            ],
            "answer_preview": self.answer[:200],
            "total_duration_ms": self.total_duration_ms,
            "confidence": self.confidence,
        }


# ── Reasoning Loop ────────────────────────────────────────────────────────────

class ReasoningLoop:
    """
    Implements a structured Think → Plan → Act → Synthesize reasoning loop
    for CFO/C-Suite agent queries.

    Falls back gracefully to direct LLM call if any phase fails.
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings
        self._llm: Any = None  # lazy-initialised

    def _get_llm(self) -> Any:
        if self._llm is None:
            try:
                from app.services.llm_router import get_llm_router
                self._llm = get_llm_router()
            except Exception:
                pass
        return self._llm

    async def run(
        self,
        question: str,
        context: dict[str, Any],
        domain: str = "cfo",
        max_act_steps: int = 3,
        min_confidence: float = 0.5,
    ) -> ReasoningResult:
        """
        Execute the full reasoning loop.

        Parameters
        ----------
        question : str
            The user's question.
        context : dict
            Available data (dashboard, CFO results, C-Suite kernel outputs, etc.)
        domain : str
            Focus domain for context extraction.
        max_act_steps : int
            Maximum action steps to execute.
        min_confidence : float
            If think-phase confidence < this, add a disclaimer to the answer.
        """
        start_ms = int(time.time() * 1000)

        # Phase 1: THINK
        think = await self._think(question, context, domain)

        # Phase 2: PLAN
        plan = await self._plan(question, think)

        # Phase 3: ACT
        actions: list[ActionResult] = []
        for step in plan.steps[:max_act_steps]:
            action = await self._act(step, question, context, think, actions)
            actions.append(action)
            if not action.ok:
                break  # stop on critical failure

        # Phase 4: SYNTHESIZE
        answer = await self._synthesize(question, think, plan, actions, domain)

        total_ms = int(time.time() * 1000) - start_ms

        # Estimate confidence from think uncertainties
        confidence = max(0.3, 1.0 - len(think.uncertainties) * 0.15)

        if confidence < min_confidence:
            disclaimer = (
                "\n\n⚠️ *Not: Bu yanıt sınırlı veriye dayanmaktadır. "
                "Sonuçları bağımsız olarak doğrulamanız önerilir.*"
            )
            answer = answer + disclaimer

        return ReasoningResult(
            question=question,
            answer=answer,
            think=think,
            plan=plan,
            actions=actions,
            total_duration_ms=total_ms,
            domain=domain,
            confidence=confidence,
        )

    async def _think(
        self,
        question: str,
        context: dict[str, Any],
        domain: str,
    ) -> ThinkResult:
        """Phase 1: Extract observations and uncertainties from context."""
        t0 = int(time.time() * 1000)

        # Extract relevant data from context based on domain
        relevant_data = _extract_relevant_data(context, domain)

        prompt = f"""Sen bir CFO analist asistanısın. Aşağıdaki soruyu ve mevcut verileri analiz et.

SORU: {question}

MEVCUT VERİLER:
{json.dumps(relevant_data, ensure_ascii=False, indent=2)[:1500]}

Şu formatta yanıt ver (JSON):
{{
  "observations": ["gözlem1", "gözlem2", ...],  // 3-5 anahtar gözlem
  "uncertainties": ["belirsizlik1", ...],         // veri eksiklikleri
  "domain_focus": "cfo|cto|cmo|cross-domain",
  "key_numbers": {{"metrik_adı": değer}}           // hesaplama için gerekli sayılar
}}"""

        llm = self._get_llm()
        raw = ""
        if llm:
            try:
                raw = await llm.complete(task="think", prompt=prompt, max_tokens=400)
            except Exception as e:
                logger.debug("Think phase LLM call failed: %s", e)

        # Parse response
        observations: list[str] = []
        uncertainties: list[str] = []
        key_numbers: dict[str, Any] = {}
        parsed_domain = domain

        if raw:
            try:
                # Extract JSON block from response
                json_start = raw.find("{")
                json_end = raw.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    parsed = json.loads(raw[json_start:json_end])
                    observations = parsed.get("observations", [])
                    uncertainties = parsed.get("uncertainties", [])
                    key_numbers = parsed.get("key_numbers", {})
                    parsed_domain = parsed.get("domain_focus", domain)
            except Exception:
                pass

        # Fallback: generate observations from data
        if not observations:
            observations = _fallback_observations(relevant_data, question)

        return ThinkResult(
            observations=observations,
            uncertainties=uncertainties,
            relevant_data={**relevant_data, **key_numbers},
            domain_focus=parsed_domain,
            duration_ms=int(time.time() * 1000) - t0,
        )

    async def _plan(
        self,
        question: str,
        think: ThinkResult,
    ) -> PlanResult:
        """Phase 2: Create an execution plan."""
        t0 = int(time.time() * 1000)

        prompt = f"""Aşağıdaki soruyu yanıtlamak için adım adım bir plan oluştur.

SORU: {question}

{think.to_prompt_block()}

JSON formatında 2-4 adımlık plan:
{{
  "reasoning_approach": "kısa strateji açıklaması",
  "steps": [
    {{"step_id": 1, "description": "...", "tool": "calculate|lookup|llm|summarise"}},
    ...
  ]
}}"""

        llm = self._get_llm()
        raw = ""
        if llm:
            try:
                raw = await llm.complete(task="plan", prompt=prompt, max_tokens=300)
            except Exception as e:
                logger.debug("Plan phase LLM call failed: %s", e)

        steps: list[PlanStep] = []
        approach = "Doğrudan analiz"

        if raw:
            try:
                json_start = raw.find("{")
                json_end = raw.rfind("}") + 1
                if json_start >= 0:
                    parsed = json.loads(raw[json_start:json_end])
                    approach = parsed.get("reasoning_approach", approach)
                    for s in parsed.get("steps", []):
                        steps.append(PlanStep(
                            step_id=s.get("step_id", len(steps) + 1),
                            description=s.get("description", ""),
                            tool=s.get("tool"),
                        ))
            except Exception:
                pass

        # Fallback plan
        if not steps:
            steps = _fallback_plan(question, think)

        return PlanResult(
            steps=steps,
            reasoning_approach=approach,
            duration_ms=int(time.time() * 1000) - t0,
        )

    async def _act(
        self,
        step: PlanStep,
        question: str,
        context: dict[str, Any],
        think: ThinkResult,
        prior_actions: list[ActionResult],
    ) -> ActionResult:
        """Phase 3: Execute a single plan step."""
        t0 = int(time.time() * 1000)

        tool = step.tool or "llm"

        try:
            if tool == "calculate":
                output = _execute_calculation(step, think.relevant_data)
            elif tool == "lookup":
                output = _execute_lookup(step, context)
            else:
                # LLM-based step
                prior_outputs = "\n".join(
                    f"Adım {a.step_id}: {a.output[:200]}" for a in prior_actions
                )
                prior_block = f"ÖNCEKİ ADIMLAR:\n{prior_outputs}" if prior_outputs else ""
                prompt = f"""Soruya yanıt vermenin bir parçası olarak şu adımı gerçekleştir:

ADIM: {step.description}
SORU: {question}
{think.to_prompt_block()}
{prior_block}

Kısa ve somut yanıt ver (max 3 cümle):"""

                llm = self._get_llm()
                output = ""
                if llm:
                    output = await llm.complete(
                        task="act_step",
                        prompt=prompt,
                        max_tokens=400,
                    )
                output = output or f"{step.description} tamamlandı."

            return ActionResult(
                step_id=step.step_id,
                description=step.description,
                output=output,
                tool_used=tool,
                duration_ms=int(time.time() * 1000) - t0,
                ok=True,
            )

        except Exception as e:
            return ActionResult(
                step_id=step.step_id,
                description=step.description,
                output="",
                tool_used=tool,
                duration_ms=int(time.time() * 1000) - t0,
                ok=False,
                error=str(e),
            )

    async def _synthesize(
        self,
        question: str,
        think: ThinkResult,
        plan: PlanResult,
        actions: list[ActionResult],
        domain: str,
    ) -> str:
        """Phase 4: Synthesize all results into a coherent final answer."""
        # Build synthesis context
        think_block = think.to_prompt_block()
        plan_block = plan.to_prompt_block()
        action_block = "\n".join(a.to_prompt_block() for a in actions if a.ok)

        prompt = f"""Aşağıdaki analiz adımlarını bir araya getirerek soruya kapsamlı bir yanıt ver.

SORU: {question}

{think_block}

{plan_block}

### ACT PHASE OUTPUTS
{action_block or "(Eylem adımları yürütülmedi)"}

Yanıt kriterleri:
- Türkçe, net ve somut ol
- Anahtar sayıları ve metrikleri dahil et
- 1-3 somut öneri ekle
- Maksimum 4 paragraf"""

        llm = self._get_llm()
        if not llm:
            # Fallback: concatenate action outputs
            outputs = [a.output for a in actions if a.ok and a.output]
            return "\n\n".join(outputs) if outputs else "Analiz tamamlandı, ancak LLM yanıt üretemedi."

        try:
            answer = await llm.complete(
                task="synthesize",
                prompt=prompt,
                max_tokens=800,
            )
            return answer or "Yanıt üretilemedi."
        except Exception as e:
            logger.warning("Synthesize phase failed: %s", e)
            # Fallback: join action outputs
            outputs = [a.output for a in actions if a.ok and a.output]
            return "\n\n".join(outputs) if outputs else "Analiz yürütüldü ancak sonuç sentezlenemedi."


# ── Helper functions ──────────────────────────────────────────────────────────

def _extract_relevant_data(context: dict[str, Any], domain: str) -> dict[str, Any]:
    """Extract domain-specific numeric data from context dict."""
    result: dict[str, Any] = {}

    # Always include CFO basics
    pnl = context.get("pnl") or {}
    cf = context.get("cashflow") or {}
    forecast = context.get("forecast") or {}

    if pnl:
        result["revenue"] = pnl.get("revenue")
        result["net_margin"] = pnl.get("net_margin")
        result["gross_margin"] = pnl.get("gross_margin")
        result["ebitda"] = pnl.get("ebitda")

    if cf:
        result["operating_cashflow"] = cf.get("operating")
        result["net_cashflow"] = cf.get("net")

    # Forecast
    scenarios = (forecast.get("scenarios") or {})
    base = scenarios.get("base") or {}
    if base:
        result["runway_months"] = base.get("runway_months")

    # Domain-specific
    if domain in ("cto", "all"):
        cto = context.get("_cto_result") or {}
        summary = cto.get("cto_summary") or {}
        result["tech_health_score"] = summary.get("overall_health_score")
        infra = cto.get("infra") or {}
        result["infra_cost"] = infra.get("total_cost_cents", 0)

    if domain in ("cmo", "all"):
        cmo = context.get("_cmo_result") or {}
        campaigns = cmo.get("campaigns") or {}
        result["roas"] = campaigns.get("overall_roas")
        result["cac_cents"] = campaigns.get("blended_cac_cents")

    # Remove None values
    return {k: v for k, v in result.items() if v is not None}


def _fallback_observations(data: dict[str, Any], question: str) -> list[str]:
    """Generate basic observations when LLM is unavailable."""
    obs = []
    if data.get("revenue"):
        obs.append(f"Gelir: {data['revenue']:,.0f} TRY")
    if data.get("net_margin") is not None:
        obs.append(f"Net marj: {data['net_margin'] * 100:.1f}%")
    if data.get("runway_months"):
        obs.append(f"Nakit runway: {data['runway_months']} ay")
    if not obs:
        obs.append("Analiz için yeterli finansal veri mevcut değil.")
    return obs


def _fallback_plan(question: str, think: ThinkResult) -> list[PlanStep]:
    """Generate a minimal 2-step plan when LLM is unavailable."""
    return [
        PlanStep(step_id=1, description="Mevcut verileri analiz et", tool="lookup"),
        PlanStep(step_id=2, description="Sonuçları özetle ve öneri sun", tool="llm"),
    ]


def _execute_calculation(step: PlanStep, data: dict[str, Any]) -> str:
    """Execute simple numeric calculations from available data."""
    desc = step.description.lower()
    results = []

    if "margin" in desc or "marj" in desc:
        rev = data.get("revenue", 0)
        ebitda = data.get("ebitda", 0)
        if rev:
            margin = ebitda / rev * 100
            results.append(f"FAVÖK Marjı: {margin:.1f}%")

    if "runway" in desc or "nakit" in desc:
        runway = data.get("runway_months")
        if runway:
            results.append(f"Nakit Runway: {runway} ay")

    if "cac" in desc:
        cac = data.get("cac_cents", 0)
        if cac:
            results.append(f"CAC: {cac / 100:,.0f} TRY")

    return ", ".join(results) if results else "Hesaplama için yeterli veri yok."


def _execute_lookup(step: PlanStep, context: dict[str, Any]) -> str:
    """Look up data from context dictionary."""
    desc = step.description.lower()
    findings = []

    # Simple keyword-based lookup
    if "alert" in desc or "uyarı" in desc:
        alerts = context.get("anomalies") or []
        if alerts:
            findings.append(f"{len(alerts)} aktif anomali/uyarı mevcut")

    if "forecast" in desc or "tahmin" in desc:
        forecast = context.get("forecast") or {}
        scenarios = forecast.get("scenarios") or {}
        base = scenarios.get("base") or {}
        if base.get("revenue_12m"):
            findings.append(f"12 aylık gelir tahmini: {base['revenue_12m']:,.0f} TRY")

    return ", ".join(findings) if findings else "İlgili veri bulunamadı."


# ── Module singleton ──────────────────────────────────────────────────────────

_reasoning_loop: ReasoningLoop | None = None


def get_reasoning_loop() -> ReasoningLoop:
    global _reasoning_loop
    if _reasoning_loop is None:
        try:
            from app.config import get_settings
            _reasoning_loop = ReasoningLoop(settings=get_settings())
        except Exception:
            _reasoning_loop = ReasoningLoop()
    return _reasoning_loop
