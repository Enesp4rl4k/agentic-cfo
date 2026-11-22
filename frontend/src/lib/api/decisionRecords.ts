import { apiClient } from "@/lib/api/client";

// The decision record, read-only (backend app/api/decision_records.py): who decided what, when, on which basis.
// The company-wide log is for owner, admin, cfo and smmm; one object's history is open to any member.

export interface DecisionEntry {
  id: string;
  kind: string;
  target_type: string;
  target_id: string;
  outcome: string;
  decided_by: string | null;
  decided_via: "human" | "rule" | "system" | string;
  rule_id: string | null;
  decided_at: string;
  reason: string | null;
  evidence_refs: { type: string; id: string }[];
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  supersedes_id: string | null;
  superseded_by_id: string | null;
}

export interface DecisionFilters {
  kind?: string;
  decidedBy?: string;
  since?: string; // YYYY-MM-DD, start of that day (UTC)
  until?: string; // YYYY-MM-DD, inclusive: sent as the next day, the API's bound is exclusive
  targetType?: string;
  targetId?: string;
}

export const DECISIONS_PAGE_SIZE = 25;

function nextDay(day: string): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

export async function listDecisionEntries(
  filters: DecisionFilters = {},
  page = 0,
): Promise<{ entries: DecisionEntry[]; total: number }> {
  const params: Record<string, string | number> = { limit: DECISIONS_PAGE_SIZE, offset: page * DECISIONS_PAGE_SIZE };
  if (filters.kind) params.kind = filters.kind;
  if (filters.decidedBy) params.decided_by = filters.decidedBy;
  if (filters.since) params.since = filters.since;
  if (filters.until) params.until = nextDay(filters.until);
  if (filters.targetType && filters.targetId) {
    params.target_type = filters.targetType;
    params.target_id = filters.targetId;
  }
  const res = await apiClient.get<{ data: DecisionEntry[]; meta: { total: number } }>("/decision-records", { params });
  return { entries: res.data.data, total: res.data.meta.total };
}
