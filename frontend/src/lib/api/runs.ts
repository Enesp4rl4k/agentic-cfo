import { apiClient } from "@/lib/api/client";

// ── Agent run ledger ────────────────────────────────────────────────────────
// Every pipeline run is recorded: which node it reached, what it cost, how long
// it took, and — when it failed — where. The ledger shipped as a completed
// phase and was never given a surface, so the record of what the agents did
// existed and nobody could look at it.

interface Envelope<T> {
  data: T;
  error: string | null;
}

export type RunStatus =
  | "running"
  | "completed"
  | "failed"
  | "awaiting_review"
  | "halted";

export interface AgentRun {
  id: string;
  pipeline: string;
  job_id: string | null;
  status: RunStatus;
  current_node: string | null;
  node_history: string[];
  attempt: number;
  error: string | null;
  latency_ms: number | null;
  cost_usd: number | null;
  result_ref: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface PipelineSLO {
  runs: number;
  completed: number;
  failed: number;
  awaiting_review: number;
  halted: number;
  success_rate: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  avg_cost_usd: number | null;
}

export interface RunsSLO {
  window_days: number;
  total_runs: number;
  by_pipeline: Record<string, PipelineSLO>;
}

export async function listRuns(params?: {
  status?: RunStatus;
  pipeline?: string;
  limit?: number;
}): Promise<AgentRun[]> {
  const res = await apiClient.get<Envelope<{ runs: AgentRun[] }>>("/runs", {
    params,
  });
  return res.data.data.runs ?? [];
}

export async function fetchRunsSLO(days = 7): Promise<RunsSLO> {
  const res = await apiClient.get<Envelope<RunsSLO>>("/runs/slo", {
    params: { days },
  });
  return res.data.data;
}

/** Re-drive an interrupted run from the node it stopped on. */
export async function resumeRun(runId: string): Promise<AgentRun> {
  const res = await apiClient.post<Envelope<AgentRun>>(`/runs/${runId}/resume`, {});
  return res.data.data;
}
