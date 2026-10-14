/**
 * Runtime contract between what the CMO pipeline returns on the wire and the
 * dashboard view. The page used to cast with `as CMOResult`, so a renamed or
 * missing backend key surfaced as `undefined`/`NaN` — the bug class the CHRO
 * page hit on 2026-10-14. Both entry points (context hydration,
 * DomainPanel onResult) normalize exactly once; a section without its core
 * metric is omitted and the view renders "—".
 *
 * Wire keys are the ones the backend CMO agents emit and the page consumed
 * live on 2026-10-14 (ROAS 3.9×, ₺18 CAC). Money is kuruş.
 */

export interface CampaignData {
  total_spend_cents: number;
  total_revenue_cents: number;
  total_conversions: number;
  overall_roas: number;
  overall_cac_cents: number;
  by_channel: Record<string, {
    spend_cents: number; revenue_cents: number; roas: number;
    cac_cents: number; conversions: number; ctr: number;
  }>;
  top_campaigns: Array<{
    name: string; channel: string; spend_cents: number;
    revenue_cents: number; roas: number; cac_cents: number; status: string;
  }>;
  underperforming: Array<{ name: string; channel: string; spend_cents: number; roas: number; reason: string }>;
  alerts: Array<{ level: string; message: string }>;
  narrative: string;
}

export interface FunnelData {
  total_leads: number;
  mql_count: number;
  sql_count: number;
  won_count: number;
  lead_to_mql_rate: number;
  mql_to_sql_rate: number;
  sql_to_won_rate: number;
  overall_conversion_rate: number;
  avg_cycle_days: number;
  by_source: Record<string, { leads: number; mqls: number; sqls: number; won: number; conversion_rate: number }>;
  bottleneck_stage: string;
  alerts: Array<{ level: string; message: string }>;
  narrative: string;
}

export interface CohortData {
  cohorts_analyzed: number;
  avg_retention_30d: number;
  avg_retention_90d: number;
  avg_ltv_cents: number;
  avg_cac_cents: number;
  ltv_cac_ratio: number;
  churn_rate: number;
  best_cohort: { period: string; retention_30d: number; ltv_cents: number } | null;
  worst_cohort: { period: string; retention_30d: number; ltv_cents: number } | null;
  retention_trend: string;
  alerts: Array<{ level: string; message: string }>;
  narrative: string;
}

export interface CMOSummary {
  overall_marketing_score: number;
  growth_efficiency_score: number;
  component_scores: Record<string, number>;
  top_risks: Array<{ domain: string; severity: string; message: string }>;
  quick_wins: Array<{ action: string; estimated_impact: string; effort: string }>;
  narrative: string;
}

export interface CMOResult {
  job_id: string;
  campaigns?: CampaignData;
  funnel?: FunnelData;
  cohorts?: CohortData;
  cmo_summary?: CMOSummary;
  error?: string;
}

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

function records(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? v.filter(isRecord) : [];
}

function numMap<T>(v: unknown, map: (rec: Record<string, unknown>) => T): Record<string, T> {
  if (!isRecord(v)) return {};
  const out: Record<string, T> = {};
  for (const [k, value] of Object.entries(v)) {
    if (isRecord(value)) out[k] = map(value);
  }
  return out;
}

function numScores(v: unknown): Record<string, number> {
  if (!isRecord(v)) return {};
  const out: Record<string, number> = {};
  for (const [k, value] of Object.entries(v)) {
    const n = num(value);
    if (n !== null) out[k] = n;
  }
  return out;
}

function alertsOf(section: Record<string, unknown>): Array<{ level: string; message: string }> {
  return records(section.alerts)
    .map((a) => ({ level: str(a.level, "info"), message: str(a.message) }))
    .filter((a) => a.message !== "");
}

