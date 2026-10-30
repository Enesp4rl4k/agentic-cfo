/**
 * Company Context API — /api/v1/context/*
 *
 * Provides org-level unified state: which agents have run,
 * their last results, active job IDs, etc.
 */
import { apiClient } from "@/lib/api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface AgentStatus {
  has_result: boolean;
  updated_at: string;
}

export interface CompanyContext {
  org_id: string;
  company_name: string | null;
  reporting_period: string | null;
  updated_at: string;

  // Active job IDs
  active_cfo_job_id: string | null;
  active_cto_job_id: string | null;
  active_cmo_job_id: string | null;
  active_coo_job_id: string | null;
  active_chro_job_id: string | null;

  // Last agent results (raw dict — typed per-agent by consumers)
  last_cfo_result: Record<string, unknown> | null;
  last_cto_result: Record<string, unknown> | null;
  last_cmo_result: Record<string, unknown> | null;
  last_coo_result: Record<string, unknown> | null;
  last_chro_result: Record<string, unknown> | null;
  last_risk_result: Record<string, unknown> | null;
  last_audit_result: Record<string, unknown> | null;
  last_compliance_result: Record<string, unknown> | null;
  last_ceo_result: Record<string, unknown> | null;
}

export interface ContextSummary {
  org_id: string;
  company_name: string | null;
  reporting_period: string | null;
  updated_at: string;
  agents: Record<string, AgentStatus>;
  active_jobs: Record<string, string | null>;
}

export type AgentName =
  | "cfo" | "cto" | "cmo" | "coo" | "chro"
  | "risk" | "audit" | "compliance" | "ceo";


// ── API calls ─────────────────────────────────────────────────────────────────

/**
 * Fetch the full company context for the current user's org.
 */
export async function getCompanyContext(): Promise<CompanyContext> {
  const res = await apiClient.get<{ data: CompanyContext; error: null }>(
    "/context/me"
  );
  return res.data.data;
}

/**
 * Lightweight summary — agent statuses only, no full result payloads.
 */
export async function getContextSummary(): Promise<ContextSummary> {
  const res = await apiClient.get<{ data: ContextSummary; error: null }>(
    "/context/me/summary"
  );
  return res.data.data;
}

/**
 * Reset the company context (start fresh for a new period).
 */
export async function resetCompanyContext(): Promise<void> {
  await apiClient.delete("/context/me");
}
