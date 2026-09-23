import { apiClient } from "@/lib/api/client";

// ── Decision Packet ───────────────────────────────────────────────────────────
// GET /analysis/{id}/decision-packet — the review moment in one response:
// situation, options with computed consequences, real data freshness,
// precedent. Backend is deterministic (no LLM) and read-only.

export type FreshnessState = "fresh" | "aging" | "stale" | "never" | "unknown";

export interface FreshnessItem {
  source: string;
  label: string;
  /** ISO timestamp the source itself maintains — null = never synced. */
  as_of: string | null;
  age_days: number | null;
  state: FreshnessState;
  detail: string | null;
}

export interface PacketOption {
  id: string;
  label: string;
  description: string;
  baseline: boolean;
  /** 12-month net effect in kuruş (0 for the baseline by definition). */
  base_net_impact: number;
  breakeven_months: number | null;
  cashflow_risk: string | null;
  /** Only the baseline carries a runway figure — the engine never guesses one. */
  runway_after: number | null;
  assumptions: string[];
  recommendation: string | null;
  engine: "forecast" | "counterfactual";
  scenarios: {
    name: string;
    net_impact_try: number;
    cashflow_impact_monthly: number;
    breakeven_months: number | null;
  }[];
}

export interface PacketSituation {
  /** Money fields are kuruş, straight from the report. */
  revenue_12m: number;
  net_margin: number | null;
  net_change_12m: number;
  top_opex_category: string | null;
  top_opex_amount: number | null;
  runway_months: number | null;
  forecast_12m_net: number | null;
  anomaly_count: number;
  min_confidence: number | null;
}

export interface PacketDecision {
  id: string;
  topic: string;
  final_decision: string;
  resolution_status: string;
  /** The boardroom memory scores confidence; the decision ledger does
   *  not compute one and honestly sends null. */
  confidence_score: number | null;
  created_at: string;
}

/**
 * P3 · "Tahminleriniz tuttu mu?" — org-wide forecast backtest.
 * `status: "ok"` only once ≥3 forecast windows closed; until then the
 * honest answer, and the metric fields are absent — never a number
 * computed on noise.
 */
export interface Calibration {
  status: string;
  pairs: number;
  /** All money fields are kuruş; percentages are already in percent. */
  mae_kurus?: number | null;
  smape_pct?: number | null;
  coverage_pct?: number | null;
  bias_kurus?: number | null;
}

export interface DecisionPacket {
  job_id: string;
  status: string;
  awaiting_review: boolean;
  generated_at: string;
  gate: {
    held_for_review: boolean;
    min_confidence: number | null;
    reason: string | null;
  };
  situation: PacketSituation;
  options: PacketOption[];
  freshness: FreshnessItem[];
  precedent: { decisions: PacketDecision[]; pending_actions: number };
  calibration: Calibration;
  evidence: string;
}

export async function getDecisionPacket(jobId: string): Promise<DecisionPacket> {
  const res = await apiClient.get<{ data: DecisionPacket; error: null }>(
    `/analysis/${jobId}/decision-packet`
  );
  return res.data.data;
}
