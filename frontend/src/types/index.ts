// Global TypeScript types for AI CFO frontend

export interface KPI {
  label: string;
  value: number;
  format: "currency" | "percent" | "months" | "number" | "score";
  trend: number | null;
}

export interface MonthlyEntry {
  month: string;
  in: number;
  out: number;
  net: number;
  projected?: boolean;
}

export interface OpEx {
  salary?: number;
  rent?: number;
  utilities?: number;
  marketing?: number;
  technology?: number;
  other_expense?: number;
  [key: string]: number | undefined;
}

export interface PnLData {
  revenue: number;
  cogs: number;
  gross_profit: number;
  gross_margin: number;
  ebitda: number;
  ebitda_margin: number;
  net_income: number;
  net_margin: number;
  opex: OpEx;
  narrative: string;
}

export interface CashFlowData {
  operating: number;
  investing: number;
  financing: number;
  net_change: number;
  monthly_series: MonthlyEntry[];
  narrative: string;
  alerts: Alert[];
}

export interface ForecastScenario {
  label: string;
  description: string;
  runway_months: number | null;
  twelve_month_net: number;
  months: MonthlyEntry[];
}

export interface ForecastData {
  scenarios: {
    optimistic: ForecastScenario;
    base: ForecastScenario;
    pessimistic: ForecastScenario;
  };
  narrative: string;
  alerts: Alert[];
}

export type AlertLevel = "warning" | "critical" | "info";

export interface Alert {
  level: AlertLevel;
  message: string;
  category?: string;
}

export interface Transaction {
  amount_cents: number;
  currency: string;
  type: "income" | "expense";
  category: string;
  description: string;
  vendor: string | null;
  transaction_date: string | null;
  confidence: number | null;
}

// ── Tax Analysis ──────────────────────────────────────────────────────────────

export interface MonthlyKDV {
  month: string;
  collected: number;
  paid: number;
  net: number;
}

export interface TaxAnalysisData {
  kdv_collected: number;
  kdv_paid: number;
  kdv_net: number;
  kdv_payable: number;
  kdv_refundable: number;
  monthly_kdv: MonthlyKDV[];
  stopaj_total: number;
  stopaj_salary: number;
  stopaj_rent: number;
  kurumlar_vergisi_annual: number;
  gecici_vergi_quarterly: number;
  total_tax_burden: number;
  effective_tax_rate: number;
  narrative: string;
  alerts: Alert[];
}

// ── Anomaly Detection ─────────────────────────────────────────────────────────

export type AnomalySeverity = "high" | "medium" | "low";
export type AnomalyType =
  | "outlier_amount"
  | "potential_duplicate"
  | "round_number"
  | "frequency_spike";

export interface AnomalyEntry {
  type: AnomalyType;
  severity: AnomalySeverity;
  detail: string;
  transaction_date: string | null;
  amount_cents: number;
  vendor: string | null;
  category: string;
  description: string;
  z_score?: number;
  count_in_window?: number;
}

export interface AnomalyData {
  anomaly_list: AnomalyEntry[];
  anomaly_count: number;
  high_severity_count: number;
  risk_score: number; // 0–1
  narrative: string;
}

// ── Budget vs Actual ──────────────────────────────────────────────────────────

export type BudgetStatus =
  | "on_track"
  | "over_budget"
  | "under_budget"
  | "under_spend"
  | "ahead_of_target";

export interface BudgetCategoryData {
  budget: number;
  actual: number;
  variance: number;
  variance_pct: number;
  status: BudgetStatus;
}

export interface BudgetComparisonData {
  categories: Record<string, BudgetCategoryData>;
  total_variance: number;
  variance_pct: number;
  over_budget_count: number;
  auto_budget: boolean;
  narrative: string;
  alerts: Alert[];
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export interface DashboardData {
  generated_at: string;
  kpis: KPI[];
  pnl: PnLData;
  cashflow: CashFlowData;
  forecast: ForecastData;
  tax_analysis: TaxAnalysisData | null;
  anomalies: AnomalyData | null;
  budget_comparison: BudgetComparisonData | null;
  balance_sheet: BalanceSheetData | null;
  financial_ratios: FinancialRatiosData | null;
  alerts: Alert[];
  recent_transactions: Transaction[];
  transaction_count: number;
}

// ── Balance Sheet ─────────────────────────────────────────────────────────────

export interface BalanceSheetCurrentAssets {
  cash: number;
  accounts_receivable: number;
  inventory: number;
  prepaid_other: number;
  total: number;
}

export interface BalanceSheetData {
  assets: {
    current: BalanceSheetCurrentAssets;
    non_current: { ppe: number; intangibles: number; total: number };
    total: number;
  };
  liabilities: {
    current: { accounts_payable: number; short_term_debt: number; accrued_expenses: number; total: number };
    non_current: { long_term_debt: number; total: number };
    total: number;
  };
  equity: { retained_earnings: number; paid_in_capital: number; total: number };
  is_balanced: boolean;
  assumptions: { dso_days: number; dio_days: number; dpo_days: number; note: string };
  narrative: string;
}

// ── Financial Ratios ──────────────────────────────────────────────────────────

export interface RatioValue {
  value: number | null;
  benchmark: number | null;
  unit: string;
  status: "good" | "warning" | "critical" | "n/a";
}

export interface FinancialRatiosData {
  liquidity: Record<string, RatioValue>;
  profitability: Record<string, RatioValue>;
  leverage: Record<string, RatioValue>;
  efficiency: Record<string, RatioValue>;
  cash_flow: Record<string, RatioValue>;
  scorecard: { good: number; warning: number; critical: number; na: number };
  narrative: string;
  narrative_lang?: string;
}

// ── Extended Cash Flow ────────────────────────────────────────────────────────

export interface BurnRateData {
  monthly_burn_rate: number;
  avg_monthly_inflow: number;
  avg_monthly_outflow: number;
  runway_months: number | null;
  current_cash_balance: number;
}

export interface WorkingCapitalData {
  current_assets_est: number;
  current_liabilities_est: number;
  working_capital: number;
  working_capital_ratio: number;
  dso_days: number;
  dio_days: number;
  dpo_days: number;
  cash_conversion_cycle: number;
}

// ── Job / Analysis ────────────────────────────────────────────────────────────

export type JobStatus =
  | "pending"
  | "ingesting"
  | "analyzing"
  | "awaiting_review"
  | "completed"
  | "failed";

export interface StepLog {
  step: string;
  ok: boolean;
  detail: string | null;
  confidence: number | null;
}

export interface AnalysisJob {
  job_id: string;
  status: JobStatus;
  filename: string;
  awaiting_review: boolean;
  min_confidence: number | null;
  logs: StepLog[];
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ReportMeta {
  id: string;
  job_id: string;
  report_type: string;
  report_format: string;
  has_file: boolean;
  created_at: string;
}

export interface ApiResponse<T> {
  data: T;
  error: string | null;
}
