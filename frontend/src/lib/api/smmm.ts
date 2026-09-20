import { apiClient } from "@/lib/api/client";

// ── SMMM Defensibility Packet (differentiator #4) ───────────────────────────

export interface PacketSummary {
  period: string | null;
  entry_count: number;
  total_amount_kurus: number;
  by_decision_source: Record<string, number>;
  human_reviewed: number;
  ai_auto_posted: number;
  rejected: number;
  pending_review: number;
  balanced: boolean | null;
  avg_classification_confidence: number | null;
  defensible: boolean;
  run: { status: string | null; latency_ms: number | null; cost_usd: number | null };
}

export interface DefensibilityPacket {
  id: string;
  job_id: string;
  period: string | null;
  status: "draft" | "finalized";
  content_hash: string | null;
  summary: PacketSummary | null;
  finalized_at: string | null;
  created_at: string | null;
  smmm_statement?: string | null;
  payload?: { entries: PacketEntry[]; thp_dagilim: Record<string, number> };
}

export interface PacketEntry {
  kayit_id: string;
  date: string;
  description: string;
  amount_kurus: number;
  account_code: string;
  classification_confidence: number;
  decision_source:
    | "ai_auto_posted"
    | "human_approved"
    | "human_corrected"
    | "rejected"
    | "pending_review";
  review: {
    status: string;
    original_account: string | null;
    corrected_account: string | null;
    note: string | null;
  } | null;
}

export async function buildDefensibilityPacket(
  jobId: string,
  period?: string
): Promise<DefensibilityPacket> {
  const res = await apiClient.post<{ data: DefensibilityPacket }>(
    `/smmm/defensibility/${jobId}/build`,
    null,
    { params: period ? { period } : {} }
  );
  return res.data.data;
}

export async function getDefensibilityPacket(packetId: string): Promise<DefensibilityPacket> {
  const res = await apiClient.get<{ data: DefensibilityPacket }>(
    `/smmm/defensibility/${packetId}`
  );
  return res.data.data;
}

export async function finalizeDefensibilityPacket(
  packetId: string,
  statement: string
): Promise<DefensibilityPacket> {
  const res = await apiClient.post<{ data: DefensibilityPacket }>(
    `/smmm/defensibility/${packetId}/finalize`,
    { statement }
  );
  return res.data.data;
}

export async function exportDefensibilityPacket(packetId: string): Promise<Blob> {
  const res = await apiClient.get(`/smmm/defensibility/${packetId}/export`, {
    responseType: "blob",
  });
  return res.data as Blob;
}
