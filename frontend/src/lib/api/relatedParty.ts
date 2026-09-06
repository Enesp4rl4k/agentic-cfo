import { apiClient } from "@/lib/api/client";

// ── İlişkili Taraf Sicili ────────────────────────────────────────────────────

export type RelationshipType =
  | "ortak"
  | "yonetici"
  | "aile"
  | "istirak"
  | "ana_ortaklik"
  | "kilit_personel"
  | "diger";

export const RELATIONSHIP_LABELS: Record<RelationshipType, string> = {
  ortak: "Ortak",
  yonetici: "Yönetici",
  aile: "Aile üyesi",
  istirak: "İştirak",
  ana_ortaklik: "Ana ortaklık",
  kilit_personel: "Kilit personel",
  diger: "Diğer",
};

export interface RelatedParty {
  id: string;
  name: string;
  normalized_name: string;
  relationship_type: RelationshipType;
  tax_id: string | null;
  note: string | null;
  active: boolean;
  created_at: string | null;
}

export interface CounterpartySuggestion {
  vendor: string;
  normalized_name: string;
  transaction_count: number;
  total_kurus: number;
}

export interface PartyMatch {
  party_id: string;
  party_name: string;
  relationship_type: RelationshipType;
  /** What the match keyed on, so a reviewer can judge it. */
  matched_on: "tax_id" | "exact_name" | "name_in_text";
  matched_value: string;
}

interface Envelope<T> {
  data: T;
  error: string | null;
}

export async function listRelatedParties(includeInactive = false) {
  const res = await apiClient.get<
    Envelope<{ parties: RelatedParty[]; count: number; relationship_types: string[] }>
  >("/related-parties", { params: { include_inactive: includeInactive } });
  return res.data.data;
}

export async function createRelatedParty(body: {
  name: string;
  relationship_type: RelationshipType;
  tax_id?: string | null;
  note?: string | null;
}) {
  const res = await apiClient.post<Envelope<RelatedParty>>("/related-parties", body);
  return res.data.data;
}

export async function updateRelatedParty(
  id: string,
  body: Partial<{
    name: string;
    relationship_type: RelationshipType;
    tax_id: string | null;
    note: string | null;
    active: boolean;
  }>,
) {
  const res = await apiClient.patch<Envelope<RelatedParty>>(`/related-parties/${id}`, body);
  return res.data.data;
}

/** Deactivates rather than deletes — a sealed period must stay explainable. */
export async function deactivateRelatedParty(id: string) {
  const res = await apiClient.delete<Envelope<{ id: string; active: boolean }>>(
    `/related-parties/${id}`,
  );
  return res.data.data;
}

/** Recurring counterparties not yet in the register. */
export async function fetchCounterpartySuggestions(limit = 25) {
  const res = await apiClient.get<
    Envelope<{
      suggestions: CounterpartySuggestion[];
      count: number;
      registry_size: number;
    }>
  >("/related-parties/suggestions", { params: { limit } });
  return res.data.data;
}

/** Would this counterparty be flagged, and on what evidence? */
export async function checkCounterparty(body: {
  vendor?: string;
  description?: string;
  tax_id?: string;
}) {
  const res = await apiClient.post<
    Envelope<{ is_related_party: boolean; match: PartyMatch | null; registry_size: number }>
  >("/related-parties/check", body);
  return res.data.data;
}
