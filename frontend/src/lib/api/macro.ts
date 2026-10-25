import { apiClient } from "./client";

/** TCMB snapshot — `data_source` says whether it is live, cached or the static fallback. */
export interface TcmbSnapshot {
  usd_try: number;
  eur_try: number;
  policy_rate_pct: number;
  inflation_pct: number;
  data_source?: string | null;
}

export interface ShockInputs {
  usd_shock_pct: number;
  eur_shock_pct: number;
  interest_rate_delta_bp: number;
  payment_delay_days: number;
}

export interface StressResult {
  baseline_runway_months: number | null;
  /** null when the forecast has no runway limit (never goes cash-negative). */
  stressed_runway_months: number | null;
  runway_delta_months: number | null;
  monthly_cost_increase_lira: number;
  monthly_net_after_shock_lira: number;
  months_observed: number;
  risk_level: string;
  /** Codes; the UI owns the wording. */
  recommendations: string[];
  data_source: string;
  assumptions: Record<string, number>;
}

export interface StressResponse {
  current_macro: TcmbSnapshot;
  /** null when the org has no CFO analysis to stress — never sample numbers. */
  simulation_result: StressResult | null;
  baseline_missing_reason: string | null;
}

export async function getTcmbSnapshot(): Promise<TcmbSnapshot> {
  const res = await apiClient.get<{ data: TcmbSnapshot }>("/macro/tcmb");
  return res.data.data;
}

export async function simulateMacroShock(inputs: ShockInputs): Promise<StressResponse> {
  const res = await apiClient.post<{ data: StressResponse }>("/macro/simulate", inputs);
  return res.data.data;
}
