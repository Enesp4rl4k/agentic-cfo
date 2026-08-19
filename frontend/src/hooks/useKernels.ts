"use client";

import { useMutation } from "@tanstack/react-query";
import {
  getCTOKernelFromJob,
  getCTOKernelFromOrg,
  getCMOKernelFromJob,
  getCMOKernelFromOrg,
  getCHROKernelFromJob,
  getCHROKernelFromOrg,
  getCOOKernelFromJob,
  getCOOKernelFromOrg,
  getCrossDomainFromJob,
  getCrossDomainFromOrg,
  getBenchmarkCompare,
  getBenchmarkFromOrg,
} from "@/lib/api/kernels";
import type {
  KernelFromJobRequest,
  KernelFromOrgRequest,
  CrossDomainFromOrgRequest,
  BenchmarkCompareRequest,
} from "@/lib/api/kernels";

// ── CTO ───────────────────────────────────────────────────────────────────────

export function useCTOKernelFromJob() {
  const m = useMutation({ mutationFn: (req: KernelFromJobRequest) => getCTOKernelFromJob(req) });
  return { result: m.data ?? null, loading: m.isPending, error: m.error ? String(m.error) : null, load: m.mutate, reset: m.reset };
}

export function useCTOKernelFromOrg() {
  const m = useMutation({ mutationFn: (req: KernelFromOrgRequest) => getCTOKernelFromOrg(req) });
  return { result: m.data ?? null, loading: m.isPending, error: m.error ? String(m.error) : null, load: m.mutate, reset: m.reset };
}

// ── CMO ───────────────────────────────────────────────────────────────────────

export function useCMOKernelFromJob() {
  const m = useMutation({ mutationFn: (req: KernelFromJobRequest) => getCMOKernelFromJob(req) });
  return { result: m.data ?? null, loading: m.isPending, error: m.error ? String(m.error) : null, load: m.mutate, reset: m.reset };
}

export function useCMOKernelFromOrg() {
  const m = useMutation({ mutationFn: (req: KernelFromOrgRequest) => getCMOKernelFromOrg(req) });
  return { result: m.data ?? null, loading: m.isPending, error: m.error ? String(m.error) : null, load: m.mutate, reset: m.reset };
}

// ── CHRO ──────────────────────────────────────────────────────────────────────

export function useCHROKernelFromJob() {
  const m = useMutation({ mutationFn: (req: KernelFromJobRequest) => getCHROKernelFromJob(req) });
  return { result: m.data ?? null, loading: m.isPending, error: m.error ? String(m.error) : null, load: m.mutate, reset: m.reset };
}

export function useCHROKernelFromOrg() {
  const m = useMutation({ mutationFn: (req: KernelFromOrgRequest) => getCHROKernelFromOrg(req) });
  return { result: m.data ?? null, loading: m.isPending, error: m.error ? String(m.error) : null, load: m.mutate, reset: m.reset };
}

// ── COO ───────────────────────────────────────────────────────────────────────

export function useCOOKernelFromJob() {
  const m = useMutation({ mutationFn: (req: KernelFromJobRequest) => getCOOKernelFromJob(req) });
  return { result: m.data ?? null, loading: m.isPending, error: m.error ? String(m.error) : null, load: m.mutate, reset: m.reset };
}

export function useCOOKernelFromOrg() {
  const m = useMutation({ mutationFn: (req: KernelFromOrgRequest) => getCOOKernelFromOrg(req) });
  return { result: m.data ?? null, loading: m.isPending, error: m.error ? String(m.error) : null, load: m.mutate, reset: m.reset };
}

// ── Cross-Domain Hub ──────────────────────────────────────────────────────────

export function useCrossDomainFromJob() {
  const m = useMutation({
    mutationFn: (req: KernelFromJobRequest & { sector?: string; has_eu_customers?: boolean; is_fintech?: boolean }) =>
      getCrossDomainFromJob(req),
  });
  return { result: m.data ?? null, loading: m.isPending, error: m.error ? String(m.error) : null, load: m.mutate, reset: m.reset };
}

export function useCrossDomainFromOrg() {
  const m = useMutation({ mutationFn: (req: CrossDomainFromOrgRequest) => getCrossDomainFromOrg(req) });
  return { result: m.data ?? null, loading: m.isPending, error: m.error ? String(m.error) : null, load: m.mutate, reset: m.reset };
}

// ── Unified kernel loader (job_id veya org_id'ye gore otomatik secim) ─────────

interface UnifiedKernelLoadParams {
  jobId?: string | null;
  orgId?: string | null;
  companySize?: "startup" | "smb" | "enterprise";
}

export function useUnifiedCrossDoamin() {
  const fromJob = useCrossDomainFromJob();
  const fromOrg = useCrossDomainFromOrg();

  const load = (params: UnifiedKernelLoadParams) => {
    if (params.orgId) {
      fromOrg.load({ org_id: params.orgId, company_size: params.companySize ?? "smb" });
    } else if (params.jobId) {
      fromJob.load({ job_id: params.jobId, company_size: params.companySize ?? "smb" });
    }
  };

  const active = fromOrg.result ? fromOrg : fromJob;
  return {
    result:  active.result,
    loading: fromJob.loading || fromOrg.loading,
    error:   fromJob.error || fromOrg.error,
    load,
    reset:   () => { fromJob.reset(); fromOrg.reset(); },
  };
}

// ── Benchmark ─────────────────────────────────────────────────────────────────

export function useBenchmarkCompare() {
  const m = useMutation({ mutationFn: (req: BenchmarkCompareRequest) => getBenchmarkCompare(req) });
  return { result: m.data ?? null, loading: m.isPending, error: m.error ? String(m.error) : null, load: m.mutate, reset: m.reset };
}

export function useBenchmarkFromOrg() {
  const m = useMutation({
    mutationFn: ({ orgId, sector }: { orgId: string; sector?: string }) =>
      getBenchmarkFromOrg(orgId, sector),
  });
  return { result: m.data ?? null, loading: m.isPending, error: m.error ? String(m.error) : null, load: m.mutate, reset: m.reset };
}

// ── Re-exports ────────────────────────────────────────────────────────────────

export {
  healthColor,
  healthBg,
  insightSeverityColor,
  velocityColor,
} from "@/lib/api/kernels";
