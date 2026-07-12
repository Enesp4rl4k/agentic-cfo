// Global TypeScript types for AI CFO frontend

export interface KPI {
  label: string;
  value: number;
  format: "currency" | "percent" | "months" | "number";
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
}

export type AlertLevel = "warning" | "critical" | "info";

export interface Alert {
  level: AlertLevel;
  message: string;
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

export interface DashboardData {
  generated_at: string;
  kpis: KPI[];
  pnl: PnLData;
  cashflow: CashFlowData;
  forecast: ForecastData;
  alerts: Alert[];
  recent_transactions: Transaction[];
  transaction_count: number;
}

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
