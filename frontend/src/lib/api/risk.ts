import { apiClient } from "@/lib/api/client";

// ── Types ──────────────────────────────────────────────────────────────────────

export type KRIStatus = "green" | "amber" | "red";
export type KRITrend  = "improving" | "stable" | "deteriorating";
export type RiskPosture = "acceptable" | "moderate" | "elevated" | "critical";

export interface KRI {
  name:              string;
  category:          string;
  current_value:     number;
  unit:              string;
  threshold_amber:   number;
  threshold_red:     number;
  higher_is_worse:   boolean;
  status:            KRIStatus;
  trend:             KRITrend;
  trend_delta:       number;
  trajectory_months: number | null;
  evidence:          string;
  cascade_trigger:   string | null;
  cascade_params:    Record<string, unknown>;
}

export interface RiskPostureData {
  kri_score:    number;
  posture:      RiskPosture;
  posture_tr:   string;
  counts: {
    red:   number;
    amber: number;
    green: number;
    total: number;
  };
  red_kris:      KRI[];
  amber_kris:    KRI[];
  upcoming_red:  KRI[];
  cascade_ready: KRI[];
  all_kris:      KRI[];
  by_category:   Record<string, KRI[]>;
  narrative:     string;
}

export interface RiskKernelResult {
  ok:        boolean;
  posture:   RiskPostureData;
  kri_count: number;
}

export interface KRICascadeLink {
  kri_name:       string;
  kri_category:   string;
  kri_status:     KRIStatus;
  kri_value:      number;
  kri_unit:       string;
  trigger_type:   string;
  trigger_params: Record<string, unknown>;
  cascade_result: Record<string, unknown> | null;
  cascade_error:  string | null;
}

export interface RiskCascadeReport {
  kri_posture:     RiskPostureData;
  cascade_links:   KRICascadeLink[];
  total_cascades:  number;
  critical_count:  number;
  cascade_summary: string;
  domains_at_risk: string[];
  top_cascade:     {
    kri_name:       string;
    trigger_type:   string;
    cascade_result: Record<string, unknown> | null;
  } | null;
}

// ── Risk Kernel ───────────────────────────────────────────────────────────────

export interface RiskKernelRequest {
  pnl?:       Record<string, unknown>;
  cashflow?:  Record<string, unknown>;
  forecast?:  Record<string, unknown>;
  chro_data?: Record<string, unknown>;
  cto_data?:  Record<string, unknown>;
  cmo_data?:  Record<string, unknown>;
  coo_data?:  Record<string, unknown>;
}

export async function analyzeRiskKernel(
  req: RiskKernelRequest
): Promise<RiskKernelResult> {
  const res = await apiClient.post<RiskKernelResult>("/risk-kernel/analyze", req);
  return res.data;
}

export async function getRiskKernelFromJob(
  jobId: string
): Promise<RiskKernelResult> {
  const res = await apiClient.post<RiskKernelResult>("/risk-kernel/from-job", {
    job_id: jobId,
  });
  return res.data;
}

export async function getRiskKernelFromOrg(
  orgId: string
): Promise<RiskKernelResult> {
  const res = await apiClient.post<RiskKernelResult>("/risk-kernel/from-org", {
    org_id: orgId,
  });
  return res.data;
}

// ── Risk Cascade ──────────────────────────────────────────────────────────────

export interface RiskCascadeRequest extends RiskKernelRequest {
  max_cascades?: number;
  only_red?:     boolean;
}

export async function analyzeRiskCascade(
  req: RiskCascadeRequest
): Promise<RiskCascadeReport> {
  const res = await apiClient.post<RiskCascadeReport>(
    "/risk-cascade/analyze",
    req
  );
  return res.data;
}

export async function getRiskCascadeFromJob(
  jobId: string,
  maxCascades = 5
): Promise<RiskCascadeReport> {
  const res = await apiClient.post<RiskCascadeReport>(
    "/risk-cascade/from-job",
    { job_id: jobId, max_cascades: maxCascades }
  );
  return res.data;
}

export async function getRiskCascadeFromOrg(
  orgId: string,
  maxCascades = 5
): Promise<RiskCascadeReport> {
  const res = await apiClient.post<RiskCascadeReport>(
    "/risk-cascade/from-org",
    { org_id: orgId, max_cascades: maxCascades }
  );
  return res.data;
}

// ── Display helpers ───────────────────────────────────────────────────────────

export function statusColor(status: KRIStatus): string {
  switch (status) {
    case "red":   return "text-red-400";
    case "amber": return "text-yellow-400";
    default:      return "text-emerald-400";
  }
}

export function statusBg(status: KRIStatus): string {
  switch (status) {
    case "red":   return "bg-red-500/10 border-red-500/30";
    case "amber": return "bg-yellow-500/10 border-yellow-500/30";
    default:      return "bg-emerald-500/10 border-emerald-500/30";
  }
}

export function postureBg(posture: RiskPosture): string {
  switch (posture) {
    case "critical":   return "bg-red-500/15 border-red-500/40";
    case "elevated":   return "bg-orange-500/15 border-orange-500/40";
    case "moderate":   return "bg-yellow-500/15 border-yellow-500/40";
    default:           return "bg-emerald-500/15 border-emerald-500/40";
  }
}

export function postureColor(posture: RiskPosture): string {
  switch (posture) {
    case "critical":   return "text-red-400";
    case "elevated":   return "text-orange-400";
    case "moderate":   return "text-yellow-400";
    default:           return "text-emerald-400";
  }
}

export function trendIcon(trend: KRITrend): string {
  switch (trend) {
    case "deteriorating": return "↘";
    case "improving":     return "↗";
    default:              return "→";
  }
}

export function categoryLabel(cat: string): string {
  const map: Record<string, string> = {
    financial:   "Finansal",
    people:      "İnsan Kaynakları",
    technology:  "Teknoloji",
    market:      "Pazar",
    operational: "Operasyon",
    compliance:  "Uyumluluk",
  };
  return map[cat] ?? cat;
}
