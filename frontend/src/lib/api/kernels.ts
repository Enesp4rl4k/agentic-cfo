import { apiClient } from "@/lib/api/client";

// ── Shared types ───────────────────────────────────────────────────────────────

export interface KernelFromJobRequest {
  job_id: string;
  company_size?: "startup" | "smb" | "enterprise";
  industry?: string;
}

export interface KernelFromOrgRequest {
  org_id: string;
  company_size?: "startup" | "smb" | "enterprise";
  industry?: string;
}

// ── CTO Kernel ────────────────────────────────────────────────────────────────

export interface CTOKernelOutput {
  overall_health_score:    number;
  tech_debt_score:         number;
  infra_waste_pct:         number;
  velocity_trend:          "improving" | "stable" | "deteriorating";
  monthly_infra_cost_try:  number;
  infra_waste_try:         number;
  estimated_engineers:     number;
  sprint_velocity_score:   number;
  security_score:          number;
  open_vulnerabilities:    number;
  monthly_tech_budget_try: number;
  annual_tech_budget_try:  number;
  data_source:             string;
  confidence:              number;
  narrative:               string;
}

export interface CTOKernelResult {
  ok: boolean;
  output: CTOKernelOutput;
  patch: Record<string, unknown>;
}

export async function getCTOKernelFromJob(req: KernelFromJobRequest): Promise<CTOKernelResult> {
  const res = await apiClient.post<CTOKernelResult>("/cto-kernel/from-job", req);
  return res.data;
}

export async function getCTOKernelFromOrg(req: KernelFromOrgRequest): Promise<CTOKernelResult> {
  const res = await apiClient.post<CTOKernelResult>("/cto-kernel/from-org", req);
  return res.data;
}

// ── CMO Kernel ────────────────────────────────────────────────────────────────

export interface CMOKernelOutput {
  overall_roas:                   number;
  avg_cac_cents:                  number;
  avg_monthly_churn:              number;
  ltv_cac_ratio:                  number;
  monthly_marketing_budget_try:   number;
  estimated_monthly_leads:        number;
  estimated_new_customers:        number;
  estimated_sales_reps:           number;
  revenue_per_rep_try:            number;
  mrr_try:                        number;
  arr_try:                        number;
  growth_rate:                    number;
  data_source:                    string;
  confidence:                     number;
  narrative:                      string;
}

export interface CMOKernelResult {
  ok: boolean;
  output: CMOKernelOutput;
  patch: Record<string, unknown>;
}

export async function getCMOKernelFromJob(req: KernelFromJobRequest): Promise<CMOKernelResult> {
  const res = await apiClient.post<CMOKernelResult>("/cmo-kernel/from-job", req);
  return res.data;
}

export async function getCMOKernelFromOrg(req: KernelFromOrgRequest): Promise<CMOKernelResult> {
  const res = await apiClient.post<CMOKernelResult>("/cmo-kernel/from-org", req);
  return res.data;
}

// ── CHRO Kernel ────────────────────────────────────────────────────────────────

export interface CHROKernelOutput {
  total_headcount:                   number;
  estimated_engineers:               number;
  annual_turnover_rate:              number;
  at_risk_employees:                 number;
  turnover_cost_annual_try:          number;
  avg_monthly_salary_try:            number;
  total_monthly_payroll_try:         number;
  total_monthly_personnel_cost_try:  number;
  engagement_score:                  number;
  open_critical_roles:               number;
  time_to_hire_days:                 number;
  monthly_training_budget_try:       number;
  skills_gap_risk:                   "low" | "medium" | "high";
  data_source:                       string;
  confidence:                        number;
  narrative:                         string;
}

export interface CHROKernelResult {
  ok: boolean;
  output: CHROKernelOutput;
  patch: Record<string, unknown>;
}

export async function getCHROKernelFromJob(req: KernelFromJobRequest): Promise<CHROKernelResult> {
  const res = await apiClient.post<CHROKernelResult>("/chro-kernel/from-job", req);
  return res.data;
}

export async function getCHROKernelFromOrg(req: KernelFromOrgRequest): Promise<CHROKernelResult> {
  const res = await apiClient.post<CHROKernelResult>("/chro-kernel/from-org", req);
  return res.data;
}

// ── COO Kernel ─────────────────────────────────────────────────────────────────

export interface COOKernelOutput {
  sla_compliance:          number;
  uptime_pct:              number;
  overall_ops_score:       number;
  process_efficiency_pct:  number;
  resource_utilization:    number;
  ops_headcount:           number;
  bottleneck_risk:         "low" | "medium" | "high";
  scaling_readiness:       "ready" | "limited" | "not_ready";
  top_bottlenecks:         string[];
  data_source:             string;
  confidence:              number;
  narrative:               string;
}

export interface COOKernelResult {
  ok: boolean;
  output: COOKernelOutput;
  patch: Record<string, unknown>;
}

export async function getCOOKernelFromJob(req: KernelFromJobRequest): Promise<COOKernelResult> {
  const res = await apiClient.post<COOKernelResult>("/coo-kernel/from-job", req);
  return res.data;
}

export async function getCOOKernelFromOrg(req: KernelFromOrgRequest): Promise<COOKernelResult> {
  const res = await apiClient.post<COOKernelResult>("/coo-kernel/from-org", req);
  return res.data;
}

