import { apiClient } from "@/lib/api/client";

// Role results below the confidence gate (backend app/platform/run_gate.py):
// visible to the person deciding, not in the company's context until approved.

export interface GateDecision {
  awaiting_review: boolean;
  min_confidence: number | null;
  reasons: string[];
}

export interface HeldAgentJob {
  id: string;
  agent_type: string;
  created_at: string;
  gate: GateDecision | null;
}

interface Envelope<T> {
  data: T;
  error: string | null;
}

export async function getReviewQueue(): Promise<HeldAgentJob[]> {
  const res = await apiClient.get<Envelope<HeldAgentJob[]>>("/agent-jobs/review-queue");
  return res.data.data;
}

export async function approveHeldJob(jobId: string): Promise<void> {
  await apiClient.post(`/agent-jobs/${jobId}/approve`);
}

export async function rejectHeldJob(jobId: string): Promise<void> {
  await apiClient.post(`/agent-jobs/${jobId}/reject`);
}
