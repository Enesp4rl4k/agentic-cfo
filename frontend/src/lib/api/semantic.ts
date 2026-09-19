/**
 * Semantic company model + Decision Brief API client.
 */
import { apiClient } from "./client";

export interface MetricPoint {
  metric_id: string;
  value: number | string | boolean | null;
  unit: string;
  confidence: number;
  currency?: string | null;
  source_agent?: string | null;
  data_source?: string;
}

export interface DecisionBriefFinding {
  severity: string;
  domain: string;
  statement: string;
  metric_ids: string[];
  confidence: number;
}

export interface DecisionBriefOption {
  title: string;
  impact_summary: string;
  linked_cf_action?: string | null;
}

export interface DecisionBrief {
  period: string;
  currency: string;
  locale: string;
  headline: string;
  health_score: number;
  findings: DecisionBriefFinding[];
  options: DecisionBriefOption[];
  recommendation: { title: string; rationale: string; option_index: number } | null;
  conflicts: Record<string, unknown>[];
  awaiting_review: boolean;
  generated_at: string;
  schema_version: string;
}

export interface SemanticSnapshot {
  org_id: string;
  period: { key: string; start?: string | null; end?: string | null; grain?: string };
  currency: string;
  locale: string;
  metrics: MetricPoint[];
  brief?: DecisionBrief | null;
  updated_at?: string;
}

export async function getSemanticMe(): Promise<{
  snapshot: SemanticSnapshot | null;
  catalog: Array<Record<string, string>>;
  period_key: string;
}> {
  const res = await apiClient.get<{
    data: {
      snapshot: SemanticSnapshot | null;
      catalog: Array<Record<string, string>>;
      period_key: string;
    };
    error: string | null;
  }>("/semantic/me");
  return res.data.data;
}

export async function getDecisionBrief(periodKey?: string): Promise<{
  brief: DecisionBrief | null;
  period_key: string;
  awaiting_review: boolean;
}> {
  const qs = periodKey ? `?period_key=${encodeURIComponent(periodKey)}` : "";
  const res = await apiClient.get<{
    data: {
      brief: DecisionBrief | null;
      period_key: string;
      awaiting_review: boolean;
    };
    error: string | null;
  }>(`/semantic/me/brief${qs}`);
  return res.data.data;
}

export interface SemanticPeriodSummary {
  period_key: string;
  period_start?: string | null;
  period_end?: string | null;
  currency: string;
  health_score: number | null;
  awaiting_review: boolean;
  metric_count: number;
  updated_at?: string;
}

export async function getSemanticHistory(limit = 12): Promise<SemanticPeriodSummary[]> {
  const res = await apiClient.get<{
    data: { periods: SemanticPeriodSummary[]; count: number };
    error: string | null;
  }>(`/semantic/me/history?limit=${limit}`);
  return res.data.data.periods;
}

export interface LiveDataStatus {
  live_sync_enabled: boolean;
  last_sync: {
    provider: string | null;
    completed_at: string | null;
    row_count_canonical: number;
    quality_score: number | null;
    triggered_job_id: string | null;
  } | null;
  canonical_transaction_count: number;
  semantic_snapshot: {
    period_key: string | null;
    metric_count: number;
    health_score: number | null;
    awaiting_review: boolean;
    updated_at: string | null;
  };
  baseline_source: string;
  golden_path_ready: boolean;
}

export async function getLiveDataStatus(): Promise<LiveDataStatus> {
  const res = await apiClient.get<{ data: LiveDataStatus; error: string | null }>(
    "/semantic/me/live-status"
  );
  return res.data.data;
}

export async function rebuildSemantic(): Promise<SemanticSnapshot> {
  const res = await apiClient.post<{ data: SemanticSnapshot; error: string | null }>(
    "/semantic/me/rebuild"
  );
  return res.data.data;
}

export async function approveDecisionBrief(periodKey?: string): Promise<{
  brief: DecisionBrief;
  period_key: string;
  awaiting_review: boolean;
}> {
  const qs = periodKey ? `?period_key=${encodeURIComponent(periodKey)}` : "";
  const res = await apiClient.post<{
    data: { brief: DecisionBrief; period_key: string; awaiting_review: boolean };
    error: string | null;
  }>(`/semantic/me/brief/approve${qs}`);
  return res.data.data;
}

/** Deep-link a metric into the most relevant simulation or brief surface. */
export function metricSimulationHref(metricId: string): string {
  if (metricId === "finance.runway_months" || metricId.includes("cash")) {
    return "/simulation?tab=cascade";
  }
  if (metricId.startsWith("growth.")) {
    return "/simulation?tab=counterfactual&action=marketing_invest";
  }
  if (metricId.startsWith("people.")) {
    return "/simulation?tab=counterfactual&action=headcount_change";
  }
  if (metricId.startsWith("tech.")) {
    return "/simulation?tab=counterfactual&action=tech_investment";
  }
  return "/command-center";
}

export function formatMetricValue(m: MetricPoint): string {
  const v = m.value;
  if (v == null) return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "string") return v;
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  if (m.unit === "cents") {
    return `₺${(n / 100).toLocaleString("tr-TR", { maximumFractionDigits: 0 })}`;
  }
  if (m.unit === "ratio" || m.unit === "percent") {
    return `${(n * 100).toFixed(1)}%`;
  }
  if (m.unit === "months") return `${n.toFixed(1)} ay`;
  if (m.unit === "score") return n.toFixed(1);
  return n.toLocaleString("tr-TR");
}
