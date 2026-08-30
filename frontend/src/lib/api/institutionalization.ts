import { apiClient } from "@/lib/api/client";

// ── Kurumsallaşma Endeksi ──────────────────────────────────────────────────

export interface IndexDimension {
  key: string;
  label: string;
  score: number;
  weight: number;
  why: string;
}

export interface IndexRecommendation {
  dimension: string;
  text: string;
}

export interface InstitutionalizationSnapshot {
  id?: string;
  overall_score: number;
  grade: "A" | "B" | "C" | "D" | "E";
  dimensions: IndexDimension[];
  recommendations: IndexRecommendation[];
  signals: Record<string, unknown>;
  computed_at: string | null;
}

export interface IndexHistoryPoint {
  overall_score: number;
  grade: string;
  computed_at: string | null;
}

export async function getInstitutionalizationIndex(): Promise<InstitutionalizationSnapshot> {
  const res = await apiClient.get<{ data: InstitutionalizationSnapshot }>(
    "/institutionalization"
  );
  return res.data.data;
}

export async function recomputeInstitutionalizationIndex(): Promise<InstitutionalizationSnapshot> {
  const res = await apiClient.post<{ data: InstitutionalizationSnapshot }>(
    "/institutionalization/compute"
  );
  return res.data.data;
}

export async function getInstitutionalizationHistory(): Promise<IndexHistoryPoint[]> {
  const res = await apiClient.get<{ data: { points: IndexHistoryPoint[] } }>(
    "/institutionalization/history"
  );
  return res.data.data.points;
}
