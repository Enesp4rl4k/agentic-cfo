"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getDashboard,
  getJobStatus,
  startAnalysis,
  approveJob,
  listReports,
  uploadFile,
} from "@/lib/api/cfo";

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
      // Poll while running
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
  return useMutation({
    mutationFn: uploadFile,
  });
}