// ── Cross-Domain Hub ──────────────────────────────────────────────────────────

export interface CrossDomainInsight {
  id:            string;
  title:         string;
  domains:       string[];
  severity:      "critical" | "high" | "medium" | "low";
  insight_type:  "risk" | "opportunity" | "correlation" | "warning";
  description:   string;
  evidence:      string[];
  actions:       string[];
  financial_impact_try: number | null;
}

export interface CrossDomainReport {
  cto_output:        Record<string, unknown> | null;
  cmo_output:        Record<string, unknown> | null;
  chro_output:       Record<string, unknown> | null;
  coo_output:        Record<string, unknown> | null;
  audit_output:      Record<string, unknown> | null;
  compliance_output: Record<string, unknown> | null;
  risk_output:       Record<string, unknown> | null;
  insights:          CrossDomainInsight[];
  critical_count:    number;
  high_count:        number;
  overall_health_score: number;
  health_label:      "excellent" | "good" | "fair" | "at_risk" | "critical";
  executive_summary: string;
  top_priorities:    string[];
  quick_wins:        string[];
}

export interface CrossDomainFromOrgRequest extends KernelFromOrgRequest {
  sector?:           string;
  has_eu_customers?: boolean;
  is_fintech?:       boolean;
}

export async function getCrossDomainFromJob(
  req: KernelFromJobRequest & { sector?: string; has_eu_customers?: boolean; is_fintech?: boolean }
): Promise<CrossDomainReport> {
  const res = await apiClient.post<CrossDomainReport>("/cross-domain/from-job", req);
  return res.data;
}

export async function getCrossDomainFromOrg(
  req: CrossDomainFromOrgRequest
): Promise<CrossDomainReport> {
  const res = await apiClient.post<CrossDomainReport>("/cross-domain/from-org", req);
  return res.data;
}

export async function getCrossDomainHealth(orgId: string): Promise<{
  health_score:      number | null;
  health_label:      string;
  critical_count:    number;
  high_count:        number;
  executive_summary: string;
}> {
  const res = await apiClient.get(`/cross-domain/health/${orgId}`);
  return res.data as Awaited<ReturnType<typeof getCrossDomainHealth>>;
}

// ── Benchmark API ─────────────────────────────────────────────────────────────

export interface BenchmarkItem {
  metric:          string;
  company_value:   number | null;
  benchmark_p25:   number;
  benchmark_p50:   number;
  benchmark_p75:   number;
  unit:            string;
  higher_is_better: boolean;
  percentile:      number | null;
  verdict:         string;
  gap_to_median:   number | null;
  context:         string;
}

export interface BenchmarkReport {
  sector:       string;
  company_size: string;
  items:        BenchmarkItem[];
  summary:      string;
  strengths:    string[];
  weaknesses:   string[];
  generated_at: string;
}

export interface BenchmarkCompareRequest {
  sector?:       string;
  company_size?: string;
  cfo_data?:     Record<string, unknown>;
  cmo_data?:     Record<string, unknown>;
  chro_data?:    Record<string, unknown>;
  coo_data?:     Record<string, unknown>;
}

export async function getBenchmarkCompare(req: BenchmarkCompareRequest): Promise<BenchmarkReport> {
  const res = await apiClient.post<BenchmarkReport>("/benchmark/compare", req);
  return res.data;
}

export async function getBenchmarkFromOrg(orgId: string, sector = "saas"): Promise<BenchmarkReport> {
  const res = await apiClient.post<BenchmarkReport>("/benchmark/from-org", { org_id: orgId, sector });
  return res.data;
}

export async function getBenchmarkSectors(): Promise<{ sectors: string[] }> {
  const res = await apiClient.get<{ sectors: string[] }>("/benchmark/sectors");
  return res.data;
}

// ── Display helpers ────────────────────────────────────────────────────────────

export function healthColor(label: string): string {
  switch (label) {
    case "excellent": return "text-emerald-400";
    case "good":      return "text-blue-400";
    case "fair":      return "text-yellow-400";
    case "at_risk":   return "text-orange-400";
    case "critical":  return "text-red-400";
    default:          return "text-muted-foreground";
  }
}

export function healthBg(label: string): string {
  switch (label) {
    case "excellent": return "bg-emerald-500/10 border-emerald-500/30";
    case "good":      return "bg-blue-500/10 border-blue-500/30";
    case "fair":      return "bg-yellow-500/10 border-yellow-500/30";
    case "at_risk":   return "bg-orange-500/10 border-orange-500/30";
    case "critical":  return "bg-red-500/10 border-red-500/30";
    default:          return "bg-muted/50 border-border";
  }
}

export function insightSeverityColor(severity: string): string {
  switch (severity) {
    case "critical": return "text-red-400 bg-red-500/10";
    case "high":     return "text-orange-400 bg-orange-500/10";
    case "medium":   return "text-yellow-400 bg-yellow-500/10";
    default:         return "text-blue-400 bg-blue-500/10";
  }
}

export function velocityColor(trend: string): string {
  switch (trend) {
    case "improving":     return "text-emerald-400";
    case "deteriorating": return "text-red-400";
    default:              return "text-yellow-400";
  }
}
