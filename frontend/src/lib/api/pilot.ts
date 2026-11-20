import { apiClient } from "@/lib/api/client";

interface Envelope<T> {
  data: T;
  error: string | null;
}

export interface RadarBacktest {
  org_id: string;
  target_date: string;
  lookback_weeks: number;
  projected_end_balance_cents: number | null;
  actual_proven_balance_cents: number | null;
  actual_proven_balance_as_of: string | null;
  variance_cents: number | null;
  variance_pct: number | null;
  accuracy_tier: "HIGH" | "MODERATE" | "LOW" | "NO_ACTUAL" | "NO_FORECAST_SNAPSHOT" | "ZERO_ACTUAL";
  summary: string;
}

export interface DecisionSuccessMetrics {
  org_id: string;
  total_recommendations: number;
  responded_count: number;
  unresponded_count: number;
  adopted_count: number;
  deferred_count: number;
  dismissed_count: number;
  open_count: number;
  closed_count: number;
  adoption_rate_pct: number;
  dismissal_rate_pct: number;
  /** @deprecated Use dismissal_rate_pct. */
  correction_rate_pct: number;
  response_rate_pct: number;
  accepted_expected_amount_cents: number;
  /** @deprecated Expected action amount, not realized impact. */
  total_impact_cents: number;
  summary: string;
}

export async function getRadarBacktest(
  anchorDate?: string,
  lookbackWeeks: number = 4,
): Promise<RadarBacktest> {
  const params: Record<string, string | number> = { lookback_weeks: lookbackWeeks };
  if (anchorDate) params.anchor_date = anchorDate;
  const res = await apiClient.get<Envelope<RadarBacktest>>("/pilot/radar-backtest", { params });
  return res.data.data;
}

export async function getDecisionSuccessMetrics(): Promise<DecisionSuccessMetrics> {
  const res = await apiClient.get<Envelope<DecisionSuccessMetrics>>("/pilot/decision-metrics");
  return res.data.data;
}
