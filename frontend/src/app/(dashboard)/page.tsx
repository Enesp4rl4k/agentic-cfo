"use client";

import { useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  Activity,
  Clock,
  TrendingDown,
  TrendingUp,
  Upload,
  ChevronRight,
} from "lucide-react";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import {
  useDashboard,
  useJobStatus,
  useApproveJob,
} from "@/hooks/useCFO";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import type { Alert, Transaction, DashboardData } from "@/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function sign(n: number) {
  return n >= 0 ? "+" : "";
}

// ── Alert Strip (inline, not modal) ──────────────────────────────────────────

function AlertStrip({ alerts }: { alerts: Alert[] }) {
  if (!alerts.length) return null;
  const critical = alerts.filter((a) => a.level === "critical");
  const warnings = alerts.filter((a) => a.level === "warning");

  return (
    <div className="space-y-1.5">
      {critical.map((a, i) => (
        <div
          key={i}
          role="alert"
          className="flex items-start gap-2.5 rounded-md border border-destructive/30 bg-destructive/8 px-3.5 py-2.5 text-sm text-destructive transition-state"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="leading-snug">{a.message}</span>
        </div>
      ))}
      {warnings.map((a, i) => (
        <div
          key={i}
          role="alert"
          className="flex items-start gap-2.5 rounded-md border border-warning/25 bg-warning/6 px-3.5 py-2.5 text-sm text-warning transition-state"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="leading-snug">{a.message}</span>
        </div>
      ))}
    </div>
  );
}

// ── Financial Summary Row (replaces hero-metric card grid) ───────────────────
// Impeccable rule: no identical card grid, no hero-metric template.
// Instead: a single horizontal data row with clear typographic hierarchy.

