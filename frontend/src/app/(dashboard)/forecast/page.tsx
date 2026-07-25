"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  ComposedChart,
  AreaChart,
  Area,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ReferenceLine,
} from "recharts";
import { AlertTriangle, Upload, TrendingUp, TrendingDown, Minus, Info } from "lucide-react";
import { useDashboard } from "@/hooks/useCFO";
import { formatCurrency, cn } from "@/lib/utils";
import type { Alert, ForecastScenario } from "@/types";

// ── Chart style ───────────────────────────────────────────────────────────────

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
  optimistic:  { line: "oklch(0.72 0.19 142)",  fill: "oklch(0.72 0.19 142 / 0.12)" },
  base:        { line: "oklch(0.60 0.19 255)",  fill: "oklch(0.60 0.19 255 / 0.18)" },
  pessimistic: { line: "oklch(0.58 0.22 25)",   fill: "oklch(0.58 0.22 25 / 0.12)" },
};

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

// ── KPI cards ─────────────────────────────────────────────────────────────────

function KPICard({
  label,
  value,
  sub,
  positive,
  neutral,
}: {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean;
  neutral?: boolean;
}) {
  const TrendIcon = neutral ? Minus : positive ? TrendingUp : TrendingDown;
  const colorCls = neutral
    ? "text-muted-foreground"
    : positive
    ? "text-emerald-400"
    : "text-destructive";

  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-1 flex items-end gap-1.5">
        <p className={cn("text-lg font-semibold tabular-nums leading-none", colorCls)}>
          {value}
        </p>
        <TrendIcon className={cn("mb-0.5 h-3.5 w-3.5", colorCls)} aria-hidden="true" />
      </div>
      {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

// ── Monte Carlo fan chart ─────────────────────────────────────────────────────
// Shows the spread (fan) between pessimistic and optimistic as a filled band,
// with the base scenario as a solid line through the middle.

function MonteCarloFanChart({
  scenarios,
}: {
  scenarios: Record<string, ForecastScenario>;
}) {
  const base = scenarios.base?.months ?? [];
  if (!base.length) {
    return (
      <div className="flex h-[260px] items-center justify-center text-xs text-muted-foreground">
        No projection data available
      </div>
    );
  }

  const data = base.map((_, i) => {
    const opt  = (scenarios.optimistic?.months[i]?.net  ?? 0) / 100;
    const bas  = (scenarios.base?.months[i]?.net        ?? 0) / 100;
    const pes  = (scenarios.pessimistic?.months[i]?.net ?? 0) / 100;
    const month = base[i]?.month?.slice(5) ?? `M${i + 1}`;
    return {
      month,
      // Area uses [low, high] for the band
      band: [Math.min(opt, pes), Math.max(opt, pes)] as [number, number],
      base: bas,
      optimistic: opt,
      pessimistic: pes,
    };
  });

  const fmtK = (v: number) =>
    `${v < 0 ? "-" : ""}₺${Math.abs(v) >= 1000 ? `${(Math.abs(v) / 1000).toFixed(0)}k` : Math.abs(v)}`;

  return (
    <ResponsiveContainer width="100%" height={280}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
        <defs>
          <linearGradient id="fanGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor="oklch(0.60 0.19 255)" stopOpacity={0.18} />
            <stop offset="95%" stopColor="oklch(0.60 0.19 255)" stopOpacity={0.04} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.22 0.018 255)" vertical={false} />
        <XAxis dataKey="month" {...axisStyle} />
        <YAxis {...axisStyle} tickFormatter={fmtK} />
        <Tooltip
          {...tooltipStyle}
          formatter={(v: number, name: string) => [formatCurrency(v), name]}
        />
        <ReferenceLine y={0} stroke="oklch(0.35 0.018 255)" strokeDasharray="3 3" />

        {/* Confidence band */}
        <Area
          dataKey="band"
          name="Confidence band"
          fill="url(#fanGradient)"
          stroke="none"
          activeDot={false}
          legendType="none"
        />

        {/* Pessimistic line */}
        <Line
          type="monotone"
          dataKey="pessimistic"
          name="Pessimistic"
          stroke={SCENARIO_COLORS.pessimistic.line}
          strokeWidth={1.5}
          dot={false}
          strokeDasharray="3 3"
        />

        {/* Optimistic line */}
        <Line
          type="monotone"
          dataKey="optimistic"
          name="Optimistic"
          stroke={SCENARIO_COLORS.optimistic.line}
          strokeWidth={1.5}
          dot={false}
          strokeDasharray="5 2"
        />

        {/* Base scenario — solid, prominent */}
        <Line
          type="monotone"
          dataKey="base"
          name="Base"
          stroke={SCENARIO_COLORS.base.line}
          strokeWidth={2.5}
          dot={false}
        />

        <Legend wrapperStyle={{ fontSize: "11px", color: "oklch(0.52 0.012 255)" }} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// ── Scenario comparison table ─────────────────────────────────────────────────

function ScenarioTable({
  scenarios,
  activeScenario,
  onSelect,
}: {
  scenarios: Record<string, ForecastScenario>;
  activeScenario: string;
  onSelect: (key: string) => void;
}) {
  const rows = ["optimistic", "base", "pessimistic"]
    .filter((k) => k in scenarios)
    .map((k) => [k, scenarios[k]] as [string, ForecastScenario]);

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">Scenario Comparison</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Click a row to view its monthly breakdown below
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
                Runway
              </th>
              <th className="hidden px-4 py-2.5 text-left text-xs font-medium text-muted-foreground sm:table-cell">
                Assumption
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([key, s]) => {
              const isActive = key === activeScenario;
              const color = SCENARIO_COLORS[key as keyof typeof SCENARIO_COLORS]?.line;
              const netPositive = s.twelve_month_net >= 0;
              return (
                <tr
                  key={key}
                  onClick={() => onSelect(key)}
                  className={cn(
                    "cursor-pointer border-b border-border/50 last:border-0 transition-colors",
                    isActive ? "bg-primary/5 ring-1 ring-inset ring-primary/20" : "hover:bg-muted/20"
                  )}
                  aria-selected={isActive}
                >
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center gap-1.5 text-xs font-medium">
                      <span
                        className="h-2 w-2 rounded-full shrink-0"
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
                    {netPositive ? "+" : ""}
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

// ── Monthly breakdown bar chart ───────────────────────────────────────────────

function MonthlyBreakdownChart({
  scenario,
  scenarioKey,
}: {
  scenario: ForecastScenario;
  scenarioKey: string;
}) {
  const months = scenario.months ?? [];
  if (!months.length) return null;

  const color = SCENARIO_COLORS[scenarioKey as keyof typeof SCENARIO_COLORS]?.line
    ?? SCENARIO_COLORS.base.line;

  const data = months.map((m) => ({
    month: m.month?.slice(5) ?? "?",
    revenue: (m.in ?? 0) / 100,
    expenses: (m.out ?? 0) / 100,
    net: (m.net ?? 0) / 100,
  }));

  const fmtK = (v: number) =>
    `${v < 0 ? "-" : ""}₺${Math.abs(v) >= 1000 ? `${(Math.abs(v) / 1000).toFixed(0)}k` : Math.abs(v)}`;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-1 flex items-center gap-2">
        <span
          className="h-2.5 w-2.5 rounded-full"
          style={{ background: color }}
          aria-hidden="true"
        />
        <h2 className="text-sm font-medium">{scenario.label} — Monthly Breakdown</h2>
      </div>
      <p className="mb-4 text-xs text-muted-foreground">
        Revenue, expenses, and net cash flow per month
      </p>
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={data} margin={{ top: 4, right: 4, left: -8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.22 0.018 255)" vertical={false} />
          <XAxis dataKey="month" {...axisStyle} />
          <YAxis {...axisStyle} tickFormatter={fmtK} />
          <Tooltip
            {...tooltipStyle}
            formatter={(v: number, name: string) => [formatCurrency(v), name]}
          />
          <Bar dataKey="revenue"  name="Revenue"  fill="oklch(0.72 0.19 142)" opacity={0.75} maxBarSize={10} />
          <Bar dataKey="expenses" name="Expenses" fill="oklch(0.58 0.22 25)"  opacity={0.65} maxBarSize={10} />
          <Line
            type="monotone"
            dataKey="net"
            name="Net"
            stroke={color}
            strokeWidth={2}
            dot={false}
          />
          <Legend wrapperStyle={{ fontSize: "11px", color: "oklch(0.52 0.012 255)" }} />
        </ComposedChart>
      </ResponsiveContainer>
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
  const [activeScenario, setActiveScenario] = useState("base");

  const { data: dashboard, isLoading } = useDashboard(jobId);

  if (!jobId || (!isLoading && !dashboard)) return <EmptyState />;

  if (isLoading) {
    return (
      <div className="space-y-4 p-5">
        <div className="h-6 w-48 animate-pulse rounded bg-muted" />
        <div className="grid grid-cols-3 gap-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
        <div className="h-72 animate-pulse rounded-lg bg-muted" />
        <div className="h-48 animate-pulse rounded-lg bg-muted" />
      </div>
    );
  }

  const forecast = dashboard!.forecast;
  const scenarios = forecast.scenarios ?? {};
  const base = scenarios.base;
  const opt  = scenarios.optimistic;
  const pes  = scenarios.pessimistic;

  const alerts = (dashboard!.alerts ?? []).filter(
    (a) =>
      a.message.toLowerCase().includes("runway") ||
      a.message.toLowerCase().includes("forecast") ||
      a.message.toLowerCase().includes("scenario")
  );

  const activeScenarioData = (scenarios as Record<string, ForecastScenario>)[activeScenario];

  return (
    <div className="space-y-4 p-5">
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold tracking-tight">12-Month Forecast</h1>
        {forecast.narrative && (
          <p className="mt-1 max-w-prose text-sm text-muted-foreground leading-relaxed">
            {forecast.narrative}
          </p>
        )}
      </div>

      {/* Alerts */}
      {alerts.length > 0 && <AlertStrip alerts={alerts} />}

      {/* KPI strip */}
      {(base || opt || pes) && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {base && (
            <KPICard
              label="Base Case 12-Month Net"
              value={formatCurrency(base.twelve_month_net)}
              sub={base.runway_months ? `${base.runway_months} months runway` : "Stable runway"}
              positive={base.twelve_month_net >= 0}
            />
          )}
          {opt && (
            <KPICard
              label="Optimistic Upside"
              value={
                base
                  ? `+${formatCurrency(opt.twelve_month_net - base.twelve_month_net)}`
                  : formatCurrency(opt.twelve_month_net)
              }
              sub="vs base case"
              positive
            />
          )}
          {pes && (
            <KPICard
              label="Pessimistic Downside"
              value={
                base
                  ? `${formatCurrency(pes.twelve_month_net - base.twelve_month_net)}`
                  : formatCurrency(pes.twelve_month_net)
              }
              sub="vs base case"
              positive={false}
            />
          )}
        </div>
      )}

      {/* Monte Carlo fan chart */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="mb-1 flex items-center gap-2">
          <h2 className="text-sm font-medium">Monte Carlo Projection Fan</h2>
          <span
            title="The shaded band represents the full range between optimistic and pessimistic scenarios"
            className="cursor-help"
          >
            <Info className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
          </span>
        </div>
        <p className="mb-4 text-xs text-muted-foreground">
          Shaded band = scenario spread · solid line = base case
        </p>
        <MonteCarloFanChart scenarios={scenarios} />
      </div>

      {/* Scenario table — clickable rows */}
      <ScenarioTable
        scenarios={scenarios}
        activeScenario={activeScenario}
        onSelect={setActiveScenario}
      />

      {/* Monthly breakdown for selected scenario */}
      {activeScenarioData && (
        <MonthlyBreakdownChart
          scenario={activeScenarioData}
          scenarioKey={activeScenario}
        />
      )}
    </div>
  );
}
