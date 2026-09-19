import { apiClient } from "@/lib/api/client";

// One engine per domain. Mirrors backend app/agents/orchestration/domain_analysis.py:
// real files attached to the job → the domain's orchestrator runs on them;
// otherwise no analysis and no estimate — what is missing, and how to get it.

export type AlanKodu = "cto" | "cmo" | "coo" | "chro" | "risk" | "audit" | "compliance";

export type AlanDurumu = "hazir" | "analiz_edildi" | "eksik_veri" | "veri_yok";

export interface AlanKaynagi {
  tip: string;
  etiket: string;
  yuklendi: boolean;
  /** How a non-technical user exports this file from tools they already use. */
  nasil: string;
  dosya: string | null;
}

export interface CfoKalemi {
  kategori: string;
  etiket: string;
  tutar_kurus?: number;
  gelire_orani?: number | null;
  deger?: number;
  birim?: string;
  /** Where the figure came from — always shown. */
  kaynak: string;
}

export interface Alan {
  alan: AlanKodu;
  ad: string;
  durum: AlanDurumu;
  hepsi_gerekli: boolean;
  kaynaklar: AlanKaynagi[];
  eksik: string[];
  cfo_gercek: { var: boolean; kalemler: CfoKalemi[] };
  bagli_kaynak_sinyalleri: Record<string, unknown> | null;
  /** Present after a run. Null when there was not enough data. */
  sonuc?: Record<string, unknown> | null;
  neden?: string;
  provenance?: { data_source: "real"; synthetic: false; basis: string };
}

interface Envelope<T> {
  data: T;
  error: string | null;
}

export async function getDomain(jobId: string, alan: AlanKodu): Promise<Alan> {
  const res = await apiClient.get<Envelope<Alan>>(`/analysis/${jobId}/domains/${alan}`);
  return res.data.data;
}

export async function runDomain(jobId: string, alan: AlanKodu): Promise<Alan> {
  const res = await apiClient.post<Envelope<Alan>>(`/analysis/${jobId}/domains/${alan}`, {});
  return res.data.data;
}

export async function uploadDomainFile(
  jobId: string,
  alan: AlanKodu,
  tip: string,
  file: File,
): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  await apiClient.post(`/datasource/${jobId}/${alan}/${tip}`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
}
