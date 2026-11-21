import { apiClient } from "@/lib/api/client";

// Rows the system would not book alone (backend app/api/held_rows.py). Nothing here decides for the
// person: it lists what waits and sends the answer, which the server records as a decision.

export type HeldReason =
  | "confidence_unknown"
  | "confidence_low"
  | "currency_unknown"
  | "direction_unknown"
  | "direction_file_unknown"
  | "amount_unreadable"
  | "date_unreadable"
  | "document_held_together";

export interface HeldRow {
  id: string;
  job_id: string;
  source: { job_id: string; filename: string | null; document_id: string | null };
  reasons: HeldReason[];
  reason_labels: string[];
  /** null = unknown. Never shown as a percentage. */
  confidence: number | null;
  amount_cents: number | null;
  currency: string | null;
  type: "income" | "expense" | null;
  /** The document did not state the currency: the confirmed company currency was assumed. */
  currency_assumed: boolean;
  /** Set when the row waits as part of a file whose direction is one question (see FileQuestion). */
  direction_file: string | null;
  description: string | null;
  vendor: string | null;
  transaction_date: string | null;
  document_id: string | null;
}

export interface HeldCorrection {
  type?: "income" | "expense";
  currency?: string;
  transaction_date?: string;
  amount_cents?: number;
}

export interface HeldAction {
  ids?: string[];
  job_id?: string;
  reason?: HeldReason;
  document_id?: string;
  corrections?: Record<string, HeldCorrection>;
}

export interface BaseCurrency {
  currency: string | null;
  confirmed: boolean;
  waiting_for_currency: number;
}

interface Envelope<T> {
  data: T;
  error: string | null;
}

export async function listHeldRows(jobId?: string): Promise<HeldRow[]> {
  const res = await apiClient.get<Envelope<{ count: number; rows: HeldRow[] }>>("/held-rows", {
    params: jobId ? { job_id: jobId } : undefined,
  });
  return res.data.data.rows;
}

export async function releaseHeldRows(action: HeldAction): Promise<void> {
  await apiClient.post("/held-rows/release", action);
}

export async function rejectHeldRows(action: HeldAction): Promise<void> {
  await apiClient.post("/held-rows/reject", action);
}

export async function getBaseCurrency(): Promise<BaseCurrency> {
  const res = await apiClient.get<Envelope<BaseCurrency>>("/org/base-currency");
  return res.data.data;
}

export async function confirmBaseCurrency(currency: string): Promise<void> {
  await apiClient.post("/org/base-currency", { currency });
}

// A statement file whose direction nobody could place: ONE question for the file, answered once and
// applied to every row (backend app/services/held_direction.py).

export type FileAnswer = "all_income" | "all_expense" | "as_read" | "balance" | "mixed";

export interface FileQuestion {
  job_id: string;
  file_key: string;
  reason: "no_signal" | "balance_contradicts";
  rows: number;
  options: FileAnswer[];
  question: {
    columns: Array<{ name: string; role: string | null }>;
    samples: Array<Record<string, string>>;
    note?: string;
  } | null;
}

export interface DirectionMapping {
  id: string;
  signature: string;
  reason: "no_signal" | "balance_contradicts";
  answer: FileAnswer;
  columns: string;
  created_at: string | null;
}

export async function listFileQuestions(): Promise<FileQuestion[]> {
  const res = await apiClient.get<Envelope<{ files: FileQuestion[] }>>("/held-rows/file-questions");
  return res.data.data.files;
}

export async function answerFileDirection(body: {
  job_id: string;
  file_key: string;
  answer: FileAnswer;
  remember: boolean;
}): Promise<void> {
  await apiClient.post("/held-rows/file-direction", body);
}

export async function listDirectionMappings(): Promise<DirectionMapping[]> {
  const res = await apiClient.get<Envelope<{ mappings: DirectionMapping[] }>>("/held-rows/direction-mappings");
  return res.data.data.mappings;
}

export async function revokeDirectionMapping(id: string): Promise<void> {
  await apiClient.delete(`/held-rows/direction-mappings/${id}`);
}
