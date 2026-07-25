"use client";

import { useSearchParams } from "next/navigation";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { AlertTriangle, Upload } from "lucide-react";
import { useDashboard } from "@/hooks/useCFO";
import { formatCurrency, cn } from "@/lib/utils";
import type { Alert, MonthlyEntry } from "@/types";

// ── Chart styles (matches dashboard.tsx) ─────────────────────────────────────

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

// ── Summary metric strip ──────────────────────────────────────────────────────

interface MetricItem {
  label: string;
  value: string;
  positive?: boolean;
  neutral?: boolean;
}

function MetricStrip({ metrics }: { metrics: MetricItem[] }) {
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
      {metrics.map((m) => (
        <div key={m.label} className="bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">{m.label}</p>
          <p
            className={cn(
              "mt-1 text-lg font-semibold tabular-nums tracking-tight",
              m.neutral
                ? "text-foreground"
                : m.positive
                ? "text-emerald-400"
                : "text-destructive"
            )}
          >
            {m.value}
          </p>
        </div>
      ))}
    </div>
  );
}

// ── Alert strip ───────────────────────────────────────────────────────────────

function AlertStrip({ alerts }: { alerts: Alert[] }) {
  if (!alerts.length) return null;
  return (
    <div className="space-y-1.5">
      {alerts.map((a, i) => (
        <div
          key={i}
          role="alert"
          className={cn(
            "flex items-start gap-2.5 rounded-md border px-3.5 py-2.5 text-sm",
            a.level === "critical"
              ? "border-destructive/30 bg-destructive/8 text-destructive"
              : "border-yellow-600/25 bg-yellow-950/20 text-yellow-400"
          )}
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="leading-snug">{a.message}</span>
        </div>
      ))}
    </div>
  );
}

// ── Monthly cash flow chart ───────────────────────────────────────────────────

function MonthlyCashFlowChart({ series }: { series: MonthlyEntry[] }) {
  const data = series.map((m) => ({
    month: m.month.slice(5),
    in: m.in / 100,
    out: m.out / 100,
    net: m.net / 100,
  }));

  if (!data.length) {
    return (
      <div className="flex h-[260px] items-center justify-center text-xs text-muted-foreground">
        No monthly data available
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={260}>
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
        <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.22 0.018 255)" vertical={false} />
        <XAxis dataKey="month" {...axisStyle} />
        <YAxis
          {...axisStyle}
          tickFormatter={(v: number) =>
            `$${Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`
          }
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
  );
}

// ── Net cash flow bar chart ───────────────────────────────────────────────────

