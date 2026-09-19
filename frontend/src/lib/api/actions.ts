import { apiClient } from "./client";

export interface PendingAction {
  id: string;
  debate_id: string;
  description: string;
  responsible_agent: string;
  status: string;
  created_at: string;
}

export interface GetPendingActionsResponse {
  status: string;
  count: number;
  actions: PendingAction[];
}

export async function getPendingActions(): Promise<PendingAction[]> {
  const res = await apiClient.get<GetPendingActionsResponse>("/actions/pending");
  return res.data.actions;
}

export async function approveAction(actionId: string, customParams?: Record<string, any>) {
  const res = await apiClient.post(`/actions/${actionId}/approve`, { custom_params: customParams });
  return res.data;
}

export async function rejectAction(actionId: string, reason?: string) {
  const res = await apiClient.post(`/actions/${actionId}/reject`, { reason: reason || "CEO tarafından uygun bulunmadı" });
  return res.data;
}
