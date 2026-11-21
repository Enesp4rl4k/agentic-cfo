import { apiClient } from "@/lib/api/client";

// Payment plan changes (backend app/api/plan_changes.py): a member proposes a new date for a payable,
// an owner or an admin decides. Nothing here edits a date directly.

export type PlanChangeStatus = "pending" | "approved" | "rejected" | "withdrawn";

export interface PlanChange {
  id: string;
  open_item_id: string;
  counterparty: string | null;
  description: string | null;
  amount_cents: number | null;
  from_date: string;
  to_date: string;
  status: PlanChangeStatus;
  requested_by: string;
  requested_at: string;
  request_note: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
}

interface Envelope<T> {
  data: T;
  meta?: { can_decide?: boolean };
  error: string | null;
}

export async function listPlanChanges(status: PlanChangeStatus | "all" = "pending"): Promise<{ changes: PlanChange[]; canDecide: boolean }> {
  const res = await apiClient.get<Envelope<PlanChange[]>>("/ledger/plan-changes", { params: { status } });
  return { changes: res.data.data, canDecide: Boolean(res.data.meta?.can_decide) };
}

export async function proposePlanChange(openItemId: string, toDate: string, note?: string): Promise<PlanChange> {
  const res = await apiClient.post<Envelope<PlanChange>>("/ledger/plan-changes", {
    open_item_id: openItemId,
    to_date: toDate,
    note: note ?? null,
  });
  return res.data.data;
}

export async function decidePlanChange(id: string, action: "approve" | "reject", note?: string): Promise<PlanChange> {
  const res = await apiClient.post<Envelope<PlanChange>>(`/ledger/plan-changes/${id}/${action}`, { note: note ?? null });
  return res.data.data;
}

export async function withdrawPlanChange(id: string): Promise<PlanChange> {
  const res = await apiClient.post<Envelope<PlanChange>>(`/ledger/plan-changes/${id}/withdraw`);
  return res.data.data;
}

/** The sentence the server gave for a refusal, or null when the error is not one of its answers. */
export function planChangeError(error: unknown): string | null {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : null;
}
