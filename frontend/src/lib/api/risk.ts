import { apiClient } from "@/lib/api/client";

// ── Types ──────────────────────────────────────────────────────────────────────

export type KRIStatus = "green" | "amber" | "red";
export type KRITrend  = "improving" | "stable" | "deteriorating";
// "no_data" when nothing was measured — never shown as a calm posture.
export type RiskPosture = "stable" | "elevated" | "critical" | "no_data";

export interface KRI {
  name:              string;
  category:          string;
  current_value:     number | null;
  unit:              string;
  threshold_amber:   number | null;
  threshold_red:     number | null;
  higher_is_worse:   boolean;
  status:            KRIStatus;
  /** One period gives no trend; null means "not measured", not "stable". */
  trend:             KRITrend | null;
  trajectory_months: number | null;
  /** Where the value came from: the CFO report or the uploaded KRI file. */
  source:            string;
  evidence:          string;
  cascade_trigger:   string | null;
  cascade_params:    Record<string, unknown>;
}

export interface RiskPostureData {
  /** Null when there are no measured KRIs. */
  kri_score:    number | null;
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
  sources:       string[];
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

// ── Risk Cascade ──────────────────────────────────────────────────────────────

export interface RiskCascadeRequest {
  pnl?:         Record<string, unknown>;
  cashflow?:    Record<string, unknown>;
  forecast?:    Record<string, unknown>;
  /** The risk orchestrator's result, whose uploaded KRIs are included. */
  risk_result?: Record<string, unknown>;
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
    case "no_data":    return "bg-muted/30 border-border";
    default:           return "bg-emerald-500/15 border-emerald-500/40";
  }
}

export function postureColor(posture: RiskPosture): string {
  switch (posture) {
    case "critical":   return "text-red-400";
    case "elevated":   return "text-orange-400";
    case "no_data":    return "text-muted-foreground";
    default:           return "text-emerald-400";
  }
}

export function trendIcon(trend: KRITrend | null): string {
  switch (trend) {
    case null:            return "";
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
