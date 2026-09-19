import { apiClient } from "@/lib/api/client";

export interface SystemHealth {
  status: "healthy" | "degraded";
  ok: boolean;
  checked_at: string;
  components: {
    database: { ok: boolean; detail: string };
    redis: { ok: boolean; detail?: string };
    agents: {
      ok: boolean;
      modules: Record<string, boolean>;
    };
  };
}

export interface SystemOps {
  schema_version: string;
  jobs: {
    status_counts: Record<string, number>;
    total: number;
    failure_rate_pct: number;
    awaiting_review_ratio_pct: number;
    awaiting_review: number;
    recent_failed: Array<{
      job_id: string;
      status: string;
      error_message: string | null;
      updated_at: string | null;
    }>;
  };
  sync: {
    available: boolean;
    by_status: Record<string, number>;
  };
  sla: {
    queue_depth: number;
    queue_depths?: {
      analysis: number;
      maintenance: number;
    };
    job_completion_p95_ms: number | null;
    time_to_first_result_p95_ms: number | null;
    error_rate_pct: number;
    breaches: Array<{
      job_id: string;
      status: string;
      age_minutes: number;
      threshold_minutes: number;
    }>;
  };
  error_budget: Record<string, { weekly_failure_rate_target_pct: number }>;
  management?: {
    conflicts_available: boolean;
    open_conflicts: number;
    topics: Array<{ topic: string; count: number }>;
    recent_conflicts?: Array<{
      id: string;
      topic: string;
      status: string;
      consensus_score: number | null;
      severity: string;
      resolution: string | null;
      created_at: string | null;
    }>;
    suggested_topics?: string[];
  };
  suggested_actions: string[];
  generated_at: string;
}

export async function getSystemHealth(): Promise<SystemHealth> {
  const res = await apiClient.get<{ data: SystemHealth; error: null }>("/system/health");
  return res.data.data;
}

export async function getSystemOps(orgId?: string | null): Promise<SystemOps> {
  const res = await apiClient.get<{ data: SystemOps; error: null }>("/system/ops", {
    params: orgId ? { org_id: orgId } : undefined,
  });
  return res.data.data;
}

