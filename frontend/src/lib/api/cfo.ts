import { apiClient } from "@/lib/api/client";
import type {
  AnalysisJob,
  DashboardData,
  ReportMeta,
  TaxAnalysisData,
  AnomalyData,
  BudgetComparisonData,
  BalanceSheetData,
  FinancialRatiosData,
} from "@/types";

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
  // NEXT_PUBLIC_ vars are inlined at build time — safe to access without process types
  const base =
    (typeof window !== "undefined"
      ? (window as Window & { __API_URL__?: string }).__API_URL__
      : undefined) ??
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).NEXT_PUBLIC_API_URL ??
    "http://localhost:8000";
  return `${base}/api/v1/reports/${reportId}/download`;
}

export async function downloadReport(reportId: string): Promise<Blob> {
  const res = await apiClient.get(`/reports/${reportId}/download`, {
    responseType: "blob",
  });
  return res.data as Blob;
}

export async function getTaxAnalysis(jobId: string): Promise<TaxAnalysisData> {
  const res = await apiClient.get<{ data: TaxAnalysisData; error: null }>(
    `/tax/${jobId}`
  );
  return res.data.data;
}

export async function getAnomalies(jobId: string): Promise<AnomalyData> {
  const res = await apiClient.get<{ data: AnomalyData; error: null }>(
    `/anomalies/${jobId}`
  );
  return res.data.data;
}

export async function getBudgetComparison(
  jobId: string
): Promise<BudgetComparisonData> {
  const res = await apiClient.get<{ data: BudgetComparisonData; error: null }>(
    `/budget/${jobId}`
  );
  return res.data.data;
}

export async function rerunBudget(
  jobId: string,
  budget: Record<string, number>
): Promise<BudgetComparisonData> {
  const res = await apiClient.post<{ data: BudgetComparisonData; error: null }>(
    `/budget/${jobId}/rerun`,
    { budget }
  );
  return res.data.data;
}

export async function getBalanceSheet(jobId: string): Promise<BalanceSheetData> {
  const res = await apiClient.get<{ data: BalanceSheetData; error: null }>(
    `/balance-sheet/${jobId}`
  );
  return res.data.data;
}

export async function getFinancialRatios(jobId: string): Promise<FinancialRatiosData> {
  const res = await apiClient.get<{ data: FinancialRatiosData; error: null }>(
    `/ratios/${jobId}`
  );
  return res.data.data;
}

export async function getSupportedLanguages(): Promise<{ code: string; name: string }[]> {
  const res = await apiClient.get<{ data: { code: string; name: string }[]; error: null }>(
    `/languages`
  );
  return res.data.data;
}
