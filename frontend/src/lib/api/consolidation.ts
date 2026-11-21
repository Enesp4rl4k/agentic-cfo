import { apiClient } from "@/lib/api/client";

interface Envelope<T> {
  data: T;
  error: string | null;
}

export interface IntercompanyElimination {
  item_id: string;
  org_id: string;
  org_name: string;
  direction: "receivable" | "payable";
  counterparty: string;
  amount_cents: number;
  due_date: string;
  week: number;
  eliminated_reason: string;
}

export interface ConsolidatedWeek {
  week: number;
  start_date: string;
  end_date: string;
  gross_inflow_cents: number;
  gross_outflow_cents: number;
  eliminated_inflow_cents: number;
  eliminated_outflow_cents: number;
  net_inflow_cents: number;
  net_outflow_cents: number;
  consolidated_balance_cents: number;
}

export interface ConsolidatedCashRadar {
  group_name: string;
  participating_org_ids: string[];
  total_starting_cash_cents: number;
  weeks: ConsolidatedWeek[];
  eliminations: IntercompanyElimination[];
  total_eliminated_cents: number;
  insights: string[];
}

export async function getConsolidatedRadar(
  orgIds: string[],
  groupName = "Konsolide Grup"
): Promise<ConsolidatedCashRadar> {
  const res = await apiClient.post<Envelope<ConsolidatedCashRadar>>("/consolidation/radar", {
    org_ids: orgIds,
    group_name: groupName,
  });
  return res.data.data;
}
