import { apiClient } from "@/lib/api/client";

// The company ledger (backend app/services/ledger.py): one record of the money,
// whichever files brought it. Amounts are kuruş.

export interface LedgerSummary {
  /** What the newest analysis added. */
  last_upload: { filename: string; new: number; already: number; possible_duplicate: number } | null;
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
