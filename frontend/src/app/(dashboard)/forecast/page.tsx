"use client";

import { useSearchParams } from "next/navigation";
import {
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { AlertTriangle, Upload } from "lucide-react";
import { useDashboard } from "@/hooks/useCFO";
import { formatCurrency, cn } from "@/lib/utils";
import type { Alert, ForecastScenario } from "@/types";

// ── Shared chart style ────────────────────────────────────────────────────────

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

const SCENARIO_COLORS = {
  optimistic: "oklch(0.72 0.19 142)",  // emerald
  base:       "oklch(0.60 0.19 255)",  // blue
  pessimistic: "oklch(0.58 0.22 25)",  // red-orange
} as const;

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

// ── Scenario comparison table ─────────────────────────────────────────────────

function ScenarioTable({
  scenarios,
}: {
  scenarios: Record<string, ForecastScenario>;
}) {
  const rows = Object.entries(scenarios);
  const sign = (n: number) => (n >= 0 ? "+" : "");

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">12-Month Scenario Comparison</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Based on historical trends — optimistic, base, and pessimistic projections
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" role="table" aria-label="Forecast scenarios">
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
              <th className="hidden px-4 py-2.5 text-left text-xs font-medium text-muted-foreground sm:table-cell">
                Assumption
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([key, s]) => {
              const isBase = key === "base";
              const netPositive = s.twelve_month_net >= 0;
              const color = SCENARIO_COLORS[key as keyof typeof SCENARIO_COLORS];
              return (
                <tr
                  key={key}
                  className={cn(
                    "border-b border-border/50 last:border-0",
                    isBase ? "bg-primary/5" : "hover:bg-muted/20"
                  )}
                >
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center gap-1.5 text-xs font-medium">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ background: color }}
                        aria-hidden="true"
                      />
                      {s.label}
                    </span>
                  </td>
                  <td
                    className={cn(
                      "px-4 py-3 text-right tabular-nums text-sm font-medium",
                      netPositive ? "text-emerald-400" : "text-destructive"
                    )}
                  >
                    {sign(s.twelve_month_net)}
                    {formatCurrency(s.twelve_month_net)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-sm text-muted-foreground">
                    {s.runway_months != null ? `${s.runway_months} mo` : "Stable"}
                  </td>
                  <td className="hidden px-4 py-3 text-xs text-muted-foreground sm:table-cell max-w-[220px]">
                    {s.description}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Projected net cash flow chart ─────────────────────────────────────────────

function ForecastChart({
  scenarios,
}: {
  scenarios: Record<string, ForecastScenario>;
}) {
  // Merge all scenarios by month index
  const base = scenarios.base?.months ?? [];
  if (!base.length) {
    return (
      <div className="flex h-[260px] items-center justify-center text-xs text-muted-foreground">
        No projection data available
      </div>
    );
  }

  const data = base.map((_, i) => ({
    month: base[i]?.month?.slice(5) ?? `M${i + 1}`,
    optimistic: (scenarios.optimistic?.months[i]?.net ?? 0) / 100,
    base: (scenarios.base?.months[i]?.net ?? 0) / 100,
    pessimistic: (scenarios.pessimistic?.months[i]?.net ?? 0) / 100,
  }));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={data} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
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
        <Legend
          wrapperStyle={{ fontSize: "11px", color: "oklch(0.52 0.012 255)" }}
        />
        <Line
          type="monotone"
          dataKey="optimistic"
          name="Optimistic"
          stroke={SCENARIO_COLORS.optimistic}
          strokeWidth={1.5}
          dot={false}
          strokeDasharray="4 2"
        />
        <Bar
          dataKey="base"
          name="Base"
          fill={SCENARIO_COLORS.base}
          opacity={0.7}
          maxBarSize={14}
        />
        <Line
          type="monotone"
          dataKey="pessimistic"
          name="Pessimistic"
          stroke={SCENARIO_COLORS.pessimistic}
          strokeWidth={1.5}
          dot={false}
          strokeDasharray="2 3"
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center px-6">
      <div className="mb-4 rounded-full bg-muted p-4">
        <Upload className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold">No forecast data</h2>
      <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
        Upload a financial document and run an analysis to generate 12-month forecasts.
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

export default function ForecastPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");

  const { data: dashboard, isLoading } = useDashboard(jobId);

  if (!jobId || (!isLoading && !dashboard)) return <EmptyState />;

  if (isLoading) {
    return (
      <div className="space-y-4 p-5">
        <div className="h-6 w-48 animate-pulse rounded bg-muted" />
        <div className="h-72 animate-pulse rounded-lg bg-muted" />
        <div className="h-48 animate-pulse rounded-lg bg-muted" />
      </div>
    );
  }

  const forecast = dashboard!.forecast;
  const alerts = forecast.scenarios
    ? (dashboard!.alerts ?? []).filter(
        (a) =>
          a.message.toLowerCase().includes("runway") ||
          a.message.toLowerCase().includes("forecast") ||
          a.message.toLowerCase().includes("scenario")
      )
    : [];

  return (
    <div className="space-y-4 p-5">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">12-Month Forecast</h1>
        {forecast.narrative && (
          <p className="mt-1 text-sm text-muted-foreground max-w-prose leading-relaxed">
            {forecast.narrative}
          </p>
        )}
      </div>

      {/* Forecast-specific alerts */}
      {alerts.length > 0 && <AlertStrip alerts={alerts} />}

      {/* Projected net cash flow chart */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="mb-0.5 text-sm font-medium">Projected Monthly Net Cash Flow</h2>
        <p className="mb-4 text-xs text-muted-foreground">
          Three scenarios over the next 12 months
        </p>
        <ForecastChart scenarios={forecast.scenarios} />
      </div>

      {/* Scenario comparison table */}
      <ScenarioTable scenarios={forecast.scenarios} />
    </div>
  );
}
