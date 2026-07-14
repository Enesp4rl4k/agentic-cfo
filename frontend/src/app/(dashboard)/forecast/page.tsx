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
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { useDashboard } from "@/hooks/useCFO";
import { formatCurrency, cn } from "@/lib/utils";
import type { ForecastScenario } from "@/types";

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
  optimistic: "oklch(0.60 0.19 142)",  // green
  base: "oklch(0.60 0.19 255)",         // blue
  pessimistic: "oklch(0.58 0.22 25)",   // red
} as const;

function ScenarioChart({ scenario, color }: { scenario: ForecastScenario; color: string }) {
  const data = scenario.months.map((m) => ({
    month: m.month.slice(5),
    in: m.in / 100,
    out: m.out / 100,
    net: m.net / 100,
  }));

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="h-2 w-2 rounded-full" style={{ background: color }} aria-hidden="true" />
        <h3 className="text-sm font-medium">{scenario.label}</h3>
        <span className="ml-auto text-xs text-muted-foreground">{scenario.description}</span>
      </div>
      <div className="mb-3 flex gap-4 text-xs">
        <span>
          12m Net:{" "}
          <strong
            className={cn(
              "tabular",
              scenario.twelve_month_net >= 0 ? "text-success" : "text-destructive"
            )}
          >
            {formatCurrency(scenario.twelve_month_net)}
          </strong>
        </span>
        <span>
          Runway:{" "}
          <strong className="text-foreground tabular">
            {scenario.runway_months != null ? `${scenario.runway_months} mo` : "Stable"}
          </strong>
        </span>
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <ComposedChart data={data} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
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
          <Bar dataKey="in" name="Cash In" fill={color} opacity={0.3} maxBarSize={20} />
          <Bar dataKey="out" name="Cash Out" fill="oklch(0.58 0.22 25)" opacity={0.3} maxBarSize={20} />
          <Line type="monotone" dataKey="net" name="Net" stroke={color} strokeWidth={2} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function ForecastPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const { data: dashboard, isLoading } = useDashboard(jobId);

  if (!jobId) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center px-6">
        <p className="text-sm text-muted-foreground">No job selected. Upload a document first.</p>
      </div>
    );
  }

  if (isLoading || !dashboard) {
    return (
      <div className="space-y-4 p-5">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-56 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    );
  }

  const { forecast } = dashboard;
  const scenarios = Object.entries(forecast.scenarios) as [
    keyof typeof SCENARIO_COLORS,
    ForecastScenario,
  ][];

  return (
    <div className="space-y-5 p-5">
      <div>
        <h2 className="text-base font-semibold">12-Month Forecast</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Three scenarios based on historical cash flow trends
        </p>
      </div>

      {/* Alerts */}
      {forecast.alerts?.map((a, i) => (
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

      {/* Comparison table */}
      <div className="rounded-lg border border-border bg-card">
        <div className="border-b border-border px-4 py-3">
          <h3 className="text-sm font-medium">Scenario Comparison</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" role="table">
            <thead>
              <tr className="border-b border-border">
                <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Scenario</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">12-Month Net</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">Cash Runway</th>
                <th className="hidden px-4 py-2.5 text-left text-xs font-medium text-muted-foreground sm:table-cell">Assumption</th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map(([key, s]) => (
                <tr key={key} className={cn(
                  "border-b border-border/50 last:border-0",
                  key === "base" ? "bg-primary/5" : "hover:bg-muted/20"
                )}>
                  <td className="px-4 py-3">
                    <span className="flex items-center gap-2 text-sm font-medium">
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ background: SCENARIO_COLORS[key] }}
                        aria-hidden="true"
                      />
                      {s.label}
                    </span>
                  </td>
                  <td className={cn(
                    "px-4 py-3 text-right tabular font-medium text-sm",
                    s.twelve_month_net >= 0 ? "text-success" : "text-destructive"
                  )}>
                    {s.twelve_month_net >= 0 ? "+" : ""}{formatCurrency(s.twelve_month_net)}
                  </td>
                  <td className="px-4 py-3 text-right tabular text-sm text-muted-foreground">
                    {s.runway_months != null ? `${s.runway_months} mo` : "Stable"}
                  </td>
                  <td className="hidden px-4 py-3 text-xs text-muted-foreground sm:table-cell max-w-[240px]">
                    {s.description}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Per-scenario charts */}
      {scenarios.map(([key, s]) => (
        <ScenarioChart key={key} scenario={s} color={SCENARIO_COLORS[key]} />
      ))}

      {/* CFO narrative */}
      {forecast.narrative && (
        <div className="rounded-lg border border-border bg-card px-4 py-3.5">
          <p className="mb-1 text-xs font-medium text-primary">CFO Strategic Recommendation</p>
          <p className="text-sm leading-relaxed text-muted-foreground max-w-prose">
            {forecast.narrative}
          </p>
        </div>
      )}
    </div>
  );
}
