import { apiClient } from "@/lib/api/client";

interface Envelope<T> {
  data: T;
  error: string | null;
}

export interface CHROMonthTrend {
  month: string;
  payroll_cents: number;
  revenue_cents: number;
  ratio_pct: number | null;
}

export interface CHROMetrics {
  org_id: string;
  revenue_cents: number;
  payroll_cents: number;
  payroll_ratio_pct: number | null;
  monthly_trend: CHROMonthTrend[];
  trend_direction: "increasing" | "stable" | "decreasing";
  summary: string;
}

export interface COOSupplier {
  supplier: string;
  amount_cents: number;
  share_pct: number;
}

export interface COOMetrics {
  org_id: string;
  total_expense_cents: number;
  top_suppliers: COOSupplier[];
  top1_share_pct: number;
  top3_share_pct: number;
  top5_share_pct: number;
  concentration_risk: "LOW" | "MEDIUM" | "HIGH";
  summary: string;
}

export interface CTOMonthTrend {
  month: string;
  tech_cents: number;
}

export interface CTORecurringVendor {
  vendor: string;
  monthly_cents: number;
  frequency_months: number;
}

export interface CTOMetrics {
  org_id: string;
  total_tech_spend_cents: number;
  tech_share_pct: number;
  monthly_trend: CTOMonthTrend[];
  recurring_tech_vendors: CTORecurringVendor[];
  summary: string;
}

export async function getCHROMetrics(
  months: number = 6,
  anchorDate?: string,
): Promise<CHROMetrics> {
  const params: Record<string, string | number> = { months };
  if (anchorDate) params.anchor_date = anchorDate;
  const res = await apiClient.get<Envelope<CHROMetrics>>("/csuite/chro", { params });
  return res.data.data;
}

export async function getCOOMetrics(
  days: number = 90,
  anchorDate?: string,
): Promise<COOMetrics> {
  const params: Record<string, string | number> = { days };
  if (anchorDate) params.anchor_date = anchorDate;
  const res = await apiClient.get<Envelope<COOMetrics>>("/csuite/coo", { params });
  return res.data.data;
}

export async function getCTOMetrics(
  months: number = 6,
  anchorDate?: string,
): Promise<CTOMetrics> {
  const params: Record<string, string | number> = { months };
  if (anchorDate) params.anchor_date = anchorDate;
  const res = await apiClient.get<Envelope<CTOMetrics>>("/csuite/cto", { params });
  return res.data.data;
}
