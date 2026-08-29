import { apiClient } from "@/lib/api/client";

// ── Confidence decomposition ────────────────────────────────────────────────

export interface ConfidenceComponent {
  step: string;
  confidence: number;
  ok: boolean;
  detail: string | null;
  kind: "skill" | "reflection" | "reconciliation";
  weakest?: boolean;
}

export interface ConfidenceBreakdown {
  aggregate: number;
  threshold: number;
  meets_threshold: boolean;
  binding_constraint: string | null;
  components: ConfidenceComponent[];
  narrative: string;
}

// ── TR accounting vertical (L3 autopilot) ────────────────────────────────────

export interface TrVerticalResult {
  job_id: string;
  stage: "ingest" | "cfo" | "accounting" | "board_deck" | "done";
  approval_required: boolean;
  approval_reasons: string[];
  errors: string[];
  cfo: {
    halted?: boolean;
    awaiting_review?: boolean;
    error?: string | null;
    min_confidence?: number | null;
    pnl?: {
      revenue?: number;
      gross_profit?: number;
      ebitda?: number;
      net_income?: number;
      net_margin?: number;
      narrative?: string;
    } | null;
    anomalies?: Array<{ title?: string; severity?: string; description?: string }>;
    transaction_count?: number;
    confidence_breakdown?: ConfidenceBreakdown | null;
  };
  reconciliation?: {
    action: "proceed" | "hold_for_review" | "halt";
    identity_failures: string[];
    ungrounded_claims: string[];
    notes: string[];
  } | null;
  accounting?: {
    islem_sayisi: number;
    kayit_sayisi: number;
    onay_bekleyen: number;
    dengeli: boolean;
    hata?: string | null;
  } | null;
  board_deck_pdf_size: number;
  board_deck_pdf_path?: string | null;
}

export interface TrVerticalResponse {
  data: TrVerticalResult;
  error: string | null;
  meta: { depth_level: number; auto_approved: boolean };
}

export async function runTrVertical(
  jobId: string,
  opts: { companyName?: string; donem?: string } = {}
): Promise<TrVerticalResponse> {
  const res = await apiClient.post<TrVerticalResponse>("/muhasebe/tr-vertical", {
    job_id: jobId,
    company_name: opts.companyName,
    donem: opts.donem,
  });
  return res.data;
}

export async function downloadTrBoardDeck(jobId: string): Promise<Blob> {
  const res = await apiClient.get(
    `/muhasebe/tr-vertical/${jobId}/board-deck.pdf`,
    { responseType: "blob" }
  );
  return new Blob([res.data], { type: "application/pdf" });
}

// ── LLM cost rollup (observability) ─────────────────────────────────────────

export interface LlmCostBucket {
  key: string | null;
  calls: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
}

export interface LlmCosts {
  window_days: number;
  total_calls: number;
  ok_calls: number;
  total_cost_usd: number;
  by_model: LlmCostBucket[];
  by_org: LlmCostBucket[];
  by_task: LlmCostBucket[];
  by_day: LlmCostBucket[];
  live_process_aggregate: Record<string, unknown>;
}

export async function getLlmCosts(days = 30): Promise<LlmCosts> {
  const res = await apiClient.get<{ data: LlmCosts; error: null }>("/system/llm-costs", {
    params: { days },
  });
  return res.data.data;
}
