import { apiClient } from "@/lib/api/client";

// ── Types ──────────────────────────────────────────────────────────────────────

export type TriggerType =
  | "cash_crisis"
  | "revenue_drop"
  | "key_person_loss"
  | "market_shock";

export type RoleType = "cto" | "cfo" | "ceo" | "cmo" | "chro";
export type ActionRoleType = "engineer" | "sales" | "ops" | "general";
export type ImpactLevel = "none" | "low" | "medium" | "high" | "critical";

export interface DomainImpact {
  domain: string;
  impact_level: ImpactLevel;
  impact_score: number;
  triggered_by: string;
  delay_months: number;
  description: string;
  quantified_impact: Record<string, number | string>;
  mitigations: string[];
  secondary_triggers: string[];
}

export interface CascadeScenario {
  name: string;
  multiplier: number;
  overall_risk_score: number;
  total_financial_impact_try: number;
  recovery_months: number;
  cascade_chain: string[];
  domain_impacts: DomainImpact[];
}

export interface CascadeResult {
  trigger_type: string;
  trigger_description: string;
  trigger_params: Record<string, unknown>;
  scenarios: CascadeScenario[];
  affected_domains: string[];
  critical_path: string[];
  immediate_actions: string[];
  executive_summary: string;
  simulation_confidence: number;
}

export interface DomainEffect {
  domain: string;
  label: string;
  impact_score: number;
  financial_impact_try: number;
  key_metrics: Record<string, number | string>;
  risks: string[];
  opportunities: string[];
  timeline_months: number;
}

export interface MultidomainScenario {
  name: string;
  multiplier: number;
  net_financial_impact_try: number;
  overall_score: number;
  recommendation: string;
  domain_effects: DomainEffect[];
}

export interface MultidomainCFResult {
  action_type: string;
  action_description: string;
  action_params: Record<string, unknown>;
  scenarios: MultidomainScenario[];
  executive_summary: string;
  confidence: number;
}

// ── Cascade Simulator ─────────────────────────────────────────────────────────

export interface CascadeSimulateRequest {
  trigger: TriggerType;
  job_id?: string;
  org_id?: string;
  cash_crisis?: { runway_months: number };
  revenue_drop?: { drop_pct: number };
  key_person_loss?: { role: RoleType };
  market_shock?: { usd_try_increase_pct: number; inflation_pct: number };
}

export async function simulateCascade(
  req: CascadeSimulateRequest
): Promise<CascadeResult> {
  const res = await apiClient.post<CascadeResult>("/cascade/simulate", req);
  return res.data;
}

export interface CascadeTrigger {
  type: string;
  label: string;
  description: string;
  params: Array<{
    name: string;
    type: string;
    label: string;
    default?: number | string;
    options?: string[];
  }>;
}

export async function getCascadeTriggers(): Promise<{
  triggers: CascadeTrigger[];
}> {
  const res = await apiClient.get<{ triggers: CascadeTrigger[] }>(
    "/cascade/triggers"
  );
  return res.data;
}

// ── Multi-Domain Counterfactual ───────────────────────────────────────────────

export interface HeadcountMDRequest {
  delta: number;
  avg_monthly_salary_try?: number;
  productivity_gain_pct?: number;
  onboarding_months?: number;
  horizon_months?: number;
  role_type?: ActionRoleType;
  job_id?: string;
  org_id?: string;
}

export interface MarketingMDRequest {
  monthly_increase_try: number;
  expected_roas?: number;
  horizon_months?: number;
  job_id?: string;
  org_id?: string;
}

export interface TechInvestMDRequest {
  one_time_invest_try: number;
  monthly_ops_increase_try?: number;
  velocity_gain_pct?: number;
  horizon_months?: number;
  job_id?: string;
  org_id?: string;
}

export async function analyzeHeadcount(
  req: HeadcountMDRequest
): Promise<MultidomainCFResult> {
  const res = await apiClient.post<MultidomainCFResult>(
    "/multidomain-cf/headcount",
    req
  );
  return res.data;
}

export async function analyzeMarketing(
  req: MarketingMDRequest
): Promise<MultidomainCFResult> {
  const res = await apiClient.post<MultidomainCFResult>(
    "/multidomain-cf/marketing",
    req
  );
  return res.data;
}

export async function analyzeTech(
  req: TechInvestMDRequest
): Promise<MultidomainCFResult> {
  const res = await apiClient.post<MultidomainCFResult>(
    "/multidomain-cf/tech",
    req
  );
  return res.data;
}

export async function getMultidomainActions(): Promise<{
  actions: Array<{
    type: string;
    label: string;
    endpoint: string;
    description: string;
    domains: string[];
    params: Array<{
      name: string;
      type: string;
      label: string;
      default?: number | string;
      options?: string[];
      optional?: boolean;
    }>;
  }>;
}> {
  const res = await apiClient.get("/multidomain-cf/actions");
  return res.data as Awaited<ReturnType<typeof getMultidomainActions>>;
}
