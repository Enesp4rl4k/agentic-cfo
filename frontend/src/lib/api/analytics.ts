import { apiClient } from "@/lib/api/client";

// ── TCMB Macro ────────────────────────────────────────────────────────────────

export interface MacroSnapshot {
  usd_try:           number;
  eur_try:           number;
  policy_rate_pct:   number;
  inflation_pct:     number;
  ppi_pct:           number;
  repo_rate_pct:     number;
  data_source:       string;
  as_of:             string;
  real_cost_of_capital: number;
}

export async function getMacroSnapshot(): Promise<MacroSnapshot> {
  const res = await apiClient.get<{ data: MacroSnapshot }>("/analytics/macro");
  return res.data.data;
}

export async function getExchangeRateHistory(
  currency: "USD" | "EUR" = "USD",
  days = 30
): Promise<{ date: string; rate: number }[]> {
  const res = await apiClient.get<{ data: { series: { date: string; rate: number }[] } }>(
    `/analytics/macro/exchange-rate?currency=${currency}&days=${days}`
  );
  return res.data.data.series;
}

// ── Monte Carlo ───────────────────────────────────────────────────────────────

export interface MonteCarloRequest {
  current_cash_try:      number;
  monthly_revenue_try:   number;
  monthly_burn_try:      number;
  revenue_std_pct?:      number;
  burn_std_pct?:         number;
  growth_rate_monthly?:  number;
  months?:               number;
  simulations?:          number;
}

export interface MonteCarloResult {
  simulations:         number;
  months:              number;
  survival_rate:       number;
  bankruptcy_pct:      number;
  avg_runway_months:   number;
  final_cash: {
    median: number;
    p10:    number;
    p90:    number;
  };
  sample_paths:     number[][];
  interpretation:   string;
}

export async function runMonteCarlo(req: MonteCarloRequest): Promise<MonteCarloResult> {
  const res = await apiClient.post<{ data: MonteCarloResult }>("/analytics/monte-carlo", req);
  return res.data.data;
}

// ── Working Capital ───────────────────────────────────────────────────────────

export interface WorkingCapitalRequest {
  accounts_receivable_try:  number;
  annual_revenue_try:       number;
  accounts_payable_try:     number;
  annual_cogs_try:          number;
  inventory_try?:           number;
  job_id?:                  string;
}

export interface WorkingCapitalMetrik {
  ad:       string;
  /** null when an input the formula needs is missing — never a filled-in guess. */
  gun:      number | null;
  formul:   string;
  aciklama: string;
}

export interface WorkingCapitalResult {
  metrikler: { dso: WorkingCapitalMetrik; dpo: WorkingCapitalMetrik; dio: WorkingCapitalMetrik; ccc: WorkingCapitalMetrik };
  yorum: string;
  eksik_girdiler: string[];
  olcum: "hesaplandi";
  /** No DSO/DPO sector data exists in this project, so none is shown. */
  sektor_karsilastirmasi: null;
  sektor_karsilastirmasi_notu: string;
}

export async function analyzeWorkingCapital(
  req: WorkingCapitalRequest
): Promise<WorkingCapitalResult> {
  const res = await apiClient.post<{ data: WorkingCapitalResult }>(
    "/analytics/working-capital", req
  );
  return res.data.data;
}

// ── Break-Even ────────────────────────────────────────────────────────────────

export interface BreakEvenRequest {
  fixed_costs_monthly_try:    number;
  variable_cost_per_unit_try: number;
  price_per_unit_try:         number;
  current_units_monthly?:     number;
}

export interface BreakEvenResult {
  break_even_units:         number;
  break_even_revenue_try:   number;
  unit_contribution_try:    number;
  contribution_margin_pct:  number;
  margin_of_safety_pct:     number;
  current_profit_monthly:   number | null;
  scenarios: {
    units:    number;
    revenue:  number;
    profit:   number;
    label:    string;
  }[];
}

export async function analyzeBreakEven(req: BreakEvenRequest): Promise<BreakEvenResult> {
  const res = await apiClient.post<{ data: BreakEvenResult }>("/analytics/break-even", req);
  return res.data.data;
}

// ── Cohort ────────────────────────────────────────────────────────────────────

export interface CohortRequest {
  cohorts:     Array<Record<string, number | string>>;
  avg_cac_try: number;
}

export interface CohortResult {
  cohorts: Array<{
    cohort_month:  string;
    customers:     number;
    ltv_curve:     number[];
    retention:     number[];
    ltv_12m:       number;
    payback_months: number | null;
    avg_monthly_revenue_per_customer: number;
  }>;
  summary: {
    avg_ltv_12m:   number;
    ltv_cac_ratio: number | null;
    avg_cac_try:   number;
    verdict:       string;
  };
}

export async function analyzeCohorts(req: CohortRequest): Promise<CohortResult> {
  const res = await apiClient.post<{ data: CohortResult }>("/analytics/cohort", req);
  return res.data.data;
}
