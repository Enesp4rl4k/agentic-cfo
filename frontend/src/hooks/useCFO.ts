"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import {
  getDashboard,
  getJobStatus,
  startAnalysis,
  approveJob,
  listReports,
  uploadFile,
  listJobs,
  listTransactions,
  correctCategory,
  listAnomalies,
  scanAnomalies,
  acknowledgeAnomaly,
  getCommandCenterData,
} from "@/lib/api/cfo";
import { useToast } from "@/components/ui/toast";

export function useDashboard(jobId: string | null) {
  return useQuery({
    queryKey: ["dashboard", jobId],
    queryFn: () => getDashboard(jobId!),
    enabled: !!jobId,
    staleTime: 30_000,
    retry: 2,
  });
}

export function useJobStatus(jobId: string | null, enabled = true) {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJobStatus(jobId!),
    enabled: !!jobId && enabled,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "pending" || status === "ingesting" || status === "analyzing") {
        return 2_000;
      }
      return false;
    },
  });
}

export function useStartAnalysis() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: startAnalysis,
    onSuccess: (_data, jobId) => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      // dashboard will pick up the new job via SSE stream
      queryClient.invalidateQueries({ queryKey: ["dashboard", jobId] });
    },
  });
}

export function useApproveJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: approveJob,
    onSuccess: (_data, jobId) => {
      // After approval, invalidate dashboard so it refetches when SSE signals done
      queryClient.invalidateQueries({ queryKey: ["dashboard", jobId] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useReports(jobId: string | null) {
  return useQuery({
    queryKey: ["reports", jobId],
    queryFn: () => listReports(jobId!),
    enabled: !!jobId,
  });
}

/**
 * Upload hook — uploads file and immediately starts analysis.
 * Returns the job_id so callers can redirect to /?job={job_id}.
 *
 * onJobReady: optional callback that fires with the job_id once analysis
 * has been enqueued. Use this for navigation instead of navigating in onSuccess
 * to keep the hook composable.
 */
export function useUpload(onJobReady?: (jobId: string) => void) {
  const queryClient = useQueryClient();
  const startMutation = useMutation({ mutationFn: startAnalysis });

  return useMutation({
    mutationFn: uploadFile,
    onSuccess: async (data) => {
      const jobId = data.job_id;
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      try {
        // Auto-start analysis immediately after upload
        await startMutation.mutateAsync(jobId);
        onJobReady?.(jobId);
      } catch {
        // startAnalysis may fail if job was already auto-started by validateAndUpload
        // In that case, still fire the callback so navigation happens
        onJobReady?.(jobId);
      }
    },
  });
}

/** Recent jobs list — used by sidebar history */
export function useJobs() {
  return useQuery({
    queryKey: ["jobs"],
    queryFn: listJobs,
    staleTime: 10_000,
    refetchOnWindowFocus: true,
  });
}

/** Paginated transactions for a job */
export function useTransactions(
  jobId: string | null,
  limit = 100,
  offset = 0
) {
  return useQuery({
    queryKey: ["transactions", jobId, limit, offset],
    queryFn: () => listTransactions(jobId!, limit, offset),
    enabled: !!jobId,
    staleTime: 60_000,
  });
}

/** Correct a transaction's category — invalidates transactions + dashboard */
export function useCorrectCategory(jobId: string | null) {
  const queryClient = useQueryClient();
  const { success, error: toastError } = useToast();
  return useMutation({
    mutationFn: ({
      transactionId,
      category,
      applyAlways,
    }: {
      transactionId: string;
      category: string;
      applyAlways?: boolean;
    }) => correctCategory(transactionId, category, applyAlways),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["transactions", jobId] });
      queryClient.invalidateQueries({ queryKey: ["dashboard", jobId] });
      success(
        "Category updated",
        vars.applyAlways ? `Saved as rule for future transactions` : undefined
      );
    },
    onError: (err: Error) => {
      toastError("Failed to update category", err.message);
    },
  });
}

/** List anomalies for a job */
export function useAnomalies(jobId: string | null, severity?: string) {
  return useQuery({
    queryKey: ["anomalies", jobId, severity],
    queryFn: () => listAnomalies(jobId!, severity),
    enabled: !!jobId,
    staleTime: 60_000,
  });
}

/** Trigger a fresh anomaly scan for a completed job */
export function useScanAnomalies(jobId: string | null) {
  const queryClient = useQueryClient();
  const { success, error: toastError } = useToast();
  return useMutation({
    mutationFn: () => scanAnomalies(jobId!),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["anomalies", jobId] });
      success(
        `Scan complete: ${data.anomalies_found} anomalies found`,
        data.critical > 0 ? `${data.critical} critical issues need attention` : undefined
      );
    },
    onError: (err: Error) => {
      toastError("Scan failed", err.message);
    },
  });
}

/** Acknowledge / dismiss an anomaly */
export function useAcknowledgeAnomaly(jobId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ack }: { id: string; ack: boolean }) =>
      acknowledgeAnomaly(id, ack),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["anomalies", jobId] });
    },
  });
}

/**
 * Command Center — fetches CEO pipeline result and maps it to agent health,
 * cross-domain risks and quick wins.
 *
 * Caches for 5 minutes; auto-refetches when the window regains focus.
 * Pass jobId to anchor analysis to a specific uploaded dataset.
 */
export function useCommandCenter(jobId?: string | null) {
  return useQuery({
    queryKey: ["command-center", jobId ?? "global"],
    queryFn: () => getCommandCenterData(jobId),
    staleTime: 5 * 60 * 1000,    // 5 min
    refetchOnWindowFocus: false,  // CEO pipeline is expensive — don't spam
    retry: 1,
  });
}

export interface TopAlert {
  level: "critical" | "error" | "warning" | "info";
  message: string;
  source: string;
  domain: string;
  score: number;
  action: string;
}

export interface TopAlertsData {
  top_alerts: TopAlert[];
  total_raw: number;
  has_critical: boolean;
}

async function fetchTopAlerts(jobId: string, limit = 3): Promise<TopAlertsData> {
  const res = await apiClient.get<{ data: TopAlertsData; error: null }>(
    `/alerts/top/${jobId}`,
    { params: { limit } }
  );
  return res.data.data;
}

/**
 * Top prioritized alerts for the ActionBar "What should I do now?" widget.
 * Only fetches when a job is completed — does not poll.
 */
export function useTopAlerts(jobId: string | null) {
  return useQuery<TopAlertsData>({
    queryKey: ["alerts-top", jobId],
    queryFn: () => fetchTopAlerts(jobId!),
    enabled: !!jobId,
    staleTime: 60_000,
    retry: 1,
  });
}
