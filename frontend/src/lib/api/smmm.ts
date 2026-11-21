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

// ── Closed months ───────────────────────────────────────────────────────────

export interface KapaliDonem {
  donem: string;
  kilitleyen_user_id: string | null;
  kilitlendi?: string | null;
}

export async function getClosedPeriods(): Promise<KapaliDonem[]> {
  const res = await apiClient.get<{ data: { donemler: KapaliDonem[] } }>("/smmm/donem-kilitleri");
  return res.data.data.donemler ?? [];
}

export async function closePeriod(donem: string): Promise<void> {
  await apiClient.post("/smmm/donem-kilitleri", { donem });
}

// ── Every client's upcoming deadlines ──────────────────────────────────────

export interface SmmmTakvimKalemi {
  tarih: string;
  tur: string;
  baslik: string;
  musteri_id: string;
  firma_adi: string;
  client_org_id: string | null;
  /** Only from that client's own past payments; null when it has none. */
  tutar_kurus: number | null;
  gecmiste_odeme_var: boolean;
}

export interface SmmmTakvim {
  baslangic: string;
  bitis: string;
  kalemler: SmmmTakvimKalemi[];
  /** The day rules are not yet checked against GİB/SGK's own text while false. */
  kurallar_dogrulandi: boolean;
}

export async function getSmmmTakvim(gun = 45): Promise<SmmmTakvim> {
  const res = await apiClient.get<{ data: SmmmTakvim }>("/smmm/takvim", { params: { gun } });
  return res.data.data;
}

// ── What the agent learned from this company's accountant ───────────────────

export interface OgrenilmisKural {
  id: string;
  /** The recurring description, normalised (what changes monthly removed). */
  anahtar: string;
  hesap_kodu: string;
  hesap_adi: string | null;
  /** How many times the accountant corrected it to this account. */
  onay_sayisi: number;
  /** In force: enough corrections and no rival account of similar weight. */
  aktif: boolean;
}

export async function getOgrenilmisKurallar(): Promise<OgrenilmisKural[]> {
  const res = await apiClient.get<{ data: { kurallar: OgrenilmisKural[] } }>("/smmm/kurallar");
  return res.data.data.kurallar ?? [];
}

export async function deleteOgrenilmisKural(id: string): Promise<void> {
  await apiClient.delete(`/smmm/kurallar/${id}`);
}

export async function exportDefensibilityPacket(packetId: string): Promise<Blob> {
  const res = await apiClient.get(`/smmm/defensibility/${packetId}/export`, {
    responseType: "blob",
  });
  return res.data as Blob;
}
