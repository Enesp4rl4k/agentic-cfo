"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  ComposedChart,
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
import { useI18n } from "@/hooks/useI18n";
import { useCurrencyFormat, useCurrencySymbol } from "@/hooks/useCurrencyFormat";
import { cn } from "@/lib/utils";
import type { Alert, ForecastScenario } from "@/types";

// ── Chart style ───────────────────────────────────────────────────────────────

const tooltipStyle = {
  contentStyle: {
    background: "oklch(0.21 0.018 70)",
    border: "1px solid oklch(0.32 0.019 68)",
    borderRadius: "6px",
    fontSize: "12px",
    color: "oklch(0.94 0.012 85)",
    padding: "8px 12px",
  },
  cursor: { stroke: "oklch(0.38 0.02 70)", strokeWidth: 1 },
};

const axisStyle = {
  tick: { fontSize: 11, fill: "oklch(0.72 0.017 78)" },
  axisLine: { stroke: "oklch(0.32 0.019 68)" },
  tickLine: false as const,
};

const SCENARIO_COLORS = {
  optimistic:  { line: "oklch(0.72 0.19 142)",  fill: "oklch(0.72 0.19 142 / 0.12)" },
  base:        { line: "oklch(0.79 0.115 83)",  fill: "oklch(0.79 0.115 83 / 0.18)" },
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
  const fmt = useCurrencyFormat();
  const symbol = useCurrencySymbol();
  const { t } = useI18n();
  const { fan } = t.forecast;

  const base = scenarios.base?.months ?? [];
  if (!base.length) {
    return (
      <div className="flex h-[260px] items-center justify-center text-xs text-muted-foreground">
        {fan.empty}
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
    `${v < 0 ? "-" : ""}${symbol}${Math.abs(v) >= 1000 ? `${(Math.abs(v) / 1000).toFixed(0)}k` : Math.abs(v)}`;

  return (
    <ResponsiveContainer width="100%" height={280}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
        <defs>
          <linearGradient id="fanGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor="oklch(0.79 0.115 83)" stopOpacity={0.18} />
            <stop offset="95%" stopColor="oklch(0.79 0.115 83)" stopOpacity={0.04} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.27 0.017 70)" vertical={false} />
        <XAxis dataKey="month" {...axisStyle} />
        <YAxis {...axisStyle} tickFormatter={fmtK} />
        <Tooltip
          {...tooltipStyle}
          formatter={(v: number, name: string) => [fmt(v), name]}
        />
        <ReferenceLine y={0} stroke="oklch(0.40 0.02 70)" strokeDasharray="3 3" />

        {/* Confidence band */}
        <Area
          dataKey="band"
          name={fan.band}
          fill="url(#fanGradient)"
          stroke="none"
          activeDot={false}
          legendType="none"
        />

        {/* Pessimistic line */}
        <Line
          type="monotone"
          dataKey="pessimistic"
          name={fan.pessimistic}
          stroke={SCENARIO_COLORS.pessimistic.line}
          strokeWidth={1.5}
          dot={false}
          strokeDasharray="3 3"
        />

        {/* Optimistic line */}
        <Line
          type="monotone"
          dataKey="optimistic"
          name={fan.optimistic}
          stroke={SCENARIO_COLORS.optimistic.line}
          strokeWidth={1.5}
          dot={false}
          strokeDasharray="5 2"
        />

        {/* Base scenario — solid, prominent */}
        <Line
          type="monotone"
          dataKey="base"
          name={fan.base}
          stroke={SCENARIO_COLORS.base.line}
          strokeWidth={2.5}
          dot={false}
        />

        <Legend wrapperStyle={{ fontSize: "11px", color: "oklch(0.72 0.017 78)" }} />
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
  const fmt = useCurrencyFormat();
  const { t } = useI18n();
  const { table } = t.forecast;

  const rows = ["optimistic", "base", "pessimistic"]
    .filter((k) => k in scenarios)
    .map((k) => [k, scenarios[k]] as [string, ForecastScenario]);

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">{table.heading}</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {table.hint}
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" role="table" aria-label={table.ariaLabel}>
          <thead>
            <tr className="border-b border-border">
              <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">
                {table.colScenario}
              </th>
              <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">
                {table.colNet}
              </th>
              <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">
                {table.colRunway}
              </th>
              <th className="hidden px-4 py-2.5 text-left text-xs font-medium text-muted-foreground sm:table-cell">
                {table.colAssumption}
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
                    {fmt(s.twelve_month_net)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-sm text-muted-foreground">
                    {s.runway_months != null
                      ? table.monthsShort.replace("{count}", String(s.runway_months))
                      : table.stable}
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
  const fmt = useCurrencyFormat();
  const symbol = useCurrencySymbol();
  const { t } = useI18n();
  const { breakdown } = t.forecast;

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
    `${v < 0 ? "-" : ""}${symbol}${Math.abs(v) >= 1000 ? `${(Math.abs(v) / 1000).toFixed(0)}k` : Math.abs(v)}`;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-1 flex items-center gap-2">
        <span
          className="h-2.5 w-2.5 rounded-full"
          style={{ background: color }}
          aria-hidden="true"
        />
        <h2 className="text-sm font-medium">
          {breakdown.heading.replace("{label}", scenario.label)}
        </h2>
      </div>
      <p className="mb-4 text-xs text-muted-foreground">
        {breakdown.subtitle}
      </p>
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={data} margin={{ top: 4, right: 4, left: -8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.27 0.017 70)" vertical={false} />
          <XAxis dataKey="month" {...axisStyle} />
          <YAxis {...axisStyle} tickFormatter={fmtK} />
          <Tooltip
            {...tooltipStyle}
            formatter={(v: number, name: string) => [fmt(v), name]}
          />
          <Bar dataKey="revenue"  name={breakdown.revenue}  fill="oklch(0.72 0.19 142)" opacity={0.75} maxBarSize={10} />
          <Bar dataKey="expenses" name={breakdown.expenses} fill="oklch(0.58 0.22 25)"  opacity={0.65} maxBarSize={10} />
          <Line
            type="monotone"
            dataKey="net"
            name={breakdown.net}
            stroke={color}
            strokeWidth={2}
            dot={false}
          />
          <Legend wrapperStyle={{ fontSize: "11px", color: "oklch(0.72 0.017 78)" }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  const { t } = useI18n();
  const { empty } = t.forecast;

  return (
    <div className="flex flex-col items-center justify-center py-20 text-center px-6">
      <div className="mb-4 rounded-full bg-muted p-4">
        <Upload className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold">{empty.heading}</h2>
      <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
        {empty.body}
      </p>
      <a
        href="/upload"
        className={cn(
          "mt-5 inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground",
          "transition-opacity hover:opacity-90",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        )}
      >
        {empty.cta}
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
  const fmt = useCurrencyFormat();
  const { t } = useI18n();
  const { kpi, fan } = t.forecast;

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

  // Backend alert messages are data, filtered on their English keywords.
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
        <h1 className="text-lg font-semibold tracking-tight">{t.forecast.title}</h1>
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
              label={kpi.baseNet}
              value={fmt(base.twelve_month_net)}
              sub={
                base.runway_months
                  ? kpi.runway.replace("{count}", String(base.runway_months))
                  : kpi.runwayStable
              }
              positive={base.twelve_month_net >= 0}
            />
          )}
          {opt && (
            <KPICard
              label={kpi.optimisticUpside}
              value={
                base
                  ? `+${fmt(opt.twelve_month_net - base.twelve_month_net)}`
                  : fmt(opt.twelve_month_net)
              }
              sub={kpi.vsBase}
              positive
            />
          )}
          {pes && (
            <KPICard
              label={kpi.pessimisticDownside}
              value={
                base
                  ? `${fmt(pes.twelve_month_net - base.twelve_month_net)}`
                  : fmt(pes.twelve_month_net)
              }
              sub={kpi.vsBase}
              positive={false}
            />
          )}
        </div>
      )}

      {/* Monte Carlo fan chart */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="mb-1 flex items-center gap-2">
          <h2 className="text-sm font-medium">{fan.heading}</h2>
          <span
            title={fan.tip}
            className="cursor-help"
          >
            <Info className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
          </span>
        </div>
        <p className="mb-4 text-xs text-muted-foreground">
          {fan.hint}
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
