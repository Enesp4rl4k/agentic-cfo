import { apiClient } from "@/lib/api/client";

// ── Multi-domain data sources ───────────────────────────────────────────────
// The path from a synthetic C-suite to a real one. Without a file for a domain,
// its kernel derives everything from CFO financials and sector benchmarks and
// says so (`data_source: "benchmark"`). Upload one, run the CEO pipeline over
// the job, and that domain's agent reads actual content instead.
//
// Both halves of that were already wired to each other — /datasource stores the
// file and POST /ceo/analyze-from-job reads it — and neither had a door.

interface Envelope<T> {
  data: T;
  error: string | null;
}

export type DataDomain = "cto" | "chro" | "cmo" | "coo";

/** Which files each domain accepts, in the order they are worth uploading. */
export const DOMAIN_SOURCES: Record<
  DataDomain,
  { label: string; types: Array<{ value: string; label: string }> }
> = {
  cto: {
    label: "CTO — Teknoloji",
    types: [
      { value: "cloud_billing", label: "Bulut faturası" },
      { value: "git_log", label: "Git commit dökümü" },
      { value: "incident_log", label: "Olay (incident) kaydı" },
      { value: "sprint_data", label: "Sprint verisi" },
    ],
  },
  chro: {
    label: "CHRO — İnsan Kaynakları",
    types: [
      { value: "headcount", label: "Kadro listesi" },
      { value: "attrition", label: "Ayrılma verisi" },
      { value: "compensation", label: "Ücret verisi" },
    ],
  },
  cmo: {
    label: "CMO — Pazarlama",
    types: [
      { value: "campaign", label: "Kampanya performansı" },
      { value: "funnel", label: "Dönüşüm hunisi" },
      { value: "cohort", label: "Kohort analizi" },
    ],
  },
  coo: {
    label: "COO — Operasyon",
    types: [
      { value: "sla", label: "SLA / hizmet seviyesi" },
      { value: "process", label: "Süreç verisi" },
      { value: "resource", label: "Kaynak kullanımı" },
    ],
  },
};

export interface AttachedSource {
  source_id: string;
  source_type: string;
  filename: string;
  file_size_bytes: number;
  label: string | null;
  pipeline_kwarg: string | null;
  created_at: string;
}

export interface AttachedSources {
  job_id: string;
  total: number;
  by_domain: Record<string, AttachedSource[]>;
}

export async function listDataSources(jobId: string): Promise<AttachedSources> {
  const res = await apiClient.get<Envelope<AttachedSources>>(`/datasource/${jobId}`);
  return res.data.data;
}

export async function uploadDataSource(
  jobId: string,
  domain: DataDomain,
  sourceType: string,
  file: File,
): Promise<AttachedSource & { domain: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiClient.post<Envelope<AttachedSource & { domain: string }>>(
    `/datasource/${jobId}/${domain}/${sourceType}`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return res.data.data;
}

export async function deleteDataSource(jobId: string, sourceId: string): Promise<void> {
  await apiClient.delete(`/datasource/${jobId}/${sourceId}`);
}

/**
 * Run the whole C-suite over a job, reading every attached domain file.
 *
 * `/ceo/analyze` takes a payload; this one reads what was uploaded. It is the
 * only route that turns an attached file into a real `data_source`.
 */
export async function analyzeCSuiteFromJob(jobId: string): Promise<unknown> {
  const res = await apiClient.post<Envelope<unknown>>(
    `/ceo/analyze-from-job/${jobId}`,
    {},
  );
  return res.data.data;
}
