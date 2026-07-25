import { apiClient } from "@/lib/api/client";
import type { AnalysisJob, DashboardData, ReportMeta, Transaction } from "@/types";

export async function uploadFile(file: File): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiClient.post<{ data: { job_id: string }; error: null }>(
    "/upload",
    form,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return res.data.data;
}

export async function startAnalysis(jobId: string): Promise<void> {
  await apiClient.post(`/analyze/${jobId}`);
}

export async function getJobStatus(jobId: string): Promise<AnalysisJob> {
  const res = await apiClient.get<{ data: AnalysisJob; error: null }>(
    `/analysis/${jobId}`
  );
  return res.data.data;
}

export async function approveJob(jobId: string): Promise<void> {
  await apiClient.post(`/analysis/${jobId}/approve`);
}

export async function getDashboard(jobId: string): Promise<DashboardData> {
  const res = await apiClient.get<{ data: DashboardData; error: null }>(
    `/dashboard/${jobId}`
  );
  return res.data.data;
}

export async function listReports(jobId: string): Promise<ReportMeta[]> {
  const res = await apiClient.get<{ data: ReportMeta[]; error: null }>(
    `/reports/${jobId}`
  );
  return res.data.data;
}

export function getDownloadUrl(reportId: string): string {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return `${base}/api/v1/reports/${reportId}/download`;
}

export interface JobSummary {
  job_id: string;
  status: string;
  filename: string;
  created_at: string;
  completed_at: string | null;
}

export async function listJobs(): Promise<JobSummary[]> {
  const res = await apiClient.get<{ data: JobSummary[]; error: null }>("/jobs");
  return res.data.data;
}

export interface TransactionsPage {
  total: number;
  limit: number;
  offset: number;
  transactions: (Transaction & { id: string })[];
}

export async function listTransactions(
  jobId: string,
  limit = 100,
  offset = 0
): Promise<TransactionsPage> {
  const res = await apiClient.get<{ data: TransactionsPage; error: null }>(
    `/analysis/${jobId}/transactions`,
    { params: { limit, offset } }
  );
  return res.data.data;
}

export async function correctCategory(
  transactionId: string,
  category: string,
  applyAlways = false
): Promise<void> {
  await apiClient.patch(`/transactions/${transactionId}/category`, {
    category,
    apply_always: applyAlways,
  });
}

// ── Anomaly API ───────────────────────────────────────────────────────────────

export interface AnomalyItem {
  id: string;
  job_id: string;
  anomaly_type: string;
  severity: "low" | "medium" | "high" | "critical";
  title: string;
  description: string;
  transaction_ids: string[] | null;
  evidence: Record<string, unknown> | null;
  confidence: number | null;
  acknowledged: boolean;
  acknowledged_at: string | null;
  created_at: string;
}

export interface AnomaliesData {
  job_id: string;
  total: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
  anomalies: AnomalyItem[];
}

export async function listAnomalies(
  jobId: string,
  severity?: string
): Promise<AnomaliesData> {
  const params = severity ? { severity } : {};
  const res = await apiClient.get<{ data: AnomaliesData; error: null }>(
    `/anomalies/${jobId}`,
    { params }
  );
  return res.data.data;
}

export async function scanAnomalies(jobId: string): Promise<{
  scanned: number;
  anomalies_found: number;
  critical: number;
  high: number;
  narrative: string;
}> {
  const res = await apiClient.post<{
    data: { scanned: number; anomalies_found: number; critical: number; high: number; narrative: string };
    error: null;
  }>(`/anomalies/scan/${jobId}`);
  return res.data.data;
}

export async function acknowledgeAnomaly(
  anomalyId: string,
  acknowledged = true
): Promise<void> {
  await apiClient.patch(`/anomalies/${anomalyId}/acknowledge`, { acknowledged });
}

// ── Chat API ──────────────────────────────────────────────────────────────────

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export async function sendChatMessage(
  jobId: string,
  question: string,
  history: ChatMessage[] = []
): Promise<string> {
  const res = await apiClient.post<{ data: { answer: string }; error: null }>(
    `/chat/job/${jobId}`,
    {
      question,
      stream: false,
      conversation_history: history,
    }
  );
  return res.data.data.answer;
}

export interface CEOChatPayload {
  question: string;
  ceo_result?: Record<string, unknown> | null;
  cto_result?: Record<string, unknown> | null;
  job_id?: string | null;
  conversation_history?: ChatMessage[];
}

export async function sendCEOChatMessage(
  payload: CEOChatPayload
): Promise<string> {
  const res = await apiClient.post<{ data: { answer: string }; error: null }>(
    "/chat/ceo",
    {
      stream: false,
      conversation_history: [],
      ...payload,
    }
  );
  return res.data.data.answer;
}

// ── CEO Async Job API ─────────────────────────────────────────────────────────

export interface CEOJobStatus {
  status: "pending" | "completed" | "failed" | "not_found";
  job_id: string;
  result?: Record<string, unknown> | null;
  error?: string | null;
}

export async function enqueueCEOAnalysis(
  body: Record<string, unknown>
): Promise<{ job_id: string; status: string; poll_url: string }> {
  const res = await apiClient.post<{
    data: { job_id: string; status: string; poll_url: string };
    error: null;
  }>("/ceo/analyze-async", body);
  return res.data.data;
}

export async function getCEOJobStatus(jobId: string): Promise<CEOJobStatus> {
  const res = await apiClient.get<{ data: CEOJobStatus; error: null }>(
    `/ceo/status/${jobId}`
  );
  return res.data.data;
}

export interface CEOExportPayload {
  board_deck: Record<string, unknown>;
  okr_status?: Record<string, unknown> | null;
  company_name?: string | null;
  period?: string | null;
}

/**
 * POST /ceo/export-pdf — returns a PDF Blob for download.
 */
export async function exportBoardDeckPDF(payload: CEOExportPayload): Promise<Blob> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const res = await fetch(`${base}/api/v1/ceo/export-pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`PDF export failed (${res.status}): ${text}`);
  }
  return res.blob();
}
