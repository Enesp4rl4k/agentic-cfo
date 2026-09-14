"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Upload, TrendingUp, TrendingDown, ChevronDown, ChevronRight, BarChart3, ChevronUp, RefreshCw } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useDashboard } from "@/hooks/useCFO";
import { apiClient } from "@/lib/api/client";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import type { PnLData } from "@/types";

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
  cursor: { fill: "oklch(0.22 0.018 255 / 0.4)" },
};

const axisStyle = {
  tick: { fontSize: 11, fill: "oklch(0.52 0.012 255)" },
  axisLine: { stroke: "oklch(0.27 0.018 255)" },
  tickLine: false as const,
};

// ── KPI strip ─────────────────────────────────────────────────────────────────

function MarginBar({ value, max = 1 }: { value: number; max?: number }) {
  const pct = Math.min(Math.max((value / max) * 100, 0), 100);
  const color = value >= 0.2 ? "bg-emerald-400" : value >= 0 ? "bg-yellow-400" : "bg-destructive";
  return (
    <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-muted">
      <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
    </div>
  );
}

function KPIStrip({ pnl }: { pnl: PnLData }) {
  const items = [
    {
      label: "Revenue",
      value: formatCurrency(pnl.revenue),
      sub: "Total income",
      positive: true,
      neutral: true,
    },
    {
      label: "Gross Profit",
      value: formatCurrency(pnl.gross_profit),
      sub: `${formatPercent(pnl.gross_margin)} margin`,
      positive: pnl.gross_profit >= 0,
      margin: pnl.gross_margin,
    },
    {
      label: "EBITDA",
      value: formatCurrency(pnl.ebitda),
      sub: `${formatPercent(pnl.ebitda_margin)} margin`,
      positive: pnl.ebitda >= 0,
      margin: pnl.ebitda_margin,
    },
    {
      label: "Net Income",
      value: formatCurrency(pnl.net_income),
      sub: `${formatPercent(pnl.net_margin)} margin`,
      positive: pnl.net_income >= 0,
      margin: pnl.net_margin,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
      {items.map((item) => (
        <div key={item.label} className="bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">{item.label}</p>
          <p
            className={cn(
              "mt-1 text-base font-semibold tabular-nums tracking-tight",
              item.neutral ? "text-foreground" : item.positive ? "text-emerald-400" : "text-destructive"
            )}
          >
            {item.value}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">{item.sub}</p>
          {item.margin != null && <MarginBar value={item.margin} />}
        </div>
      ))}
    </div>
  );
}

// ── Waterfall chart ───────────────────────────────────────────────────────────
// Built with Recharts stacked bars: invisible "base" bar + colored "value" bar

function WaterfallChart({ pnl }: { pnl: PnLData }) {
  const opexEntries = Object.entries(pnl.opex).filter(([, v]) => v != null && v !== 0);
  const totalOpex = opexEntries.reduce((s, [, v]) => s + (v ?? 0), 0);

  // Build waterfall steps
  const steps: { name: string; base: number; value: number; color: string }[] = [];

  let running = 0;

  // Revenue bar (start)
  steps.push({
    name: "Revenue",
    base: 0,
    value: pnl.revenue / 100,
    color: "oklch(0.72 0.19 142)",
  });
  running = pnl.revenue / 100;

  // COGS (negative)
  if (pnl.cogs > 0) {
    steps.push({
      name: "COGS",
      base: (pnl.revenue - pnl.cogs) / 100,
      value: pnl.cogs / 100,
      color: "oklch(0.58 0.22 25 / 0.7)",
    });
    running = (pnl.revenue - pnl.cogs) / 100;
  }

  // OpEx items
  opexEntries.forEach(([key, val]) => {
    const v = (val ?? 0) / 100;
    running -= v;
    steps.push({
      name: key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      base: running,
      value: v,
      color: "oklch(0.55 0.18 255 / 0.6)",
    });
  });

  // Net income (final)
  steps.push({
    name: "Net Income",
    base: 0,
    value: pnl.net_income / 100,
    color: pnl.net_income >= 0 ? "oklch(0.72 0.19 142)" : "oklch(0.58 0.22 25)",
  });

  const fmtK = (v: number) =>
    `${v < 0 ? "-" : ""}₺${Math.abs(v) >= 1000 ? `${(Math.abs(v) / 1000).toFixed(0)}k` : Math.round(Math.abs(v))}`;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-0.5 text-sm font-medium">P&amp;L Waterfall</h2>
      <p className="mb-4 text-xs text-muted-foreground">
        Revenue → COGS → OpEx → Net Income
      </p>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={steps} margin={{ top: 4, right: 4, left: -4, bottom: 40 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.22 0.018 255)" vertical={false} />
          <XAxis
            dataKey="name"
            {...axisStyle}
            angle={-35}
            textAnchor="end"
            interval={0}
          />
          <YAxis {...axisStyle} tickFormatter={fmtK} />
          <Tooltip
            {...tooltipStyle}
            formatter={(v: number, name: string) =>
              name === "value" ? [formatCurrency(v), "Amount"] : null
            }
          />
          {/* Invisible base (spacer) */}
          <Bar dataKey="base" stackId="wf" fill="transparent" />
          {/* Visible bar */}
          <Bar dataKey="value" stackId="wf" radius={[3, 3, 0, 0]}>
            {steps.map((s, i) => (
              <Cell key={i} fill={s.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── OpEx drill-down ───────────────────────────────────────────────────────────

const OPEX_COLORS: Record<string, string> = {
  salary:        "oklch(0.60 0.19 255)",
  rent:          "oklch(0.65 0.18 295)",
  utilities:     "oklch(0.65 0.17 200)",
  marketing:     "oklch(0.65 0.20 330)",
  technology:    "oklch(0.60 0.18 260)",
  other_expense: "oklch(0.50 0.01 255)",
};

function OpExDrillDown({ pnl }: { pnl: PnLData }) {
  const [expanded, setExpanded] = useState(true);
  const entries = Object.entries(pnl.opex)
    .filter(([, v]) => v != null && v !== 0)
    .sort(([, a], [, b]) => (b ?? 0) - (a ?? 0));

  const total = entries.reduce((s, [, v]) => s + (v ?? 0), 0);

  if (!entries.length) return null;

  const data = entries.map(([key, val]) => ({
    name: key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    value: (val ?? 0) / 100,
    pct: total > 0 ? ((val ?? 0) / total) * 100 : 0,
    color: OPEX_COLORS[key] ?? "oklch(0.50 0.01 255)",
  }));

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 border-b border-border px-4 py-3 text-left"
        aria-expanded={expanded}
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        )}
        <div>
          <h2 className="text-sm font-medium">Operating Expenses Breakdown</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Total: {formatCurrency(total / 100)} · {entries.length} categories
          </p>
        </div>
      </button>

      {expanded && (
        <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2">
          {/* Bar chart */}
          <ResponsiveContainer width="100%" height={200}>
            <BarChart
              data={data}
              layout="vertical"
              margin={{ top: 0, right: 8, left: 8, bottom: 0 }}
            >
              <XAxis
                type="number"
                {...axisStyle}
                tickFormatter={(v: number) =>
                  `₺${v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`
                }
              />
              <YAxis
                type="category"
                dataKey="name"
                {...axisStyle}
                width={80}
                tick={{ fontSize: 10, fill: "oklch(0.52 0.012 255)" }}
              />
              <Tooltip
                {...tooltipStyle}
                formatter={(v: number) => [formatCurrency(v), "Amount"]}
              />
              <Bar dataKey="value" radius={[0, 3, 3, 0]} maxBarSize={14}>
                {data.map((d, i) => (
                  <Cell key={i} fill={d.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>

          {/* Row breakdown */}
          <div className="space-y-2">
            {data.map((item) => (
              <div key={item.name} className="flex items-center gap-3">
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ background: item.color }}
                  aria-hidden="true"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs text-muted-foreground">{item.name}</span>
                    <span className="shrink-0 tabular-nums text-xs font-medium">
                      {formatCurrency(item.value)}
                    </span>
                  </div>
                  <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${item.pct}%`,
                        background: item.color,
                      }}
                    />
                  </div>
                </div>
                <span className="w-10 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                  {item.pct.toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── P&L statement table ───────────────────────────────────────────────────────

interface RowProps {
  label?: string;
  value?: number | null;
  indent?: boolean;
  bold?: boolean;
  positive?: boolean;
  isPercent?: boolean;
  separator?: boolean;
}

function PnLRow({ label, value, indent, bold, positive, isPercent, separator }: RowProps) {
  if (separator) {
    return (
      <tr>
        <td colSpan={3} className="px-4 py-1">
          <div className="border-t border-border/50" />
        </td>
      </tr>
    );
  }

  const displayValue =
    value == null ? "—" : isPercent ? formatPercent(value) : formatCurrency(value);

  const valueColor =
    positive === undefined
      ? "text-foreground"
      : positive
      ? "text-emerald-400"
      : "text-destructive";

  return (
    <tr className="transition-colors hover:bg-muted/10">
      <td
        className={cn(
          "py-2 text-sm",
          indent ? "pl-8 pr-4" : "px-4",
          bold ? "font-semibold" : "font-normal text-muted-foreground"
        )}
      >
        {label}
      </td>
      <td className="w-8 px-2 py-2 text-center">
        {value != null && value !== 0 && (
          value > 0
            ? <TrendingUp className="h-3 w-3 text-emerald-400/60 inline" aria-hidden="true" />
            : <TrendingDown className="h-3 w-3 text-destructive/60 inline" aria-hidden="true" />
        )}
      </td>
      <td
        className={cn(
          "px-4 py-2 text-right tabular-nums text-sm",
          bold ? "font-semibold" : "font-normal",
          valueColor
        )}
      >
        {displayValue}
      </td>
    </tr>
  );
}

function PnLStatement({ pnl }: { pnl: PnLData }) {
  const opexEntries = Object.entries(pnl.opex).filter(([, v]) => v != null && v !== 0);
  const totalOpex = opexEntries.reduce((s, [, v]) => s + (v ?? 0), 0);

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">Profit & Loss Statement</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">Full income statement breakdown</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full" aria-label="P&L Statement">
          <thead>
            <tr className="border-b border-border">
              <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">
                Line Item
              </th>
              <th className="w-8" />
              <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">
                Amount
              </th>
            </tr>
          </thead>
          <tbody>
            <PnLRow label="Revenue" value={pnl.revenue} bold positive={pnl.revenue >= 0} />
            <PnLRow label="Cost of Goods Sold (COGS)" value={-pnl.cogs} indent positive={pnl.cogs === 0} />
            <PnLRow separator />
            <PnLRow label="Gross Profit" value={pnl.gross_profit} bold positive={pnl.gross_profit >= 0} />
            <PnLRow label="Gross Margin" value={pnl.gross_margin} indent isPercent positive={pnl.gross_margin >= 0} />
            <PnLRow separator />

            <tr>
              <td className="px-4 pt-3 pb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Operating Expenses
              </td>
              <td /><td />
            </tr>
            {opexEntries.map(([key, val]) => (
              <PnLRow
                key={key}
                label={key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                value={-(val ?? 0)}
                indent
              />
            ))}
            <PnLRow label="Total OpEx" value={-totalOpex} bold positive={totalOpex === 0} />
            <PnLRow separator />

            <PnLRow label="EBITDA" value={pnl.ebitda} bold positive={pnl.ebitda >= 0} />
            <PnLRow label="EBITDA Margin" value={pnl.ebitda_margin} indent isPercent positive={pnl.ebitda_margin >= 0} />
            <PnLRow separator />

            <PnLRow label="Net Income" value={pnl.net_income} bold positive={pnl.net_income >= 0} />
            <PnLRow label="Net Margin" value={pnl.net_margin} indent isPercent positive={pnl.net_margin >= 0} />
          </tbody>
        </table>
      </div>

      {pnl.narrative && (
        <div className="border-t border-border/50 px-4 py-3">
          <p className="mb-1 text-xs font-medium text-primary">CFO Commentary</p>
          <p className="text-sm leading-relaxed text-muted-foreground max-w-prose">
            {pnl.narrative}
          </p>
        </div>
      )}
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
      <h2 className="text-base font-semibold">No P&L data</h2>
      <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
        Upload a financial document and run an analysis to see the P&L statement.
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

export default function PnLPage() {
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
              <div className="mt-2 h-5 w-28 animate-pulse rounded bg-muted" />
            </div>
          ))}
        </div>
        <div className="h-72 animate-pulse rounded-lg bg-muted" />
        <div className="h-48 animate-pulse rounded-lg bg-muted" />
      </div>
    );
  }

  const pnl = dashboard!.pnl;

  return (
    <div className="space-y-4 p-5">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">P&amp;L Statement</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Profit &amp; loss breakdown with operating expense detail
        </p>
      </div>

      <KPIStrip pnl={pnl} />
      <WaterfallChart pnl={pnl} />
      <OpExDrillDown pnl={pnl} />
      <PnLStatement pnl={pnl} />
      <BenchmarkPanel jobId={jobId} pnl={pnl} />
    </div>
  );
}

// ── Benchmark Panel ───────────────────────────────────────────────────────────

interface BenchmarkMetric {
  benchmark: { metric: string; sector: string; p25: number; p50: number; p75: number };
  company_value: number;
  percentile_position: "bottom_25" | "p25_p50" | "p50_p75" | "top_25";
  vs_median_pct: number;
  interpretation: string;
  recommendation: string;
}

interface BenchmarkData {
  sector: string;
  metrics: Record<string, BenchmarkMetric>;
  overall_score: number;
  overall_label: string;
}

const SECTOR_LABELS: Record<string, string> = {
  default:       "Genel Ortalama",
  retail:        "Perakende",
  manufacturing: "Üretim / İmalat",
  technology:    "Teknoloji / Yazılım",
  construction:  "İnşaat / Gayrimenkul",
  services:      "Hizmet",
  food_beverage: "Yiyecek-İçecek",
  logistics:     "Lojistik",
};

const METRIC_LABELS: Record<string, string> = {
  gross_margin:    "Brüt Kâr Marjı",
  net_margin:      "Net Kâr Marjı",
  ebitda_margin:   "FAVÖK Marjı",
  opex_to_revenue: "Gider/Ciro Oranı",
};

function percentileColor(pos: string): { bar: string; badge: string; text: string } {
  switch (pos) {
    case "top_25":   return { bar: "bg-emerald-500", badge: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30", text: "text-emerald-400" };
    case "p50_p75":  return { bar: "bg-blue-500",    badge: "bg-blue-500/15 text-blue-400 border-blue-500/30",         text: "text-blue-400" };
    case "p25_p50":  return { bar: "bg-amber-500",   badge: "bg-amber-500/15 text-amber-400 border-amber-500/30",     text: "text-amber-400" };
    default:         return { bar: "bg-red-500",     badge: "bg-red-500/15 text-red-400 border-red-500/30",           text: "text-red-400" };
  }
}

function percentileLabel(pos: string): string {
  switch (pos) {
    case "top_25":  return "İlk %25";
    case "p50_p75": return "%50–75";
    case "p25_p50": return "%25–50";
    default:        return "Alt %25";
  }
}

function BenchmarkMetricRow({ metricKey, data }: { metricKey: string; data: BenchmarkMetric }) {
  const [expanded, setExpanded] = useState(false);
  const colors = percentileColor(data.percentile_position);
  const label = METRIC_LABELS[metricKey] ?? metricKey;
  const companyPct = (data.company_value * 100).toFixed(1);
  const medianPct  = (data.benchmark.p50 * 100).toFixed(1);
  const delta      = data.vs_median_pct;

  // Position on the bar: 0..1 where p25=0.25, p75=0.75
  const range = data.benchmark.p75 - data.benchmark.p25;
  const companyPos = range > 0
    ? Math.min(1, Math.max(0, (data.company_value - data.benchmark.p25) / range))
    : 0.5;

  return (
    <div className="border-b border-border last:border-0">
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-muted/30 transition-state"
        onClick={() => setExpanded((v) => !v)}
      >
        {/* Metric name */}
        <div className="w-40 shrink-0">
          <p className="text-sm font-medium">{label}</p>
        </div>

        {/* Company vs benchmark bar */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between text-[10px] text-muted-foreground mb-1">
            <span>P25: {(data.benchmark.p25 * 100).toFixed(0)}%</span>
            <span>Medyan: {medianPct}%</span>
            <span>P75: {(data.benchmark.p75 * 100).toFixed(0)}%</span>
          </div>
          <div className="relative h-2 w-full rounded-full bg-muted/40">
            {/* P25–P75 range bar */}
            <div className="absolute inset-y-0 left-0 right-0 rounded-full overflow-hidden">
              <div className="absolute h-full bg-muted/60 rounded-full"
                style={{
                  left: "25%",
                  width: "50%",
                }}
              />
            </div>
            {/* Median marker */}
            <div className="absolute top-1/2 -translate-y-1/2 w-0.5 h-3.5 bg-muted-foreground/40 rounded-full"
              style={{ left: "50%" }}
            />
            {/* Company marker */}
            <div
              className={cn("absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full ring-2 ring-background shadow-sm", colors.bar)}
              style={{ left: `calc(${companyPos * 100}% - 5px)` }}
              title={`${label}: ${companyPct}%`}
            />
          </div>
        </div>

        {/* Company value */}
        <div className="w-20 text-right shrink-0">
          <p className={cn("text-sm font-bold tabular-nums", colors.text)}>{companyPct}%</p>
          <p className={cn("text-[10px]", delta >= 0 ? "text-emerald-400" : "text-red-400")}>
            {delta >= 0 ? "+" : ""}{delta.toFixed(1)}% vs medyan
          </p>
        </div>

        {/* Badge */}
        <span className={cn("shrink-0 rounded border px-2 py-0.5 text-[10px] font-semibold", colors.badge)}>
          {percentileLabel(data.percentile_position)}
        </span>

        {/* Expand */}
        {expanded
          ? <ChevronUp className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          : <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        }
      </div>

      {expanded && (
        <div className="border-t border-border/50 bg-muted/10 px-4 py-3 space-y-1.5 animate-slide-down">
          <p className="text-xs text-foreground">{data.interpretation}</p>
          {data.recommendation && (
            <p className="text-xs text-muted-foreground">
              <span className="font-medium text-primary">→ Öneri:</span> {data.recommendation}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function BenchmarkPanel({ jobId, pnl }: { jobId: string | null; pnl: PnLData }) {
  const [sector, setSector] = useState("default");
  const [open, setOpen] = useState(false);

  const { data, isLoading, refetch, isFetching } = useQuery<BenchmarkData>({
    queryKey: ["benchmark", jobId, sector],
    queryFn: async () => {
      const res = await apiClient.get<{ data: BenchmarkData }>(
        `/benchmark/${jobId}?sector=${sector}`
      );
      return res.data.data;
    },
    enabled: !!jobId && open,
    staleTime: 5 * 60_000,
    retry: 1,
  });

  const overallColors = data
    ? data.overall_score >= 3
      ? { badge: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30", text: "text-emerald-400" }
      : data.overall_score >= 2
      ? { badge: "bg-amber-500/15 text-amber-400 border-amber-500/30", text: "text-amber-400" }
      : { badge: "bg-red-500/15 text-red-400 border-red-500/30", text: "text-red-400" }
    : null;

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      {/* Header — always visible, click to expand */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3.5 hover:bg-muted/30 transition-state text-left"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2.5">
          <BarChart3 className="h-4 w-4 text-primary shrink-0" aria-hidden="true" />
          <div>
            <p className="text-sm font-semibold">Sektör Karşılaştırması</p>
            <p className="text-[11px] text-muted-foreground">
              TCMB/BDDK verilerine göre sektör ortalaması ile kıyasla
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {data?.overall_label && overallColors && (
            <span className={cn("rounded border px-2 py-0.5 text-[10px] font-semibold", overallColors.badge)}>
              {data.overall_label}
            </span>
          )}
          {open
            ? <ChevronUp className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            : <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          }
        </div>
      </button>

      {/* Expanded content */}
      {open && (
        <div className="border-t border-border animate-slide-down">
          {/* Sector selector */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-border bg-muted/10">
            <label htmlFor="sector-select" className="text-xs font-medium text-muted-foreground whitespace-nowrap">
              Sektör:
            </label>
            <div className="relative">
              <select
                id="sector-select"
                value={sector}
                onChange={(e) => setSector(e.target.value)}
                className="appearance-none rounded border border-input bg-background pl-3 pr-8 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring transition-state"
              >
                {Object.entries(SECTOR_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" aria-hidden="true" />
            </div>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="ml-auto flex items-center gap-1.5 rounded border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted transition-state disabled:opacity-50"
            >
              <RefreshCw className={cn("h-3 w-3", isFetching && "animate-spin")} aria-hidden="true" />
              {isFetching ? "Yükleniyor…" : "Yenile"}
            </button>
          </div>

          {/* Loading */}
          {isLoading && (
            <div className="flex items-center gap-2 px-4 py-6 text-sm text-muted-foreground">
              <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
              Benchmark verileri yükleniyor…
            </div>
          )}

          {/* Metrics */}
          {data && (
            <div>
              {Object.entries(data.metrics).map(([key, metric]) => (
                <BenchmarkMetricRow key={key} metricKey={key} data={metric} />
              ))}

              {/* Footer */}
              <div className="px-4 py-2.5 bg-muted/10 border-t border-border">
                <p className="text-[10px] text-muted-foreground">
                  Kaynak: TCMB/BDDK Sektör İstatistikleri 2023-2024 ·{" "}
                  {SECTOR_LABELS[data.sector] ?? data.sector}
                </p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
