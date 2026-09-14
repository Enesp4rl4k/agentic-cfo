"use client";

import { useMutation } from "@tanstack/react-query";
import {
  analyzeRiskCascade,
  getRiskCascadeFromJob,
  getRiskCascadeFromOrg,
} from "@/lib/api/risk";
import type { RiskCascadeRequest } from "@/lib/api/risk";

// ── Risk Cascade hooks ────────────────────────────────────────────────────────
// The risk-kernel hooks are gone with the kernel: KRIs now come only from the
// CFO report and the organisation's uploaded KRI file (backend gercek_kri.py).

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

export {
  statusColor,
  statusBg,
  postureBg,
  postureColor,
  trendIcon,
  categoryLabel,
} from "@/lib/api/risk";