function FinancialSummaryRow({ data }: { data: DashboardData }) {
  const { pnl, cashflow } = data;
  const netPositive = pnl.net_income >= 0;
  const cashPositive = cashflow.net_change >= 0;

  const metrics = [
    {
      label: "Revenue",
      value: formatCurrency(pnl.revenue),
      sub: null,
      accent: false,
    },
    {
      label: "Gross Profit",
      value: formatCurrency(pnl.gross_profit),
      sub: formatPercent(pnl.gross_margin) + " margin",
      accent: false,
    },
    {
      label: "Net Income",
      value: formatCurrency(pnl.net_income),
      sub: formatPercent(pnl.net_margin) + " margin",
      accent: true,
      positive: netPositive,
    },
    {
      label: "Net Cash Flow",
      value: formatCurrency(cashflow.net_change),
      sub: `Op: ${formatCurrency(cashflow.operating)}`,
      accent: true,
      positive: cashPositive,
    },
    {
      label: "EBITDA",
      value: formatCurrency(pnl.ebitda),
      sub: formatPercent(pnl.ebitda_margin) + " margin",
      accent: false,
    },
  ] as const;

  return (
    <div
      className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-3 lg:grid-cols-5"
      aria-label="Financial summary"
    >
      {metrics.map((m) => (
        <div key={m.label} className="bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">{m.label}</p>
          <p
            className={cn(
              "mt-1 text-lg font-semibold tabular tracking-tight",
              "accent" in m && m.accent
                ? "positive" in m && m.positive
                  ? "text-success"
                  : "text-destructive"
                : "text-foreground"
            )}
          >
            {m.value}
          </p>
          {m.sub && (
            <p className="mt-0.5 text-xs text-muted-foreground tabular">{m.sub}</p>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Inline chart tooltip styles ───────────────────────────────────────────────

const tooltipStyle = {
  contentStyle: {
    background: "oklch(0.17 0.022 255)",
    border: "1px solid oklch(0.27 0.018 255)",
    borderRadius: "6px",
    fontSize: "12px",
    color: "oklch(0.92 0.008 255)",
    padding: "8px 12px",
  },
  cursor: { stroke: "oklch(0.32 0.018 255)", strokeWidth: 1 },
};

const axisStyle = {
  tick: { fontSize: 11, fill: "oklch(0.52 0.012 255)" },
  axisLine: { stroke: "oklch(0.27 0.018 255)" },
  tickLine: false as const,
};

// ── Cash Flow Chart ───────────────────────────────────────────────────────────

function CashFlowChart({ series }: { series: DashboardData["cashflow"]["monthly_series"] }) {
  const data = series.map((m) => ({
    month: m.month.slice(5), // "MM" only
    in: m.in / 100,
    out: m.out / 100,
    net: m.net / 100,
  }));

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-0.5 text-sm font-medium">Monthly Cash Flow</h3>
      <p className="mb-4 text-xs text-muted-foreground">Cash in vs. out per month</p>
      {data.length > 0 ? (
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={data} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
            <defs>
              <linearGradient id="gIn" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="oklch(0.60 0.19 255)" stopOpacity={0.25} />
                <stop offset="100%" stopColor="oklch(0.60 0.19 255)" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="gOut" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="oklch(0.58 0.22 25)" stopOpacity={0.2} />
                <stop offset="100%" stopColor="oklch(0.58 0.22 25)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="oklch(0.22 0.018 255)"
              vertical={false}
            />
            <XAxis dataKey="month" {...axisStyle} />
            <YAxis
              {...axisStyle}
              tickFormatter={(v: number) => `$${Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`}
            />
            <Tooltip
              {...tooltipStyle}
              formatter={(v: number, name: string) => [formatCurrency(v), name]}
            />
            <ReferenceLine y={0} stroke="oklch(0.35 0.018 255)" strokeWidth={1} />
            <Area
              type="monotone"
              dataKey="in"
              name="Cash In"
              stroke="oklch(0.60 0.19 255)"
              strokeWidth={1.5}
              fill="url(#gIn)"
              dot={false}
            />
            <Area
              type="monotone"
              dataKey="out"
              name="Cash Out"
              stroke="oklch(0.58 0.22 25)"
              strokeWidth={1.5}
              fill="url(#gOut)"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      ) : (
        <EmptyChartState label="No monthly data available" />
      )}
    </div>
  );
}

// ── OpEx Bar Chart ────────────────────────────────────────────────────────────

function OpExChart({ opex }: { opex: DashboardData["pnl"]["opex"] }) {
  const data = Object.entries(opex)
    .filter(([, v]) => v != null && v > 0)
    .map(([k, v]) => ({ name: k.replace(/_/g, " "), value: (v ?? 0) / 100 }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 7);

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-0.5 text-sm font-medium">Operating Expenses</h3>
      <p className="mb-4 text-xs text-muted-foreground">By category</p>
      {data.length > 0 ? (
        <ResponsiveContainer width="100%" height={200}>
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 0, right: 4, left: 0, bottom: 0 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="oklch(0.22 0.018 255)"
              horizontal={false}
            />
            <XAxis
              type="number"
              {...axisStyle}
              tickFormatter={(v: number) =>
                `$${v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`
              }
            />
            <YAxis
              dataKey="name"
              type="category"
              {...axisStyle}
              width={80}
              tick={{ ...axisStyle.tick, textAnchor: "end" }}
            />
            <Tooltip
              {...tooltipStyle}
              formatter={(v: number) => [formatCurrency(v), "Amount"]}
            />
            <Bar
              dataKey="value"
              fill="oklch(0.60 0.19 255)"
              radius={[0, 3, 3, 0]}
              maxBarSize={18}
            />
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <EmptyChartState label="No expense data" />
      )}
    </div>
  );
}

// ── Forecast Scenarios ────────────────────────────────────────────────────────
// Not cards — a comparison table. Avoids identical-card-grid ban.

function ForecastTable({ forecast }: { forecast: DashboardData["forecast"] }) {
  const scenarios = Object.values(forecast.scenarios);
  if (!scenarios.length) return null;

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-medium">12-Month Forecast</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Three scenarios based on historical trends
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" role="table">
          <thead>
            <tr className="border-b border-border">
              <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">
                Scenario
              </th>
              <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">
                12-Month Net
              </th>
              <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">
                Cash Runway
              </th>
              <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground hidden sm:table-cell">
                Assumption
              </th>
            </tr>
          </thead>
          <tbody>
            {scenarios.map((s) => {
              const isBase = s.label === "Base";
              const net = s.twelve_month_net;
              const netPositive = net >= 0;
              return (
                <tr
                  key={s.label}
                  className={cn(
                    "border-b border-border/50 last:border-0 transition-state",
                    isBase ? "bg-primary/5" : "hover:bg-muted/30"
                  )}
                >
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1.5 text-xs font-medium",
                        isBase ? "text-primary" : "text-muted-foreground"
                      )}
                    >
                      {isBase && (
                        <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />
                      )}
                      {s.label}
                    </span>
                  </td>
                  <td
                    className={cn(
                      "px-4 py-3 text-right tabular font-medium text-sm",
                      netPositive ? "text-success" : "text-destructive"
                    )}
                  >
                    {sign(net)}{formatCurrency(net)}
                  </td>
                  <td className="px-4 py-3 text-right tabular text-sm text-muted-foreground">
                    {s.runway_months != null ? `${s.runway_months} mo` : "Stable"}
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground hidden sm:table-cell max-w-[240px]">
                    {s.description}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {forecast.narrative && (
        <div className="border-t border-border/50 px-4 py-3">
          <p className="text-xs leading-relaxed text-muted-foreground max-w-prose">
            {forecast.narrative}
          </p>
        </div>
      )}
    </div>
  );
}

// ── Transactions Table ────────────────────────────────────────────────────────

function TransactionsTable({ transactions }: { transactions: Transaction[] }) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="text-sm font-medium">Recent Transactions</h3>
        <span className="text-xs text-muted-foreground">
          {transactions.length} shown
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" role="table">
          <thead>
            <tr className="border-b border-border">
              {["Date", "Description", "Category", "Amount"].map((h) => (
                <th
                  key={h}
                  className={cn(
                    "px-4 py-2.5 text-xs font-medium text-muted-foreground",
                    h === "Amount" ? "text-right" : "text-left"
                  )}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {transactions.map((tx, i) => (
              <tr
                key={i}
                className="border-b border-border/40 last:border-0 transition-state hover:bg-muted/20"
              >
                <td className="px-4 py-2.5 text-xs tabular text-muted-foreground whitespace-nowrap">
                  {tx.transaction_date?.slice(0, 10) ?? "—"}
                </td>
                <td className="px-4 py-2.5 max-w-[180px] truncate text-sm">
                  {tx.description || "—"}
                </td>
                <td className="px-4 py-2.5">
                  <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                    {tx.category}
                  </span>
                </td>
                <td
                  className={cn(
                    "px-4 py-2.5 text-right tabular text-sm font-medium",
                    tx.type === "income" ? "text-success" : "text-foreground"
                  )}
                >
                  {tx.type === "income" ? "+" : "−"}
                  {formatCurrency(tx.amount_cents / 100)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!transactions.length && (
          <div className="py-10 text-center text-sm text-muted-foreground">
            No transactions to display.
          </div>
        )}
      </div>
    </div>
  );
}

// ── Empty chart placeholder ───────────────────────────────────────────────────

function EmptyChartState({ label }: { label: string }) {
  return (
    <div className="flex h-[200px] items-center justify-center text-xs text-muted-foreground">
      {label}
    </div>
  );
}

// ── Skeleton — per product register: skeleton not spinner ────────────────────

function DashboardSkeleton() {
  return (
    <div className="space-y-4 p-5" aria-busy="true" aria-label="Loading dashboard">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-3 lg:grid-cols-5">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="bg-card px-4 py-4">
            <div className="h-3 w-16 animate-pulse rounded bg-muted" />
            <div className="mt-2 h-5 w-24 animate-pulse rounded bg-muted" />
            <div className="mt-1.5 h-2.5 w-14 animate-pulse rounded bg-muted" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {[...Array(2)].map((_, i) => (
          <div key={i} className="h-56 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    </div>
  );
}

// ── Empty state — teaches the interface ──────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center px-6">
      <div className="mb-4 rounded-full bg-muted p-4">
        <Upload className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold">No financial data yet</h2>
      <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
        Upload a bank statement, invoice export, or CSV to run your first AI CFO analysis.
      </p>
      <a
        href="/upload"
        className={cn(
          "mt-5 flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground",
          "transition-state hover:opacity-90",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        )}
      >
        Upload document
        <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
      </a>
    </div>
  );
}

// ── Main Dashboard Page ───────────────────────────────────────────────────────

export default function DashboardPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");

  const { data: dashboard, isLoading } = useDashboard(jobId);
  const { data: job } = useJobStatus(jobId);
  const approveJob = useApproveJob();

  const isRunning =
    job?.status === "pending" ||
    job?.status === "ingesting" ||
    job?.status === "analyzing";

  // Loading / running
  if (isLoading || isRunning) {
    return isRunning ? (
      <div className="p-5 space-y-3">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Activity className="h-4 w-4 animate-pulse text-primary" aria-hidden="true" />
          Agent running: <span className="font-medium text-foreground">{job?.status}</span>
        </div>
        <DashboardSkeleton />
      </div>
    ) : (
      <DashboardSkeleton />
    );
  }

  // Awaiting human review
  if (job?.awaiting_review) {
    return (
      <div className="flex flex-col items-center justify-center py-20 px-6 text-center">
        <div className="mb-4 rounded-full bg-warning/10 p-4">
          <Clock className="h-8 w-8 text-warning" aria-hidden="true" />
        </div>
        <h2 className="text-base font-semibold">Review Required</h2>
        <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
          Agent confidence:{" "}
          <strong className="text-foreground">
            {((job.min_confidence ?? 0) * 100).toFixed(0)}%
          </strong>{" "}
          — below the 80% threshold for auto-proceed.
        </p>
        <div className="mt-5 w-full max-w-sm space-y-1.5 text-left">
          {(job.logs ?? [])
            .filter((l) => l.detail)
            .map((log, i) => (
              <div
                key={i}
                className={cn(
                  "flex items-start gap-2 rounded-md border px-3 py-2 text-xs",
                  log.ok
                    ? "border-border bg-card text-muted-foreground"
                    : "border-destructive/30 bg-destructive/8 text-destructive"
                )}
              >
                <span className="font-medium shrink-0">{log.step}</span>
                <span>{log.detail}</span>
              </div>
            ))}
        </div>
        <button
          onClick={() => jobId && approveJob.mutate(jobId)}
          disabled={approveJob.isPending}
          className={cn(
            "mt-5 rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground",
            "transition-state hover:opacity-90 disabled:opacity-50",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          )}
        >
          {approveJob.isPending ? "Approving…" : "Approve & Continue"}
        </button>
      </div>
    );
  }

  // No job or no data
  if (!jobId || !dashboard) {
    return <EmptyState />;
  }

  const allAlerts = [
    ...(dashboard.cashflow.alerts ?? []),
    ...(dashboard.forecast?.alerts ?? []),
  ];

  return (
    <div className="space-y-4 p-5">
      {/* Alerts — inline strip, not modal */}
      {allAlerts.length > 0 && <AlertStrip alerts={allAlerts} />}

      {/* Financial summary row — not hero-metric cards */}
      <FinancialSummaryRow data={dashboard} />

      {/* CFO narrative — prose, not a decorated panel */}
      {dashboard.pnl.narrative && (
        <div className="rounded-lg border border-border bg-card px-4 py-3.5">
          <p className="mb-1 text-xs font-medium text-primary">CFO Commentary</p>
          <p className="text-sm leading-relaxed text-muted-foreground max-w-prose">
            {dashboard.pnl.narrative}
          </p>
        </div>
      )}

      {/* Charts — side by side */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <CashFlowChart series={dashboard.cashflow.monthly_series} />
        <OpExChart opex={dashboard.pnl.opex} />
      </div>

      {/* Forecast — comparison table, not card grid */}
      {dashboard.forecast?.scenarios && (
        <ForecastTable forecast={dashboard.forecast} />
      )}

      {/* Transactions */}
      <TransactionsTable transactions={dashboard.recent_transactions} />

      {/* Footer metadata */}
      <p className="text-center text-xs text-muted-foreground">
        Analyzed{" "}
        <span className="tabular">{dashboard.transaction_count}</span>{" "}
        transactions ·{" "}
        {new Date(dashboard.generated_at).toLocaleString()}
      </p>
    </div>
  );
}
