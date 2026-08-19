"use client";

import { useMutation } from "@tanstack/react-query";
import {
  analyzeRiskKernel,
  analyzeRiskCascade,
  getRiskKernelFromJob,
  getRiskKernelFromOrg,
  getRiskCascadeFromJob,
  getRiskCascadeFromOrg,
} from "@/lib/api/risk";
import type {
  RiskKernelRequest,
  RiskCascadeRequest,
} from "@/lib/api/risk";

// ── Risk Kernel hooks ─────────────────────────────────────────────────────────

export function useRiskKernel() {
  const mutation = useMutation({
    mutationFn: (req: RiskKernelRequest) => analyzeRiskKernel(req),
  });
  return {
    result:       mutation.data ?? null,
    loading:      mutation.isPending,
    error:        mutation.error ? String(mutation.error) : null,
    analyze:      mutation.mutate,
    analyzeAsync: mutation.mutateAsync,
    reset:        mutation.reset,
  };
}

export function useRiskKernelFromJob() {
  const mutation = useMutation({
    mutationFn: (jobId: string) => getRiskKernelFromJob(jobId),
  });
  return {
    result:  mutation.data ?? null,
    loading: mutation.isPending,
    error:   mutation.error ? String(mutation.error) : null,
    load:    mutation.mutate,
    loadAsync: mutation.mutateAsync,
    reset:   mutation.reset,
  };
}

export function useRiskKernelFromOrg() {
  const mutation = useMutation({
    mutationFn: (orgId: string) => getRiskKernelFromOrg(orgId),
  });
  return {
    result:  mutation.data ?? null,
    loading: mutation.isPending,
    error:   mutation.error ? String(mutation.error) : null,
    load:    mutation.mutate,
    loadAsync: mutation.mutateAsync,
    reset:   mutation.reset,
  };
}

// ── Risk Cascade hooks ────────────────────────────────────────────────────────

export function useRiskCascade() {
  const mutation = useMutation({
    mutationFn: (req: RiskCascadeRequest) => analyzeRiskCascade(req),
  });
  return {
    result:       mutation.data ?? null,
    loading:      mutation.isPending,
    error:        mutation.error ? String(mutation.error) : null,
    analyze:      mutation.mutate,
    analyzeAsync: mutation.mutateAsync,
    reset:        mutation.reset,
  };
}

export function useRiskCascadeFromJob() {
  const mutation = useMutation({
    mutationFn: ({ jobId, maxCascades }: { jobId: string; maxCascades?: number }) =>
      getRiskCascadeFromJob(jobId, maxCascades),
  });
  return {
    result:  mutation.data ?? null,
    loading: mutation.isPending,
    error:   mutation.error ? String(mutation.error) : null,
    load:    mutation.mutate,
    loadAsync: mutation.mutateAsync,
    reset:   mutation.reset,
  };
}

export function useRiskCascadeFromOrg() {
  const mutation = useMutation({
    mutationFn: ({ orgId, maxCascades }: { orgId: string; maxCascades?: number }) =>
      getRiskCascadeFromOrg(orgId, maxCascades),
  });
  return {
    result:  mutation.data ?? null,
    loading: mutation.isPending,
    error:   mutation.error ? String(mutation.error) : null,
    load:    mutation.mutate,
    loadAsync: mutation.mutateAsync,
    reset:   mutation.reset,
  };
}

// ── KRI display helpers (re-export for convenience) ───────────────────────────

export {
  statusColor,
  statusBg,
  postureBg,
  postureColor,
  trendIcon,
  categoryLabel,
} from "@/lib/api/risk";
