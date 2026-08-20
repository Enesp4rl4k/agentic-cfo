import { apiClient } from "@/lib/api/client";

export interface AgentConflict {
  id: string;
  topic: string;
  status: string;
  consensus_score: number | null;
  severity?: string;
  resolution: string | null;
  created_at: string | null;
  winning_agent?: string | null;
  narrative?: string | null;
}

export interface ConflictsResponse {
  org_id: string;
  count: number;
  conflicts: AgentConflict[];
}

export interface ConsensusResult {
  topic: string;
  agreement_score: number;
  winning_agent: string | null;
  narrative: string;
  conflicts: unknown[];
  winning_view?: Record<string, unknown>;
  dissenting_views?: unknown[];
}

export async function listConflicts(orgId: string): Promise<ConflictsResponse> {
  const res = await apiClient.get<{ data: ConflictsResponse; error: null }>(
    `/negotiation/conflicts/${orgId}`
  );
  return res.data.data;
}

export async function runConsensus(
  topic: string,
  orgId?: string,
  resolution: "weighted" | "majority" | "escalate" = "weighted"
): Promise<ConsensusResult> {
  const res = await apiClient.post<{ data: ConsensusResult; error: null }>(
    "/negotiation/consensus",
    { topic, org_id: orgId, resolution }
  );
  return res.data.data;
}

export async function resolveConflict(
  conflictId: string,
  resolution: string,
  note = ""
): Promise<{ conflict_id: string; resolved: boolean }> {
  const res = await apiClient.post<{
    data: { conflict_id: string; resolved: boolean };
    error: null;
  }>(`/negotiation/resolve/${conflictId}`, { resolution, note });
  return res.data.data;
}

export async function listConsensusTopics(): Promise<{
  topics: Array<{ name: string; weights: Record<string, number> }>;
}> {
  const res = await apiClient.get<{
    data: { topics: Array<{ name: string; weights: Record<string, number> }> };
    error: null;
  }>("/negotiation/topics");
  return res.data.data;
}
