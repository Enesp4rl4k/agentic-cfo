import { apiClient } from "@/lib/api/client";

// ── GİB e-Fatura ────────────────────────────────────────────────────────────
// The shortest path to real data: a company's own incoming and outgoing
// invoices, pulled from the Revenue Administration rather than typed into a
// spreadsheet. The endpoints existed and had no surface at all.

interface Envelope<T> {
  data: T;
  error: string | null;
}

export interface EFaturaStatus {
  configured: boolean;
  sandbox: boolean;
  /** Masked — the server never returns the whole number. */
  vkn?: string;
  base_url?: string;
  message: string;
  setup_guide?: Record<string, string>;
  sandbox_url?: string;
}

export interface EFaturaSyncResult {
  job_id: string | null;
  invoice_count: number;
  inbound_count?: number;
  outbound_count?: number;
  period?: string;
  /** Lira, as GİB reports them — not kuruş. */
  total_income?: number;
  total_expense?: number;
  /** Whether the CFO analysis was actually enqueued. */
  queued?: boolean;
  poll_url?: string | null;
  message?: string;
}

export async function fetchEFaturaStatus(): Promise<EFaturaStatus> {
  const res = await apiClient.get<Envelope<EFaturaStatus>>("/efatura/status");
  return res.data.data;
}

export async function syncEFatura(body: {
  start_date: string;
  end_date: string;
  analyze?: boolean;
}): Promise<EFaturaSyncResult> {
  const res = await apiClient.post<Envelope<EFaturaSyncResult>>(
    "/efatura/sync",
    { analyze: true, ...body },
  );
  return res.data.data;
}
