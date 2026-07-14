"use client";

import { useSearchParams } from "next/navigation";
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
import { useDashboard } from "@/hooks/useCFO";
import { formatCurrency, cn } from "@/lib/utils";
import type { CashFlowData } from "@/types";

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

function StatCard({
  label,
  value,
  sub,
  positive,
}: {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean;
}) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 text-lg font-semibold tabular tracking-tight",
          positive === true
            ? "text-success"
            : positive === false
            ? "text-destructive"
            : "text-foreground"
        )}
      >
        {value}
      </p>
      {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function MonthlyCashFlowChart({
  series,
}: {
  series: CashFlowData["monthly_series"];
}) {
  const data = series.map((m) => ({
    month: m.month.slice(5),
    in: m.in / 100,
    out: m.out / 100,
    net: m.net / 100,
  }));

  if (!data.length) {
    return (
      <div className="flex h-64 items-center justify-center rounded-lg border border-border bg-card text-sm text-muted-foreground">
        No monthly data available
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-0.5 text-sm font-medium">Monthly Cash Flow</h3>
      <p className="mb-4 text-xs text-muted-foreground">Cash in vs. out per month</p>
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={data} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
          <defs>
            <linearGradient id="gIn" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="oklch(0.60 0.19 255)" stopOpacity={0.3} />
              <stop offset="100%" stopColor="oklch(0.60 0.19 255)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="gOut" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="oklch(0.58 0.22 25)" stopOpacity={0.25} />
              <stop offset="100%" stopColor="oklch(0.58 0.22 25)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="gNet" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="oklch(0.60 0.19 142)" stopOpacity={0.3} />
              <stop offset="100%" stopColor="oklch(0.60 0.19 142)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.22 0.018 255)" vertical={false} />
          <XAxis dataKey="month" {...axisStyle} />
          <YAxis
            {...axisStyle}
            tickFormatter={(v: number) =>
              `₺${Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`
            }
          />
          <Tooltip
            {...tooltipStyle}
            formatter={(v: number, name: string) => [formatCurrency(v), name]}
          />
          <ReferenceLine y={0} stroke="oklch(0.35 0.018 255)" strokeWidth={1} />
          <Area type="monotone" dataKey="in" name="Cash In" stroke="oklch(0.60 0.19 255)" strokeWidth={1.5} fill="url(#gIn)" dot={false} />
          <Area type="monotone" dataKey="out" name="Cash Out" stroke="oklch(0.58 0.22 25)" strokeWidth={1.5} fill="url(#gOut)" dot={false} />
          <Area type="monotone" dataKey="net" name="Net" stroke="oklch(0.60 0.19 142)" strokeWidth={2} fill="url(#gNet)" dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function NetBarChart({ series }: { series: CashFlowData["monthly_series"] }) {
  const data = series.map((m) => ({
    month: m.month.slice(5),
    net: m.net / 100,
  }));

  if (!data.length) return null;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-0.5 text-sm font-medium">Net Cash by Month</h3>
      <p className="mb-4 text-xs text-muted-foreground">Positive = surplus, negative = deficit</p>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.22 0.018 255)" vertical={false} />
          <XAxis dataKey="month" {...axisStyle} />
          <YAxis
            {...axisStyle}
            tickFormatter={(v: number) =>
              `₺${Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`
            }
          />
          <Tooltip
            {...tooltipStyle}
            formatter={(v: number) => [formatCurrency(v), "Net"]}
          />
          <ReferenceLine y={0} stroke="oklch(0.35 0.018 255)" />
          <Bar
            dataKey="net"
            fill="oklch(0.60 0.19 255)"
            radius={[3, 3, 0, 0]}
            maxBarSize={32}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function CashFlowPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const { data: dashboard, isLoading } = useDashboard(jobId);

  if (!jobId) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center px-6">
        <p className="text-sm text-muted-foreground">
          No job selected. Upload a document first.
        </p>
      </div>
    );
  }

  if (isLoading || !dashboard) {
    return (
      <div className="space-y-4 p-5">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-16 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    );
  }

  const { cashflow } = dashboard;
  const netPositive = cashflow.net_change >= 0;
  const opPositive = cashflow.operating >= 0;

  return (
    <div className="space-y-5 p-5">
      <div>
        <h2 className="text-base font-semibold">Cash Flow Statement</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Operating · Investing · Financing activities
        </p>
      </div>

      {/* Alerts */}
      {cashflow.alerts?.map((a, i) => (
        <div
          key={i}
          role="alert"
          className={cn(
            "flex items-start gap-2.5 rounded-md border px-3.5 py-2.5 text-sm",
            a.level === "critical"
              ? "border-destructive/30 bg-destructive/8 text-destructive"
              : "border-warning/25 bg-warning/6 text-warning"
          )}
        >
          {a.message}
        </div>
      ))}

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Operating" value={formatCurrency(cashflow.operating)} positive={opPositive} />
        <StatCard label="Investing" value={formatCurrency(cashflow.investing)} />
        <StatCard label="Financing" value={formatCurrency(cashflow.financing)} />
        <StatCard label="Net Change" value={formatCurrency(cashflow.net_change)} positive={netPositive} />
      </div>

      {/* Charts */}
      <MonthlyCashFlowChart series={cashflow.monthly_series} />
      <NetBarChart series={cashflow.monthly_series} />

      {/* CFO narrative */}
      {cashflow.narrative && (
        <div className="rounded-lg border border-border bg-card px-4 py-3.5">
          <p className="mb-1 text-xs font-medium text-primary">CFO Commentary</p>
          <p className="text-sm leading-relaxed text-muted-foreground max-w-prose">
            {cashflow.narrative}
          </p>
        </div>
      )}

      {/* Monthly table */}
      {cashflow.monthly_series.length > 0 && (
        <div className="rounded-lg border border-border bg-card">
          <div className="border-b border-border px-4 py-3">
            <h3 className="text-sm font-medium">Monthly Breakdown</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" role="table">
              <thead>
                <tr className="border-b border-border">
                  {["Month", "Cash In", "Cash Out", "Net"].map((h) => (
                    <th
                      key={h}
                      className={cn(
                        "px-4 py-2.5 text-xs font-medium text-muted-foreground",
                        h === "Month" ? "text-left" : "text-right"
                      )}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {cashflow.monthly_series.map((m, i) => (
                  <tr key={i} className="border-b border-border/40 last:border-0 hover:bg-muted/20">
                    <td className="px-4 py-2.5 text-xs tabular text-muted-foreground">{m.month}</td>
                    <td className="px-4 py-2.5 text-right tabular text-sm text-success">
                      {formatCurrency(m.in / 100)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular text-sm text-destructive">
                      {formatCurrency(m.out / 100)}
                    </td>
                    <td
                      className={cn(
                        "px-4 py-2.5 text-right tabular text-sm font-medium",
                        m.net >= 0 ? "text-success" : "text-destructive"
                      )}
                    >
                      {formatCurrency(m.net / 100)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
