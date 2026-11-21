import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/pilot-schema";

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
  /** The period these figures cover: the last 12 months of data unless one was asked for. */
  period: {
    start: string | null;
    end: string | null;
    months: number;
    label: string | null;
    is_default: boolean;
    available_start: string | null;
    available_end: string | null;
    available_months: number;
  };
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

export interface SettlementItem {
  counterparty: string | null;
  description: string | null;
  amount_cents: number;
  due_date: string | null;
}

export interface ProposedSettlement {
  id: string;
  amount_cents: number;
  row: LedgerRow;
  item: SettlementItem;
  /** One transfer may pay several invoices of one customer; the answer covers all of them. */
  items: SettlementItem[];
}

export async function getProposedSettlements(): Promise<ProposedSettlement[]> {
  const res = await apiClient.get<Envelope<ProposedSettlement[]>>("/ledger/settlements/proposed");
  return res.data.data;
}

export async function resolveSettlement(matchId: string, action: "confirm" | "reject"): Promise<void> {
  await apiClient.post(`/ledger/settlements/${matchId}/resolve`, { action });
}

// The radar's shape is generated from the backend's schema (pilot-schema.ts);
// a field the backend adds or renames is a type error here, not a blank on screen.
type Schemas = components["schemas"];
export type RadarItem = Schemas["RadarItemOut"];
export type RadarWeek = Schemas["RadarWeekOut"];
export type RadarAction = Schemas["RadarActionOut"];
export type CashRadar = Schemas["CashRadarOut"];

export async function getCashRadar(): Promise<CashRadar> {
  const res = await apiClient.get<Envelope<CashRadar>>("/ledger/cash-radar");
  return res.data.data;
}

// The Monday briefing has one client: lib/api/briefing.ts. A second copy here
// was written by hand, lacked the fingerprint, and answered with a 422.
export { getMondayBriefing, respondToMondayBriefing } from "@/lib/api/briefing";
export type { MondayBriefing } from "@/lib/api/briefing";
