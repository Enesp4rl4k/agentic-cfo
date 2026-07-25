"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
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
} from "@/lib/api/cfo";
import { useToast } from "@/components/ui/toast";

export function useDashboard(jobId: string | null) {
  return useQuery({
    queryKey: ["dashboard", jobId],
    queryFn: () => getDashboard(jobId!),
    enabled: !!jobId,
    staleTime: 30_000,
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
      queryClient.invalidateQueries({ queryKey: ["job", jobId] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useApproveJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: approveJob,
    onSuccess: (_data, jobId) => {
      queryClient.invalidateQueries({ queryKey: ["job", jobId] });
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

export function useUpload() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: uploadFile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
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
