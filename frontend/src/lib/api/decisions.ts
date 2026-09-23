import { apiClient } from "@/lib/api/client";

// ── Karar Defteri ────────────────────────────────────────────────────────────
// POST/GET /decisions — record a decision against the packet's own numbers
// and measure what actually happened afterwards. Backend is deterministic;
// money is kuruş (integer minor unit) — the UI divides.

export interface DecisionExpected {
  revenue_12m: number | null;
  net_change_12m: number | null;
  runway_months: number | null;
  forecast_12m_net: number | null;
  option_id: string;
  option_label: string;
  option_net_impact: number | null;
  option_runway_after: number | null;
  generated_at: string;
}

export interface DecisionActual {
  realized_net_kurus: number;
  income_kurus: number;
  expense_kurus: number;
  transactions_since: number;
  runway_months_latest: number | null;
  data_job_id: string;
  decided_at: string | null;
  as_of: string;
}

export interface DecisionVariance {
  realized_net_kurus: number;
  runway_delta?: number;
}

export interface DecisionRecord {
  id: string;
  job_id: string;
  org_id: string | null;
  topic: string;
  chosen_option_id: string;
  chosen_option_label: string;
  rationale: string | null;
  /** Server-filled from the packet at decision time — never from the client. */
  expected: DecisionExpected;
  status: "open" | "closed";
  actual: DecisionActual | null;
  variance: DecisionVariance | null;
  outcome_note: string | null;
  measured_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateDecisionInput {
  jobId: string;
  optionId: string;
  topic?: string;
  rationale?: string;
}

export interface ListDecisionsParams {
  status?: "open" | "closed";
  jobId?: string;
  limit?: number;
}

export async function createDecision(
  input: CreateDecisionInput
): Promise<DecisionRecord> {
  const res = await apiClient.post<{ data: DecisionRecord; error: null }>(
    "/decisions",
    {
      job_id: input.jobId,
      option_id: input.optionId,
      topic: input.topic ?? null,
      rationale: input.rationale ?? null,
    }
  );
  return res.data.data;
}

export async function listDecisions(
  params: ListDecisionsParams = {}
): Promise<DecisionRecord[]> {
  const query: Record<string, unknown> = {};
  if (params.status) query.status = params.status;
  if (params.jobId) query.job_id = params.jobId;
  if (params.limit) query.limit = params.limit;
  const res = await apiClient.get<{ data: DecisionRecord[]; error: null }>(
    "/decisions",
    { params: query }
  );
  return res.data.data;
}

/** Measure what happened since the decision and close the row — once. */
export async function measureOutcome(
  decisionId: string,
  note?: string
): Promise<DecisionRecord> {
  const res = await apiClient.post<{ data: DecisionRecord; error: null }>(
    `/decisions/${decisionId}/outcome`,
    { note: note ?? null }
  );
  return res.data.data;
}
