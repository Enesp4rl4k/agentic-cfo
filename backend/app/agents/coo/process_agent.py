"""
COO Process Agent -- COO Skill 1 of 3.

Responsibility: Parse business process CSV and compute cycle time,
throughput, WIP (Work in Progress), efficiency using Little's Law,
and bottleneck detection.

Enhancements:
- Theory of Constraints (ToC) bottleneck root cause analysis
- Constraint classification: capacity / dependency / quality / variability
- Drum-Buffer-Rope throughput analysis
- Türkçe alerts and narrative
- LLM narrative in Turkish

Little's Law: WIP = Throughput x Cycle_Time
Efficiency: actual_output / theoretical_max_output

Supported CSV formats (flexible column detection):
  - Generic: process/name, cycle_time/duration_days, throughput/weekly_output,
             wip/in_progress, team/department, status, error_rate, dependencies

done_when: state['processes']['efficiency_score'] is a float
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

from app.agents.coo.state import COOState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Theory of Constraints — constraint type classification
# ---------------------------------------------------------------------------

_CONSTRAINT_TYPES = {
    "capacity":    "Kapasite Kısıtı",
    "dependency":  "Bağımlılık Kısıtı",
    "quality":     "Kalite/Yeniden İşleme Kısıtı",
    "variability": "Değişkenlik Kısıtı",
    "policy":      "Politika/Prosedür Kısıtı",
}

_TOC_STEPS = [
    "1. Kısıtı tanımla",
    "2. Kısıtı maksimuma zorla (exploit)",
    "3. Her şeyi kısıta tabi kıl (subordinate)",
    "4. Kısıtı kaldır (elevate)",
    "5. Döngüyü tekrarla",
]


def _classify_constraint(process: dict[str, Any], avg_cycle: float) -> str:
    """Classify the constraint type for a bottleneck process using ToC heuristics."""
    cycle   = process.get("cycle_time", 0.0)
    wip     = process.get("wip", 0.0)
    tp      = process.get("throughput", 0.0)
    cap     = process.get("capacity", 0.0)
    err     = process.get("error_rate", 0.0)
    deps    = process.get("dependencies", 0)

    # Quality / rework constraint: high error rate drives rework cycles
    if err > 0.15:
        return "quality"
    # Dependency constraint: many upstream dependencies stall the process
    if deps >= 3:
        return "dependency"
    # Capacity constraint: throughput << capacity, or overloaded WIP
    if cap > 0 and tp < cap * 0.6:
        return "capacity"
    if tp > 0 and wip / tp > 4:
        return "capacity"
    # Variability: cycle time far exceeds average (>2×)
    if avg_cycle > 0 and cycle > avg_cycle * 2:
        return "variability"
    # Default: policy/procedure bottleneck
    return "policy"


def _toc_recommendation(constraint_type: str, process_name: str) -> str:
    """Generate a ToC-based recommendation in Turkish."""
    recs = {
        "capacity": (
            f"'{process_name}' kapasite kısıtı altında. "
            "Ek kaynak tahsis et veya paralel işleme geç; WIP limitini düşür."
        ),
        "dependency": (
            f"'{process_name}' çok sayıda upstream bağımlılık nedeniyle bekliyor. "
            "Bağımlılık haritası çıkar; kritik yoldaki engelleri kaldır."
        ),
        "quality": (
            f"'{process_name}' yüksek hata oranı nedeniyle yeniden işleme döngüsünde. "
            "Kalite kontrol noktasını sürecin başına al (shift-left)."
        ),
        "variability": (
            f"'{process_name}' döngü süresi tutarsız — aşırı değişkenlik var. "
            "Standardize edilmiş çalışma talimatları ve buffer stock tanımla."
        ),
        "policy": (
            f"'{process_name}' onay/politika adımlarında tıkanıyor. "
            "Delegasyon matrisini gözden geçir; gereksiz onay adımlarını kaldır."
        ),
    }
    return recs.get(constraint_type, f"'{process_name}' sürecinde kısıt analizi gerekli.")


# ---------------------------------------------------------------------------
# CSV Parser
# ---------------------------------------------------------------------------

def _parse_process_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse process CSV -- flexible column detection."""
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    rows: list[dict[str, Any]] = []

    def _col(*candidates: str) -> str | None:
        for c in candidates:
            for k in (reader.fieldnames or []):
                if k.strip().lower().replace(" ", "_").replace("-", "_") == \
                   c.lower().replace(" ", "_"):
                    return k
        return None

    name_col       = _col("process", "name", "process_name", "workflow", "task")
    cycle_col      = _col("cycle_time", "duration_days", "avg_cycle_days",
                          "lead_time_days", "cycle_time_days")
    throughput_col = _col("throughput", "weekly_output", "output_per_week",
                          "completed_per_week", "velocity")
    wip_col        = _col("wip", "in_progress", "active_items",
                          "work_in_progress", "backlog")
    team_col       = _col("team", "department", "owner", "squad")
    capacity_col   = _col("capacity", "max_throughput", "max_output",
                          "theoretical_throughput")
    error_col      = _col("error_rate", "rework_rate", "defect_rate",
                          "failure_rate", "error_pct")
    deps_col       = _col("dependencies", "upstream_deps", "blockers",
                          "dependency_count", "depends_on")

    for i, row in enumerate(reader):
        name       = (row.get(name_col) or f"Süreç {i+1}").strip() if name_col else f"Süreç {i+1}"
        team       = (row.get(team_col) or "belirsiz").strip() if team_col else "belirsiz"
        cycle_time = 0.0
        throughput = 0.0
        wip        = 0.0
        capacity   = 0.0
        error_rate = 0.0
        dependencies = 0

        try:
            cycle_time = float((row.get(cycle_col) or "0").replace(",", "")) if cycle_col else 0.0
        except (ValueError, TypeError):
            pass
        try:
            throughput = float((row.get(throughput_col) or "0").replace(",", "")) if throughput_col else 0.0
        except (ValueError, TypeError):
            pass
        try:
            wip = float((row.get(wip_col) or "0").replace(",", "")) if wip_col else 0.0
        except (ValueError, TypeError):
            pass
        try:
            capacity = float((row.get(capacity_col) or "0").replace(",", "")) if capacity_col else 0.0
        except (ValueError, TypeError):
            pass
        try:
            raw_err = (row.get(error_col) or "0").replace(",", "").replace("%", "") if error_col else "0"
            error_rate = float(raw_err)
            if error_rate > 1.0:  # stored as percentage
                error_rate /= 100.0
        except (ValueError, TypeError):
            pass
        try:
            dependencies = int(float((row.get(deps_col) or "0").replace(",", ""))) if deps_col else 0
        except (ValueError, TypeError):
            pass

        # Little's Law: if WIP missing, estimate from throughput * cycle_time
        if wip == 0.0 and throughput > 0 and cycle_time > 0:
            wip = throughput * (cycle_time / 7.0)

        rows.append({
            "name":         name,
            "team":         team,
            "cycle_time":   cycle_time,    # days
            "throughput":   throughput,    # per week
            "wip":          wip,           # items
            "capacity":     capacity,      # max throughput per week
            "error_rate":   error_rate,    # fraction 0-1
            "dependencies": dependencies,  # count
        })

    return rows


