import { apiClient } from "@/lib/api/client";

// Rows the system would not book alone (backend app/api/held_rows.py). Nothing here decides for the
// person: it lists what waits and sends the answer, which the server records as a decision.

export type HeldReason =
  | "confidence_unknown"
  | "confidence_low"
  | "currency_unknown"
  | "currency_unreadable"
  | "direction_unknown"
  | "direction_file_unknown"
  | "balance_mismatch"
  | "balance_outside_chain"
  | "summary_suspect"
  | "line_unreadable"
  | "amount_uncertain"
  | "amount_zero"
  | "malformed_row"
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

export type FileAnswer = "only_income" | "only_expense" | "as_read" | "balance" | "inverted" | "sign_correct" | "sign_inverted" | "mixed";

export type FileReason = "no_signal" | "balance_contradicts" | "convention_unverified" | "balance_inconclusive" | "sign_unconfirmed";

export interface FileQuestion {
  job_id: string;
  file_key: string;
  reason: FileReason;
  /** Whether the file names its bank account: without that an answer cannot be remembered for it. */
  identity: boolean;
  rows: number;
  options: FileAnswer[];
  question: {
    columns: Array<{ name: string; role: string | null }>;
    samples: Array<Record<string, string>>;
    note?: string;
    /** For a debit/credit reading nobody could verify: what each word was read as. */
    mapping?: Array<{ label: string; means: "income" | "expense" }>;
    /** For a sign question: what each reading would book, in kuruş, and whether the file has one sign only. */
    totals?: { as_read: { income: number; expense: number }; inverted: { income: number; expense: number } };
    uniform?: boolean;
  } | null;
}

export interface DirectionMapping {
  id: string;
  signature: string;
  reason: FileReason;
  answer: FileAnswer;
  columns: string;
  created_at: string | null;
}

/** `canRemember`: only an owner, admin or the accountant may make an answer a standing rule for a format. */
export async function listFileQuestions(): Promise<{ files: FileQuestion[]; canRemember: boolean }> {
  const res = await apiClient.get<Envelope<{ files: FileQuestion[]; can_remember: boolean }>>("/held-rows/file-questions");
  return { files: res.data.data.files, canRemember: res.data.data.can_remember };
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
