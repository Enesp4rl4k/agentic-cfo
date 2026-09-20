"use client";

import { useCallback, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";

// ── Types ──────────────────────────────────────────────────────────────────────

export type AgentType = "cto" | "cmo" | "coo" | "chro" | "risk" | "audit" | "compliance";

export type AgentJobStatus = "pending" | "running" | "completed" | "failed";

export interface AgentJobResult {
  id: string;
  agent_type: AgentType;
  status: AgentJobStatus;
  progress: number;
  result: Record<string, unknown> | null;
  logs: Array<{ step?: string; node?: string; status?: string; ok?: boolean; detail?: string; message?: string }> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface EnqueueResponse {
  job_id: string;
  agent_type: AgentType;
  status: AgentJobStatus;
  message: string;
}

// Flexible input type — each agent uses its own subset of fields
export interface AgentJobRequest {
  company_name?: string;
  reporting_period?: string;
  // CTO
  cloud_billing_csv?: string;
  git_log_text?: string;
  incident_csv?: string;
  sprint_csv?: string;
  // CMO
  campaign_csv?: string;
  funnel_csv?: string;
  cohort_csv?: string;
  // COO
  process_csv?: string;
  resource_csv?: string;
  sla_csv?: string;
  // CHRO
  headcount_csv?: string;
  attrition_csv?: string;
  compensation_csv?: string;
  // Risk
  register_csv?: string;
  loss_csv?: string;
  kri_csv?: string;
  // Audit
  findings_csv?: string;
  controls_csv?: string;
  audit_plan_csv?: string;
  // Compliance
  policies_csv?: string;
  violations_csv?: string;
  regulations_csv?: string;
}

// ── API helpers ────────────────────────────────────────────────────────────────

async function enqueueJob(
  agentType: AgentType,
  body: AgentJobRequest
): Promise<EnqueueResponse> {
  const res = await apiClient.post(`/agent-jobs/${agentType}`, body);
  return res.data.data;
}

async function fetchJobStatus(jobId: string): Promise<AgentJobResult> {
  const res = await apiClient.get(`/agent-jobs/${jobId}`);
  return res.data.data;
}

async function fetchJobList(agentType: AgentType, limit = 5): Promise<AgentJobResult[]> {
  const res = await apiClient.get(`/agent-jobs/list/${agentType}`, {
    params: { limit },
  });
  return res.data.data.jobs;
}

async function deleteJob(jobId: string): Promise<void> {
  await apiClient.delete(`/agent-jobs/${jobId}`);
}

// ── Hooks ──────────────────────────────────────────────────────────────────────

/**
 * Core polling hook — polls every 2s while job is running/pending,
 * stops automatically on completion or failure.
 */
export function useAgentJobStatus(jobId: string | null) {
  return useQuery<AgentJobResult>({
    queryKey: ["agent-job", jobId],
    queryFn: () => fetchJobStatus(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "completed" || status === "failed") return false;
      return 2000;
    },
    staleTime: 0,
  });
}

/**
 * List recent jobs for an agent type.
 */
export function useAgentJobList(agentType: AgentType, limit = 5) {
  return useQuery<AgentJobResult[]>({
    queryKey: ["agent-jobs-list", agentType],
    queryFn: () => fetchJobList(agentType, limit),
    staleTime: 30_000,
  });
}

/**
 * Main hook — manages enqueue + local job ID state + result extraction.
 *
 * Usage:
 *   const { enqueue, jobId, status, result, isPending, isRunning, isDone } = useAgentJob("cto");
 */
export function useAgentJob(agentType: AgentType) {
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);

  const { data: jobData, isLoading } = useAgentJobStatus(jobId);

  const enqueueMutation = useMutation({
    mutationFn: (body: AgentJobRequest) => enqueueJob(agentType, body),
    onSuccess: (data) => {
      setJobId(data.job_id);
      qc.invalidateQueries({ queryKey: ["agent-jobs-list", agentType] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteJob,
    onSuccess: () => {
      setJobId(null);
      qc.invalidateQueries({ queryKey: ["agent-jobs-list", agentType] });
    },
  });

  const enqueue = useCallback(
    (body: AgentJobRequest) => enqueueMutation.mutate(body),
    [enqueueMutation]
  );

  const reset = useCallback(() => {
    setJobId(null);
  }, []);

  const status = jobData?.status ?? null;
  const progress = jobData?.progress ?? 0;
  const result = jobData?.result ?? null;
  const logs = jobData?.logs ?? [];
  const error = jobData?.error ?? enqueueMutation.error?.message ?? null;

  return {
    // Actions
    enqueue,
    reset,
    deleteJob: (id: string) => deleteMutation.mutate(id),

    // State
    jobId,
    status,
    progress,
    result,
    logs,
    error,

    // Convenience booleans
    isEnqueueing: enqueueMutation.isPending,
    isPending:    status === "pending",
    isRunning:    status === "running",
    isDone:       status === "completed",
    isFailed:     status === "failed",
    isActive:     status === "pending" || status === "running",
    isLoading:    isLoading && !!jobId,
  };
}