function normalizeCampaigns(raw: unknown): CampaignData | undefined {
  if (!isRecord(raw)) return undefined;
  const spend = num(raw.total_spend_cents);
  if (spend === null) return undefined;
  return {
    total_spend_cents: spend,
    total_revenue_cents: num0(raw.total_revenue_cents),
    total_conversions: num0(raw.total_conversions),
    overall_roas: num0(raw.overall_roas),
    overall_cac_cents: num0(raw.overall_cac_cents),
    by_channel: numMap(raw.by_channel, (c) => ({
      spend_cents: num0(c.spend_cents),
      revenue_cents: num0(c.revenue_cents),
      roas: num0(c.roas),
      cac_cents: num0(c.cac_cents),
      conversions: num0(c.conversions),
      ctr: num0(c.ctr),
    })),
    top_campaigns: records(raw.top_campaigns).map((c) => ({
      name: str(c.name),
      channel: str(c.channel),
      spend_cents: num0(c.spend_cents),
      revenue_cents: num0(c.revenue_cents),
      roas: num0(c.roas),
      cac_cents: num0(c.cac_cents),
      status: str(c.status),
    })),
    underperforming: records(raw.underperforming).map((c) => ({
      name: str(c.name),
      channel: str(c.channel),
      spend_cents: num0(c.spend_cents),
      roas: num0(c.roas),
      reason: str(c.reason),
    })),
    alerts: alertsOf(raw),
    narrative: str(raw.narrative),
  };
}

function normalizeFunnel(raw: unknown): FunnelData | undefined {
  if (!isRecord(raw)) return undefined;
  const leads = num(raw.total_leads);
  if (leads === null) return undefined;
  return {
    total_leads: leads,
    mql_count: num0(raw.mql_count),
    sql_count: num0(raw.sql_count),
    won_count: num0(raw.won_count),
    lead_to_mql_rate: num0(raw.lead_to_mql_rate),
    mql_to_sql_rate: num0(raw.mql_to_sql_rate),
    sql_to_won_rate: num0(raw.sql_to_won_rate),
    overall_conversion_rate: num0(raw.overall_conversion_rate),
    avg_cycle_days: num0(raw.avg_cycle_days),
    by_source: numMap(raw.by_source, (s) => ({
      leads: num0(s.leads),
      mqls: num0(s.mqls),
      sqls: num0(s.sqls),
      won: num0(s.won),
      conversion_rate: num0(s.conversion_rate),
    })),
    bottleneck_stage: str(raw.bottleneck_stage),
    alerts: alertsOf(raw),
    narrative: str(raw.narrative),
  };
}

function cohortOrNull(raw: unknown): { period: string; retention_30d: number; ltv_cents: number } | null {
  if (!isRecord(raw)) return null;
  return {
    period: str(raw.period),
    retention_30d: num0(raw.retention_30d),
    ltv_cents: num0(raw.ltv_cents),
  };
}

function normalizeCohorts(raw: unknown): CohortData | undefined {
  if (!isRecord(raw)) return undefined;
  const analyzed = num(raw.cohorts_analyzed);
  if (analyzed === null) return undefined;
  return {
    cohorts_analyzed: analyzed,
    avg_retention_30d: num0(raw.avg_retention_30d),
    avg_retention_90d: num0(raw.avg_retention_90d),
    avg_ltv_cents: num0(raw.avg_ltv_cents),
    avg_cac_cents: num0(raw.avg_cac_cents),
    ltv_cac_ratio: num0(raw.ltv_cac_ratio),
    churn_rate: num0(raw.churn_rate),
    best_cohort: cohortOrNull(raw.best_cohort),
    worst_cohort: cohortOrNull(raw.worst_cohort),
    retention_trend: str(raw.retention_trend, "stable"),
    alerts: alertsOf(raw),
    narrative: str(raw.narrative),
  };
}

function normalizeSummary(raw: unknown): CMOSummary | undefined {
  if (!isRecord(raw)) return undefined;
  const score = num(raw.overall_marketing_score);
  if (score === null) return undefined;
  return {
    overall_marketing_score: score,
    growth_efficiency_score: num0(raw.growth_efficiency_score),
    component_scores: numScores(raw.component_scores),
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
        effort: str(w.effort),
      }))
      .filter((w) => w.action !== ""),
    narrative: str(raw.narrative),
  };
}

export function normalizeCMOResult(raw: unknown): CMOResult | null {
  if (!isRecord(raw)) return null;

  const campaigns = normalizeCampaigns(raw.campaigns);
  const funnel = normalizeFunnel(raw.funnel);
  const cohorts = normalizeCohorts(raw.cohorts);
  const cmo_summary = normalizeSummary(raw.cmo_summary);
  const error = typeof raw.error === "string" && raw.error.trim() !== "" ? raw.error : undefined;

  if (!campaigns && !funnel && !cohorts && !cmo_summary && !error) return null;

  return { job_id: str(raw.job_id), campaigns, funnel, cohorts, cmo_summary, error };
}
