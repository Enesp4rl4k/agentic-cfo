import { apiClient } from "@/lib/api/client";

// Verilerimi bağla — mirrors backend app/api/veri_baglama.py.
// Files are recognised from their columns; nothing is estimated or guessed.

export type TanimaDurumu = "kesin" | "belirsiz" | "taninmadi";
export type EklemeDurumu =
  | "eklendi"
  | "secim_gerekli"
  | "taninmadi"
  | "reddedildi"
  | "finansal_dosya_gerekli"
  /** The same file appeared twice in one submission; it was added once. */
  | "mukerrer";

export interface TurSecenegi {
  tur: string;
  alan: string;
  etiket: string;
}

export interface Aday extends TurSecenegi {
  /** Parser column → the header it was read from. */
  eslesen: Record<string, string>;
  /** Required columns not found. */
  eksik: string[];
}

export interface Tanima {
  durum: TanimaDurumu;
  tur: string | null;
  alan: string | null;
  etiket: string | null;
  adaylar: Aday[];
  satir_sayisi: number;
  sayfa: string | null;
  ozet: string;
  sutunlar: string[];
}

export interface DosyaSonucu {
  dosya: string;
  durum: EklemeDurumu;
  mesaj?: string;
  tanima: Tanima;
  job_id?: string;
  source_id?: string;
  /** The page this file feeds, e.g. "/chro". */
  sayfa?: string;
}

interface Envelope<T> {
  data: T;
  error: string | null;
}

export async function veriTurleri(): Promise<TurSecenegi[]> {
  const res = await apiClient.get<Envelope<TurSecenegi[]>>("/veri/turler");
  return res.data.data;
}

export async function veriEkle(
  files: File[],
  secimler?: Record<string, string>,
  jobId?: string | null,
): Promise<{ job_id: string | null; dosyalar: DosyaSonucu[] }> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  if (secimler && Object.keys(secimler).length) form.append("secimler", JSON.stringify(secimler));
  if (jobId) form.append("job_id", jobId);
  const res = await apiClient.post<Envelope<{ job_id: string | null; dosyalar: DosyaSonucu[] }>>(
    "/veri/ekle",
    form,
    { headers: { "Content-Type": "multipart/form-data" }, timeout: 120_000 },
  );
  return res.data.data;
}

// ── E-postayla veri — backend app/api/email_ingest.py ────────────────────────

export interface EpostaAdresi {
  /** False when the server has no mail inbox configured; then there is no address. */
  acik: boolean;
  adres: string | null;
  olusturuldu?: string | null;
  nasil?: string[];
  mesaj?: string;
}

export interface GelenEposta {
  id: string;
  alindi: string | null;
  gonderen: string;
  konu: string;
  dosyalar: Array<{ dosya: string | null; durum: string; mesaj?: string; etiket?: string | null; sayfa?: string }>;
}

export async function epostaAdresi(): Promise<EpostaAdresi> {
  const res = await apiClient.get<Envelope<EpostaAdresi>>("/email/ingest-address");
  return res.data.data;
}

export async function epostaAdresiYenile(): Promise<EpostaAdresi> {
  const res = await apiClient.post<Envelope<EpostaAdresi>>("/email/ingest-address/yenile", {});
  return res.data.data;
}

export async function gelenEpostalar(): Promise<GelenEposta[]> {
  const res = await apiClient.get<Envelope<GelenEposta[]>>("/email/history");
  return res.data.data;
}
