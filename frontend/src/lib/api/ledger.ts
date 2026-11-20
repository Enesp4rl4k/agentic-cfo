import { apiClient } from "@/lib/api/client";

// The company ledger (backend app/services/ledger.py): one record of the money,
// whichever files brought it. Amounts are kuruş.

export interface LedgerSummary {
  /** What the newest analysis added. */
  last_upload: { filename: string; new: number; already: number; possible_duplicate: number } | null;
  open_items: { receivable_cents: number; payable_cents: number; no_due_date: number; other_currency: number };
  rows: number;
  revenue_cents: number;
  expense_cents: number;
  possible_duplicates: number;
  period: { start: string | null; end: string | null; months: number };
}

export interface LedgerRow {
  id: string;
  transaction_date: string;
  amount_cents: number;
  direction: string;
  description: string | null;
  matches?: LedgerRow[];
}

interface Envelope<T> {
  data: T;
  error: string | null;
}

export async function getLedgerSummary(): Promise<LedgerSummary> {
  const res = await apiClient.get<Envelope<LedgerSummary>>("/ledger/summary");
  return res.data.data;
}

export async function getPossibleDuplicates(): Promise<LedgerRow[]> {
  const res = await apiClient.get<Envelope<LedgerRow[]>>("/ledger/possible-duplicates");
  return res.data.data;
}

export async function resolveDuplicate(rowId: string, action: "keep" | "exclude"): Promise<void> {
  await apiClient.post(`/ledger/rows/${rowId}/resolve`, { action });
}

export interface ProposedSettlement {
  id: string;
  amount_cents: number;
  row: LedgerRow;
  item: { counterparty: string | null; description: string | null; amount_cents: number; due_date: string | null };
}

export async function getProposedSettlements(): Promise<ProposedSettlement[]> {
  const res = await apiClient.get<Envelope<ProposedSettlement[]>>("/ledger/settlements/proposed");
  return res.data.data;
}

export async function resolveSettlement(matchId: string, action: "confirm" | "reject"): Promise<void> {
  await apiClient.post(`/ledger/settlements/${matchId}/resolve`, { action });
}

export interface RadarItem {
  id: string;
  counterparty: string | null;
  description: string | null;
  amount_cents: number;
  due_date: string | null;
  expected_date: string;
  delay_days: number;
  is_overdue: boolean;
}

export interface RadarWeek {
  week: number;
  start_date: string;
  end_date: string;
  inflow_cents: number;
  outflow_cents: number;
  net_cents: number;
  /** The balance when the starting cash is known; otherwise movement since the anchor day. */
  end_balance_cents: number;
  receivables: RadarItem[];
  payables: RadarItem[];
}

export interface RadarAction {
  type: string;
  title: string;
  detail: string;
  amount_cents: number;
}

export interface CashRadar {
  anchor_date: string;
  /** Null when no bank statement proved a closing balance. */
  starting_cash_cents: number | null;
  starting_cash_as_of: string | null;
  weeks: RadarWeek[];
  shortfall: {
    week: number;
    week_start: string;
    week_end: string;
    shortfall_cents: number;
    driver: string;
    actions: RadarAction[];
  } | null;
  overdue_receivables: RadarItem[];
  overdue_payables_cents: number;
  undated_receivables_cents: number;
  undated_payables_cents: number;
  beyond_horizon_cents: number;
  other_currency_items: number;
  not_included: string[];
}

export async function getCashRadar(): Promise<CashRadar> {
  const res = await apiClient.get<Envelope<CashRadar>>("/ledger/cash-radar");
  return res.data.data;
}

export interface MondayBriefing {
  briefing_id: string;
  org_id: string;
  week_start: string;
  week_end: string;
  starting_cash_cents: number | null;
  net_change_cents: number;
  end_balance_cents: number;
  approaching_title: string;
  approaching_amount_cents: number;
  approaching_date: string | null;
  action_type: string;
  action_title: string;
  action_detail: string;
  action_amount_cents: number;
  sentence_radar: string;
  sentence_obligation: string;
  sentence_action: string;
  full_text: string;
  verified: boolean;
  fallback_used: boolean;
}

export async function getMondayBriefing(anchorDate?: string): Promise<MondayBriefing> {
  const params = anchorDate ? { anchor_date: anchorDate } : undefined;
  const res = await apiClient.get<Envelope<MondayBriefing>>("/briefing/monday", { params });
  return res.data.data;
}

export async function respondToBriefing(
  response: "done" | "deferred" | "dismissed",
  note?: string,
  anchorDate?: string,
): Promise<{ decision_id: string; status: string; chosen_option_label: string; briefing_id: string }> {
  const res = await apiClient.post<Envelope<{ decision_id: string; status: string; chosen_option_label: string; briefing_id: string }>>(
    "/briefing/monday/respond",
    { response, note, anchor_date: anchorDate },
  );
  return res.data.data;
}