function NetCashFlowBar({ series }: { series: MonthlyEntry[] }) {
  const data = series.map((m) => ({
    month: m.month.slice(5),
    net: m.net / 100,
  }));

  if (!data.length) return null;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-0.5 text-sm font-medium">Monthly Net Cash Flow</h2>
      <p className="mb-4 text-xs text-muted-foreground">Positive = surplus · Negative = deficit</p>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.22 0.018 255)" vertical={false} />
          <XAxis dataKey="month" {...axisStyle} />
          <YAxis
            {...axisStyle}
            tickFormatter={(v: number) =>
              `$${Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`
            }
          />
          <Tooltip
            {...tooltipStyle}
            formatter={(v: number) => [formatCurrency(v), "Net"]}
          />
          <ReferenceLine y={0} stroke="oklch(0.42 0.018 255)" strokeWidth={1} />
          <Bar dataKey="net" radius={[3, 3, 0, 0]} maxBarSize={28}>
            {data.map((entry, i) => (
              <Cell
                key={i}
                fill={
                  entry.net >= 0
                    ? "oklch(0.58 0.18 145)"   // emerald — surplus
                    : "oklch(0.58 0.22 25)"    // red — deficit
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Monthly table ─────────────────────────────────────────────────────────────

function NetBar({ net, maxAbs }: { net: number; maxAbs: number }) {
  if (maxAbs === 0) return null;
  const pct = Math.min((Math.abs(net) / maxAbs) * 100, 100);
  const positive = net >= 0;
  return (
    <div className="flex items-center gap-1.5">
      {/* Negative side */}
      <div className="flex h-1.5 w-12 justify-end overflow-hidden rounded-l-full bg-muted">
        {!positive && (
          <div
            className="h-full rounded-l-full bg-destructive/70"
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      {/* Center divider */}
      <div className="h-3 w-px bg-border" />
      {/* Positive side */}
      <div className="h-1.5 w-12 overflow-hidden rounded-r-full bg-muted">
        {positive && (
          <div
            className="h-full rounded-r-full bg-emerald-400/70"
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
    </div>
  );
}

function MonthlyTable({ series }: { series: MonthlyEntry[] }) {
  if (!series.length) return null;

  // Compute running balance and max abs net for bar scaling
  const maxAbsNet = Math.max(...series.map((r) => Math.abs(r.net)));
  let balance = 0;
  const rows = series.map((row) => {
    balance += row.net;
    return { ...row, runningBalance: balance };
  });

  // Totals
  const totalIn  = series.reduce((s, r) => s + r.in,  0);
  const totalOut = series.reduce((s, r) => s + r.out, 0);
  const totalNet = series.reduce((s, r) => s + r.net, 0);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" role="table" aria-label="Monthly cash flow">
        <thead>
          <tr className="border-b border-border">
            <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">
              Month
            </th>
            <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">
              Cash In
            </th>
            <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">
              Cash Out
            </th>
            <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">
              Net
            </th>
            <th className="hidden px-4 py-2.5 text-center text-xs font-medium text-muted-foreground sm:table-cell">
              Flow
            </th>
            <th className="hidden px-4 py-2.5 text-right text-xs font-medium text-muted-foreground lg:table-cell">
              Running Balance
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const netPositive = row.net >= 0;
            const isNegativeStreak =
              !netPositive &&
              i > 0 &&
              rows[i - 1].net < 0;
            return (
              <tr
                key={i}
                className={cn(
                  "border-b border-border/40 last:border-0 transition-colors hover:bg-muted/20",
                  isNegativeStreak && "bg-destructive/4"
                )}
              >
                <td className="px-4 py-2.5 text-xs tabular-nums text-muted-foreground">
                  {row.month}
                  {row.projected && (
                    <span className="ml-1 rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">
                      proj
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-sm text-emerald-400">
                  {formatCurrency(row.in / 100)}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-sm text-muted-foreground">
                  {formatCurrency(row.out / 100)}
                </td>
                <td
                  className={cn(
                    "px-4 py-2.5 text-right tabular-nums text-sm font-medium",
                    netPositive ? "text-emerald-400" : "text-destructive"
                  )}
                >
                  {netPositive ? "+" : "−"}
                  {formatCurrency(Math.abs(row.net / 100))}
                </td>
                <td className="hidden px-4 py-2.5 sm:table-cell">
                  <div className="flex justify-center">
                    <NetBar net={row.net} maxAbs={maxAbsNet} />
                  </div>
                </td>
                <td
                  className={cn(
                    "hidden px-4 py-2.5 text-right tabular-nums text-xs lg:table-cell",
                    row.runningBalance >= 0 ? "text-muted-foreground" : "text-destructive"
                  )}
                >
                  {row.runningBalance >= 0 ? "" : "−"}
                  {formatCurrency(Math.abs(row.runningBalance / 100))}
                </td>
              </tr>
            );
          })}
        </tbody>
        {/* Summary footer */}
        <tfoot>
          <tr className="border-t border-border bg-muted/20">
            <td className="px-4 py-2.5 text-xs font-semibold text-muted-foreground">
              Total
            </td>
            <td className="px-4 py-2.5 text-right tabular-nums text-xs font-semibold text-emerald-400">
              {formatCurrency(totalIn / 100)}
            </td>
            <td className="px-4 py-2.5 text-right tabular-nums text-xs font-semibold text-muted-foreground">
              {formatCurrency(totalOut / 100)}
            </td>
            <td
              className={cn(
                "px-4 py-2.5 text-right tabular-nums text-xs font-semibold",
                totalNet >= 0 ? "text-emerald-400" : "text-destructive"
              )}
            >
              {totalNet >= 0 ? "+" : "−"}
              {formatCurrency(Math.abs(totalNet / 100))}
            </td>
            <td className="hidden sm:table-cell" />
            <td className="hidden lg:table-cell" />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center px-6">
      <div className="mb-4 rounded-full bg-muted p-4">
        <Upload className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold">No cash flow data</h2>
      <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
        Upload a financial document and run an analysis to see cash flow details.
      </p>
      <a
        href="/upload"
        className={cn(
          "mt-5 inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground",
          "transition-opacity hover:opacity-90",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        )}
      >
        Upload document
      </a>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CashflowPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");

  const { data: dashboard, isLoading } = useDashboard(jobId);

  if (!jobId || (!isLoading && !dashboard)) return <EmptyState />;

  if (isLoading) {
    return (
      <div className="space-y-4 p-5">
        <div className="h-6 w-40 animate-pulse rounded bg-muted" />
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-card px-4 py-4">
              <div className="h-3 w-16 animate-pulse rounded bg-muted" />
              <div className="mt-2 h-5 w-24 animate-pulse rounded bg-muted" />
            </div>
          ))}
        </div>
        <div className="h-72 animate-pulse rounded-lg bg-muted" />
      </div>
    );
  }

  const cf = dashboard!.cashflow;
  const netPositive = cf.net_change >= 0;
  const opPositive = cf.operating >= 0;

  const metrics: MetricItem[] = [
    { label: "Operating", value: formatCurrency(cf.operating), positive: opPositive, neutral: false },
    { label: "Investing", value: formatCurrency(cf.investing), neutral: true },
    { label: "Financing", value: formatCurrency(cf.financing), neutral: true },
    { label: "Net Change", value: formatCurrency(cf.net_change), positive: netPositive, neutral: false },
  ];

  return (
    <div className="space-y-4 p-5">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Cash Flow Statement</h1>
        {cf.narrative && (
          <p className="mt-1 text-sm text-muted-foreground max-w-prose leading-relaxed">
            {cf.narrative}
          </p>
        )}
      </div>

      {/* Alerts */}
      {cf.alerts?.length > 0 && <AlertStrip alerts={cf.alerts} />}

      {/* Summary metrics */}
      <MetricStrip metrics={metrics} />

      {/* Monthly in/out area chart */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="mb-0.5 text-sm font-medium">Monthly Cash Flow</h2>
        <p className="mb-4 text-xs text-muted-foreground">Cash in vs. out per month</p>
        <MonthlyCashFlowChart series={cf.monthly_series} />
      </div>

      {/* Net cash flow bar chart */}
      {cf.monthly_series.length > 0 && (
        <NetCashFlowBar series={cf.monthly_series} />
      )}

      {/* Monthly table */}
      {cf.monthly_series.length > 0 && (
        <div className="rounded-lg border border-border bg-card">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-medium">Monthly Breakdown</h2>
          </div>
          <MonthlyTable series={cf.monthly_series} />
        </div>
      )}
    </div>
  );
}
