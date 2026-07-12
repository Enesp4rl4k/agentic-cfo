import { apiClient } from "@/lib/api/client";
import type { AnalysisJob, DashboardData, ReportMeta } from "@/types";

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
  const base =
    process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return `${base}/api/v1/reports/${reportId}/download`;
}
