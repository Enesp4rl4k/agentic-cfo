/**
 * Runtime contract between what the CTO pipeline returns on the wire and the
 * typed `CTOResult` the dashboard renders. Until now the page cast payloads
 * with `as unknown as CTOResult` — types-only, so a renamed or missing
 * backend key surfaced as `undefined`/`NaN` in cards (the bug class the CHRO
 * page hit in 2026-10-14). Every entry point (context hydration, POST
 * /cto/analyze, DomainPanel) normalizes exactly once; a section without its
 * core metric is null and the view renders "—" instead of lying.
 *
 * Wire keys are the ones the backend CTO agents emit and the page consumed
 * live on 2026-10-14; section shapes are pinned by `components/cto/types.ts`.
 */

import type {
  CTOResult,
  CTOSummary,
  InfraData,
  IncidentData,
  TechDebtData,
  VelocityData,
} from "@/components/cto/types";

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function num0(v: unknown): number {
  return num(v) ?? 0;
}

function str(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

function strOrNull(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v : null;
}

function records(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? v.filter(isRecord) : [];
}

function numMap(v: unknown): Record<string, number> {
  if (!isRecord(v)) return {};
  const out: Record<string, number> = {};
  for (const [k, value] of Object.entries(v)) {
    const n = num(value);
    if (n !== null) out[k] = n;
  }
  return out;
}

function alertsOf(section: Record<string, unknown>): { level: string; message: string }[] {
  return records(section.alerts)
    .map((a) => ({ level: str(a.level, "info"), message: str(a.message) }))
    .filter((a) => a.message !== "");
}

function normalizeInfra(raw: unknown): InfraData | null {
  if (!isRecord(raw)) return null;
  const total = num(raw.total_cost_cents);
  if (total === null) return null;
  return {
    total_cost_cents: total,
    waste_estimate_cents: num0(raw.waste_estimate_cents),
    mom_change_pct: num(raw.mom_change_pct),
    top_cost_drivers: records(raw.top_cost_drivers).map((d) => ({
      service: str(d.service),
      cost_cents: num0(d.cost_cents),
      pct: num0(d.pct),
    })),
    by_environment: numMap(raw.by_environment),
    alerts: alertsOf(raw),
    narrative: str(raw.narrative),
  };
}

function normalizeTechDebt(raw: unknown): TechDebtData | null {
  if (!isRecord(raw)) return null;
  const score = num(raw.debt_score);
  if (score === null) return null;
  return {
    total_commits: num0(raw.total_commits),
    active_contributors: num0(raw.active_contributors),
    churn_rate: num0(raw.churn_rate),
    debt_score: score,
    hotspot_files: records(raw.hotspot_files).map((h) => ({
      file: str(h.file),
      changes: num0(h.changes),
      authors: num0(h.authors),
      bus_factor_risk: h.bus_factor_risk === true,
    })),
    refactor_priorities: records(raw.refactor_priorities).map((r) => ({
      area: str(r.area),
      severity: str(r.severity),
      changes_in_period: num0(r.changes_in_period),
      estimated_days: num0(r.estimated_days),
    })),
    narrative: str(raw.narrative),
  };
}

function normalizeIncidents(raw: unknown): IncidentData | null {
  if (!isRecord(raw)) return null;
  const total = num(raw.total_incidents);
  if (total === null) return null;
  return {
    total_incidents: total,
    by_severity: numMap(raw.by_severity),
    mttr_hours: num(raw.mttr_hours),
    mttd_hours: num(raw.mttd_hours),
    sla_breach_count: num0(raw.sla_breach_count),
    sla_breach_pct: num0(raw.sla_breach_pct),
    recurring_services: records(raw.recurring_services).map((s) => ({
      service: str(s.service),
      count: num0(s.count),
      pct: num0(s.pct),
    })),
    trend: str(raw.trend),
    alerts: alertsOf(raw),
    narrative: str(raw.narrative),
  };
}

function normalizeVelocity(raw: unknown): VelocityData | null {
  if (!isRecord(raw)) return null;
  const avg = num(raw.avg_velocity);
  if (avg === null) return null;
  return {
    sprints_analyzed: num0(raw.sprints_analyzed),
    avg_velocity: avg,
    velocity_trend: str(raw.velocity_trend),
    predictability_score: num0(raw.predictability_score),
    carryover_ratio: num0(raw.carryover_ratio),
    bottlenecks: records(raw.bottlenecks).map((b) => ({
      area: str(b.area),
      impact: str(b.impact),
    })),
    sprint_series: records(raw.sprint_series).map((s) => ({
      sprint: str(s.sprint),
      planned: num0(s.planned),
      completed: num0(s.completed),
      completion_rate_pct: num0(s.completion_rate_pct),
    })),
    narrative: str(raw.narrative),
  };
}

function normalizeEffort(raw: unknown): "low" | "medium" | "high" {
  const v = str(raw).trim().toLowerCase();
  if (v === "low" || v === "medium" || v === "high") return v;
  if (["düşük", "dusuk"].includes(v)) return "low";
  if (["yüksek", "yuksek"].includes(v)) return "high";
  return "medium";
}

function normalizeSummary(raw: unknown): CTOSummary | null {
  if (!isRecord(raw)) return null;
  const score = num(raw.overall_health_score);
  if (score === null) return null;
  return {
    overall_health_score: score,
    component_scores: numMap(raw.component_scores),
    top_risks: records(raw.top_risks)
      .map((r) => ({
        domain: str(r.domain),
        severity: str(r.severity),
        message: str(r.message),
      }))
      .filter((r) => r.message !== ""),
    quick_wins: records(raw.quick_wins)
      .map((w) => ({
        action: str(w.action),
        estimated_impact: str(w.estimated_impact),
        effort: normalizeEffort(w.effort),
      }))
      .filter((w) => w.action !== ""),
    narrative: str(raw.narrative),
  };
}

export function normalizeCTOResult(raw: unknown): CTOResult | null {
  if (!isRecord(raw)) return null;

  const infra = normalizeInfra(raw.infra);
  const tech_debt = normalizeTechDebt(raw.tech_debt);
  const incidents = normalizeIncidents(raw.incidents);
  const velocity = normalizeVelocity(raw.velocity);
  const cto_summary = normalizeSummary(raw.cto_summary);
  const error = strOrNull(raw.error);

  if (!infra && !tech_debt && !incidents && !velocity && !cto_summary && !error) return null;

  return {
    job_id: str(raw.job_id),
    infra,
    tech_debt,
    incidents,
    velocity,
    cto_summary,
    awaiting_review: raw.awaiting_review === true,
    min_confidence: num(raw.min_confidence),
    error,
  };
}