# ---------------------------------------------------------------------------
# Pure Calculations
# ---------------------------------------------------------------------------

def _compute_process_metrics(processes: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation -- no LLM."""
    if not processes:
        return {
            "total_processes":         0,
            "avg_cycle_time_days":     0.0,
            "avg_throughput_per_week": 0.0,
            "avg_wip":                 0.0,
            "bottleneck_process":      None,
            "bottleneck_constraint":   None,
            "bottleneck_recommendation": None,
            "toc_analysis":            [],
            "efficiency_score":        0.0,
            "by_process":              {},
            "overloaded_processes":    [],
            "alerts":                  [],
            "narrative":               "",
        }

    cycle_times = [p["cycle_time"] for p in processes if p["cycle_time"] > 0]
    throughputs = [p["throughput"] for p in processes if p["throughput"] > 0]
    wips        = [p["wip"] for p in processes if p["wip"] > 0]

    avg_cycle = sum(cycle_times) / len(cycle_times) if cycle_times else 0.0
    avg_tp    = sum(throughputs) / len(throughputs) if throughputs else 0.0
    avg_wip   = sum(wips) / len(wips) if wips else 0.0

    # Efficiency per process
    by_process: dict[str, Any] = {}
    for p in processes:
        eff = 0.0
        if p["capacity"] > 0 and p["throughput"] > 0:
            eff = min(1.0, p["throughput"] / p["capacity"])
        elif p["throughput"] > 0 and avg_cycle > 0:
            eff = min(1.0, avg_cycle / max(p["cycle_time"], 0.001))

        wip_ratio = (p["wip"] / p["throughput"]) if p["throughput"] > 0 else 0.0
        constraint_type = _classify_constraint(p, avg_cycle)

        by_process[p["name"]] = {
            "team":            p["team"],
            "cycle_time":      p["cycle_time"],
            "throughput":      p["throughput"],
            "wip":             p["wip"],
            "capacity":        p["capacity"],
            "error_rate":      round(p["error_rate"], 3),
            "dependencies":    p["dependencies"],
            "efficiency":      round(eff, 3),
            "wip_ratio":       round(wip_ratio, 2),
            "constraint_type": constraint_type,
            "constraint_label": _CONSTRAINT_TYPES.get(constraint_type, constraint_type),
        }

    # Bottleneck: process with longest cycle time (primary ToC constraint)
    bottleneck_proc = None
    bottleneck_constraint = None
    bottleneck_recommendation = None
    toc_analysis: list[dict[str, Any]] = []

    if cycle_times:
        bn = max(processes, key=lambda p: p["cycle_time"])
        bottleneck_proc = bn["name"]
        bottleneck_constraint = _classify_constraint(bn, avg_cycle)
        bottleneck_recommendation = _toc_recommendation(bottleneck_constraint, bn["name"])

        # Full ToC analysis for top 3 slowest processes
        sorted_procs = sorted(processes, key=lambda p: p["cycle_time"], reverse=True)
        for rank, p in enumerate(sorted_procs[:3], 1):
            c_type = _classify_constraint(p, avg_cycle)
            toc_analysis.append({
                "rank":               rank,
                "process":            p["name"],
                "team":               p["team"],
                "cycle_time_days":    p["cycle_time"],
                "constraint_type":    c_type,
                "constraint_label":   _CONSTRAINT_TYPES.get(c_type, c_type),
                "toc_recommendation": _toc_recommendation(c_type, p["name"]),
                "throughput_loss_pct": round(
                    max(0.0, (p["cycle_time"] - avg_cycle) / max(avg_cycle, 0.001)) * 100, 1
                ),
            })

    # Overloaded: WIP ratio > 4 weeks
    overloaded = [
        {
            "name":       p["name"],
            "team":       p["team"],
            "wip":        p["wip"],
            "cycle_time": p["cycle_time"],
            "reason":     (
                f"WIP {p['wip']:.0f} iş kalemi, {p['throughput']:.1f}/hafta çıktı "
                f"= {p['wip'] / max(p['throughput'], 0.01):.1f} hafta birikimi"
            ),
        }
        for p in processes
        if p["throughput"] > 0 and (p["wip"] / p["throughput"]) > 4
    ]

    # Overall efficiency score (0-10 penalty; lower = better)
    eff_vals = [v["efficiency"] for v in by_process.values() if v["efficiency"] > 0]
    avg_eff  = sum(eff_vals) / len(eff_vals) if eff_vals else 0.5
    efficiency_score = round(max(0.0, min(10.0, (1.0 - avg_eff) * 10)), 1)

    return {
        "total_processes":            len(processes),
        "avg_cycle_time_days":        round(avg_cycle, 1),
        "avg_throughput_per_week":    round(avg_tp, 1),
        "avg_wip":                    round(avg_wip, 1),
        "bottleneck_process":         bottleneck_proc,
        "bottleneck_constraint":      bottleneck_constraint,
        "bottleneck_constraint_label": _CONSTRAINT_TYPES.get(bottleneck_constraint or "", ""),
        "bottleneck_recommendation":  bottleneck_recommendation,
        "toc_analysis":               toc_analysis,
        "toc_steps":                  _TOC_STEPS,
        "efficiency_score":           efficiency_score,
        "by_process":                 by_process,
        "overloaded_processes":       overloaded,
        "alerts":                     [],
        "narrative":                  "",
    }


def _build_process_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    """Generate actionable alerts in Turkish."""
    alerts: list[dict[str, str]] = []

    cycle = metrics.get("avg_cycle_time_days", 0.0)
    eff   = metrics.get("efficiency_score", 0.0)
    over  = metrics.get("overloaded_processes", [])
    bn    = metrics.get("bottleneck_process")
    bn_c  = metrics.get("bottleneck_constraint_label", "")
    toc   = metrics.get("toc_analysis", [])

    if eff >= 8.0:
        alerts.append({
            "level": "critical",
            "message": (
                f"Süreç verimlilik skoru {eff}/10 — operasyonlar ciddi ölçüde düşük performanslı. "
                "Acil süreç yeniden tasarımı gerekiyor."
            ),
        })
    elif eff >= 6.0:
        alerts.append({
            "level": "high",
            "message": (
                f"Süreç verimliliği {eff}/10 — önemli israf tespit edildi. "
                "Yalın (lean) veya çevik (agile) süreç iyileştirmeleri değerlendirilmeli."
            ),
        })

    if over:
        names = ", ".join(o["name"] for o in over[:3])
        alerts.append({
            "level": "high",
            "message": (
                f"{len(over)} süreçte WIP > 4 hafta birikimi var: {names}. "
                "Kalite düşüşü ve ekip tükenmişliği riski."
            ),
        })

    if cycle > 30:
        alerts.append({
            "level": "medium",
            "message": (
                f"Ortalama döngü süresi {cycle:.0f} gün — yüksek. "
                "Uzun döngüler müşteri memnuniyetini ve pazar yanıt hızını olumsuz etkiliyor."
            ),
        })

    if bn:
        alerts.append({
            "level": "medium",
            "message": (
                f"Darboğaz süreç: '{bn}' ({bn_c}). "
                "Kısıtlar Teorisi'ne göre bu tek süreç tüm operasyonel verimliliği sınırlıyor."
            ),
        })
        if toc:
            rec = toc[0].get("toc_recommendation", "")
            if rec:
                alerts.append({
                    "level": "info",
                    "message": f"ToC Önerisi: {rec}",
                })

    return alerts


# ---------------------------------------------------------------------------
# LLM Narrative (Turkish)
# ---------------------------------------------------------------------------

async def _generate_process_narrative(metrics: dict[str, Any], settings) -> str:
    """Türkçe COO narrative — Theory of Constraints bağlamıyla."""
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatOpenAI(
            model=getattr(settings, "openai_model", "gpt-4o-mini"),
            temperature=0.2,
            max_tokens=350,
            api_key=settings.openai_api_key,
        )
        cycle = metrics["avg_cycle_time_days"]
        eff   = metrics["efficiency_score"]
        over  = len(metrics.get("overloaded_processes", []))
        bn    = metrics.get("bottleneck_process", "belirsiz")
        bn_c  = metrics.get("bottleneck_constraint_label", "")
        bn_r  = metrics.get("bottleneck_recommendation", "")

        system = (
            "Sen kurumsal operasyon yönetimi alanında uzman bir COO asistanısın. "
            "Kısıtlar Teorisi (Theory of Constraints) ve Yalın üretim prensiplerini iyi biliyorsun. "
            "Türkçe, profesyonel ve aksiyon odaklı içgörüler yazıyorsun."
        )
        human = (
            f"Aşağıdaki süreç verilerine göre Türkçe 3 cümlelik COO düzeyinde özet yaz:\n\n"
            f"- Ortalama döngü süresi: {cycle:.0f} gün\n"
            f"- Verimlilik skoru: {eff}/10 (yüksek = kötü)\n"
            f"- Aşırı yüklü süreç sayısı: {over}\n"
            f"- Darboğaz süreç: {bn} ({bn_c})\n"
            f"- ToC önerisi: {bn_r}\n\n"
            "Mevcut durumu, temel riski ve 1 aksiyon önerisi içersin."
        )
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=human)])
        return resp.content.strip()
    except Exception:
        cycle = metrics.get("avg_cycle_time_days", 0.0)
        eff   = metrics.get("efficiency_score", 0.0)
        n     = metrics.get("total_processes", 0)
        bn    = metrics.get("bottleneck_process", "")
        bn_c  = metrics.get("bottleneck_constraint_label", "")
        return (
            f"{n} süreç analiz edildi; ortalama döngü süresi {cycle:.0f} gün, "
            f"verimlilik skoru {eff}/10."
            + (f" Darboğaz: '{bn}' ({bn_c})." if bn else "")
        )


# ---------------------------------------------------------------------------
# LangGraph Node
# ---------------------------------------------------------------------------

async def run_process_agent(state: COOState, config: dict) -> dict[str, Any]:
    """
    COO Process Skill — Theory of Constraints bottleneck analysis.
    done_when: state['processes']['efficiency_score'] is a float.
    """
    csv_text = state.get("process_csv") or ""

    if not csv_text.strip():
        logger.info("COO ProcessAgent: no process_csv provided -- skipping")
        return {"processes": None}

    try:
        rows    = _parse_process_csv(csv_text)
        metrics = _compute_process_metrics(rows)
        alerts  = _build_process_alerts(metrics)
        metrics["alerts"] = alerts

        try:
            from app.config import get_settings
            settings = get_settings()
            if getattr(settings, "openai_api_key", None):
                metrics["narrative"] = await _generate_process_narrative(metrics, settings)
        except Exception:
            pass

        if not metrics.get("narrative"):
            metrics["narrative"] = (
                f"{metrics['total_processes']} süreç analiz edildi; "
                f"ortalama döngü süresi {metrics['avg_cycle_time_days']:.0f} gün, "
                f"verimlilik skoru {metrics['efficiency_score']}/10."
            )

        logger.info(
            "COO ProcessAgent: processes=%d efficiency=%.1f/10 bottleneck=%s constraint=%s",
            len(rows),
            metrics["efficiency_score"],
            metrics.get("bottleneck_process"),
            metrics.get("bottleneck_constraint"),
        )
        return {"processes": metrics}

    except Exception as exc:
        logger.exception("COO ProcessAgent failed for job=%s", state.get("job_id"))
        return {"processes": None, "error": f"ProcessAgent error: {exc}"}
