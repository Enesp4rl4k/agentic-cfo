// Shared types and helpers for CTO dashboard components

export interface InfraData {
  total_cost_cents: number;
  waste_estimate_cents: number;
  mom_change_pct: number | null;
  top_cost_drivers: { service: string; cost_cents: number; pct: number }[];
  by_environment: Record<string, number>;
  alerts: { level: string; message: string }[];
  narrative: string;
}

export interface TechDebtData {
  total_commits: number;
  active_contributors: number;
  churn_rate: number;
  debt_score: number;
  hotspot_files: { file: string; changes: number; authors: number; bus_factor_risk: boolean }[];
  refactor_priorities: { area: string; severity: string; changes_in_period: number; estimated_days: number }[];
  narrative: string;
}

export interface IncidentData {
  total_incidents: number;
  by_severity: Record<string, number>;
  mttr_hours: number | null;
  mttd_hours: number | null;
  sla_breach_count: number;
  sla_breach_pct: number;
  recurring_services: { service: string; count: number; pct: number }[];
  trend: string;
  alerts: { level: string; message: string }[];
  narrative: string;
}

export interface VelocityData {
  sprints_analyzed: number;
  avg_velocity: number;
  velocity_trend: string;
  predictability_score: number;
  carryover_ratio: number;
  bottlenecks: { area: string; impact: string }[];
  sprint_series: { sprint: string; planned: number; completed: number; completion_rate_pct: number }[];
  narrative: string;
}

export interface CTOSummary {
  overall_health_score: number;
  component_scores: Record<string, number>;
  top_risks: { domain: string; severity: string; message: string }[];
  quick_wins: { action: string; estimated_impact: string; effort: "low" | "medium" | "high" }[];
  narrative: string;
}

export interface CTOResult {
  job_id: string;
  infra: InfraData | null;
  tech_debt: TechDebtData | null;
  incidents: IncidentData | null;
  velocity: VelocityData | null;
  cto_summary: CTOSummary | null;
  awaiting_review: boolean;
  min_confidence: number | null;
  error: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

export function fmtCents(cents: number): string {
  return `$${(cents / 100).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function healthColor(score: number): string {
  if (score <= 3) return "text-emerald-400";
  if (score <= 6) return "text-yellow-400";
  if (score <= 8) return "text-orange-400";
  return "text-destructive";
}

export function healthLabel(score: number): string {
  if (score <= 3) return "Healthy";
  if (score <= 6) return "Moderate";
  if (score <= 8) return "At Risk";
  return "Critical";
}
