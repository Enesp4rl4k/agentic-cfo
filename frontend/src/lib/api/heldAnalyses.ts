import { apiClient } from "@/lib/api/client";

// Analyses that finished but wait for a person (backend app/api/analysis.py, app/services/held_analysis.py).
// Approving is `approveJob` in lib/api/cfo; both answers are recorded by the server as decisions.

/** A reason is a code with its numbers; `HeldReasons` words it. Unknown codes are shown as "no reason recorded". */
export type HeldAnalysisReason = Record<string, unknown> & { code: string };

export interface HeldAnalysis {
  id: string;
  filename: string;
  min_confidence: number | null;
  reasons: HeldAnalysisReason[];
  /** The statement's running balances chain: approving it gives the cash radar its starting balance. */
  proves_balance: boolean;
  created_at: string | null;
}

export async function listHeldAnalyses(): Promise<HeldAnalysis[]> {
  const res = await apiClient.get<{ data: HeldAnalysis[]; error: string | null }>("/analyses/held");
  return res.data.data;
}

export async function rejectAnalysis(jobId: string, reason?: string): Promise<void> {
  await apiClient.post(`/analysis/${jobId}/reject`, { reason: reason?.trim() || null });
}
