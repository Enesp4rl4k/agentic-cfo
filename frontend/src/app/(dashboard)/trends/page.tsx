"use client";

import { useSearchParams } from "next/navigation";
import { Upload, AlertCircle, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { useDashboard } from "@/hooks/useCFO";
import { formatCurrency, cn } from "@/lib/utils";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Legend,
} from "recharts";

// ── Types ─────────────────────────────────────────────────────────────────────

interface MoM {
  current_month: string;
  previous_month: string;
  revenue_change_pct: number | null;
  expenses_change_pct: number | null;
  net_change_pct: number | null;
  revenue_current: number;
  revenue_previous: number;
  net_current: number;
  net_previous: number;
}

interface YoY {
  current_month: string;
  year_ago_month: string;
  revenue_yoy_pct: number | null;
  expenses_yoy_pct: number | null;
  net_yoy_pct: number | null;
}

interface KpiTrends {
  revenue_trend: string;
  expense_trend: string;
  net_trend: string;
}

interface MultiPeriodData {
  months_available: number;
  month_range: string;
  mom: MoM | null;
  yoy: YoY | null;
  kpi_trends: KpiTrends;
  trend_direction: string;
  monthly_summary: Record<string, { revenue: number; expenses: number; net: number }>;
  narrative: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const tooltipStyle = {
  contentStyle: {
    background: "oklch(0.17 0.022 255)",
    border: "1px solid oklch(0.27 0.018 255)",
    borderRadius: "6px",
    fontSize: "12px",
    color: "oklch(0.92 0.008 255)",
    padding: "8px 12px",
  },
};

const axisStyle = {
  tick: { fontSize: 11, fill: "oklch(0.52 0.012 255)" },
  axisLine: { stroke: "oklch(0.27 0.018 255)" },
  tickLine: false as const,
};

function TrendBadge({ trend }: { trend: string }) {
  const config = {
    improving: { label: "İyileşiyor", cls: "bg-emerald-950/30 text-emerald-400 ring-emerald-500/20", icon: TrendingUp },
    declining: { label: "Düşüyor", cls: "bg-destructive/10 text-destructive ring-destructive/20", icon: TrendingDown },
    stable: { label: "Stabil", cls: "bg-muted text-muted-foreground ring-border", icon: Minus },
    insufficient_data: { label: "Yetersiz veri", cls: "bg-muted text-muted-foreground ring-border", icon: Minus },
  };
  const cfg = config[trend as keyof typeof config] ?? config.stable;
  const Icon = cfg.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset", cfg.cls)}>
      <Icon className="h-3 w-3" aria-hidden="true" />
      {cfg.label}
    </span>
  );
}

function PctBadge({ pct }: { pct: number | null }) {
  if (pct == null) return <span className="text-muted-foreground">—</span>;
  const positive = pct >= 0;
  return (
    <span className={cn("tabular-nums font-medium", positive ? "text-emerald-400" : "text-destructive")}>
      {positive ? "+" : ""}{pct.toFixed(1)}%
    </span>
  );
}

// ── MoM / YoY comparison cards ────────────────────────────────────────────────

function PeriodComparisonCards({ data }: { data: MultiPeriodData }) {
  const { mom, yoy } = data;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {/* MoM */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="mb-3 text-sm font-medium">Aylık Karşılaştırma (MoM)</h3>
        {mom ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Gelir</span>
              <PctBadge pct={mom.revenue_change_pct} />
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Giderler</span>
              <PctBadge pct={mom.expenses_change_pct ? -mom.expenses_change_pct : null} />
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Net Nakit Akışı</span>
              <PctBadge pct={mom.net_change_pct} />
            </div>
            <div className="mt-3 border-t border-border/50 pt-3 text-xs text-muted-foreground">
              {mom.previous_month} → {mom.current_month}
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Karşılaştırma için en az 2 ay veri gerekli.</p>
        )}
      </div>

      {/* YoY */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="mb-3 text-sm font-medium">Yıllık Karşılaştırma (YoY)</h3>
        {yoy ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Gelir</span>
              <PctBadge pct={yoy.revenue_yoy_pct} />
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Giderler</span>
              <PctBadge pct={yoy.expenses_yoy_pct ? -yoy.expenses_yoy_pct : null} />
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Net Nakit Akışı</span>
              <PctBadge pct={yoy.net_yoy_pct} />
            </div>
            <div className="mt-3 border-t border-border/50 pt-3 text-xs text-muted-foreground">
              {yoy.year_ago_month} → {yoy.current_month}
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">YoY karşılaştırma için 12+ ay veri gerekli.</p>
        )}
      </div>
    </div>
  );
}

// ── Trend chart ───────────────────────────────────────────────────────────────

function TrendChart({ monthly }: { monthly: MultiPeriodData["monthly_summary"] }) {
  const data = Object.entries(monthly)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, v]) => ({
      month: month.slice(5),  // MM
      revenue: v.revenue / 100,
      expenses: v.expenses / 100,
      net: v.net / 100,
    }));

  if (data.length < 2) {
    return (
      <div className="flex h-[220px] items-center justify-center text-xs text-muted-foreground">
        Trend grafiği için en az 2 aylık veri gerekli.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.22 0.018 255)" vertical={false} />
        <XAxis dataKey="month" {...axisStyle} />
        <YAxis
          {...axisStyle}
          tickFormatter={(v: number) => `$${Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`}
        />
        <Tooltip
          {...tooltipStyle}
          formatter={(v: number, name: string) => [formatCurrency(v), name]}
        />
        <Legend wrapperStyle={{ fontSize: "11px", color: "oklch(0.52 0.012 255)" }} />
        <ReferenceLine y={0} stroke="oklch(0.35 0.018 255)" strokeWidth={1} />
        <Line type="monotone" dataKey="revenue" name="Gelir" stroke="oklch(0.58 0.18 145)" strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey="expenses" name="Gider" stroke="oklch(0.58 0.22 25)" strokeWidth={1.5} dot={false} strokeDasharray="4 2" />
        <Line type="monotone" dataKey="net" name="Net" stroke="oklch(0.60 0.19 255)" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── KPI trend strip ───────────────────────────────────────────────────────────

function KpiTrendStrip({ trends, direction, months }: { trends: KpiTrends; direction: string; months: number }) {
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
      <div className="bg-card px-4 py-4">
        <p className="text-xs text-muted-foreground">Genel Yön</p>
        <div className="mt-1.5"><TrendBadge trend={direction} /></div>
        <p className="mt-1 text-xs text-muted-foreground">{months} ay veri</p>
      </div>
      <div className="bg-card px-4 py-4">
        <p className="text-xs text-muted-foreground">Gelir Trendi</p>
        <div className="mt-1.5"><TrendBadge trend={trends.revenue_trend} /></div>
      </div>
      <div className="bg-card px-4 py-4">
        <p className="text-xs text-muted-foreground">Gider Trendi</p>
        <div className="mt-1.5">
          <TrendBadge trend={trends.expense_trend === "improving" ? "declining" : trends.expense_trend === "declining" ? "improving" : trends.expense_trend} />
        </div>
        <p className="mt-1 text-xs text-muted-foreground opacity-60">↑ artış = kötü</p>
      </div>
      <div className="bg-card px-4 py-4">
        <p className="text-xs text-muted-foreground">Net Trend</p>
        <div className="mt-1.5"><TrendBadge trend={trends.net_trend} /></div>
      </div>
    </div>
  );
}

// ── Monthly data table ────────────────────────────────────────────────────────

function MonthlyTable({ monthly }: { monthly: MultiPeriodData["monthly_summary"] }) {
  const rows = Object.entries(monthly).sort(([a], [b]) => b.localeCompare(a));
  if (!rows.length) return null;

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">Aylık Özet Tablo</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" role="table">
          <thead>
            <tr className="border-b border-border">
              <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Ay</th>
              <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">Gelir</th>
              <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">Gider</th>
              <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">Net</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([month, v]) => {
              const netPos = v.net >= 0;
              return (
                <tr key={month} className="border-b border-border/40 last:border-0 hover:bg-muted/10 transition-colors">
                  <td className="px-4 py-2.5 text-xs tabular-nums text-muted-foreground">{month}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-sm text-emerald-400">
                    {formatCurrency(v.revenue / 100)}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-sm text-destructive">
                    {formatCurrency(v.expenses / 100)}
                  </td>
                  <td className={cn("px-4 py-2.5 text-right tabular-nums text-sm font-medium", netPos ? "text-emerald-400" : "text-destructive")}>
                    {netPos ? "+" : "−"}{formatCurrency(Math.abs(v.net / 100))}
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

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center px-6">
      <div className="mb-4 rounded-full bg-muted p-4">
        <Upload className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold">Trend verisi yok</h2>
      <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
        En az 2 aylık veri içeren bir belge yükleyin.
      </p>
      <a href="/upload" className={cn(
        "mt-5 inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground",
        "transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      )}>
        Belge yükle
      </a>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function TrendsPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const { data: dashboard, isLoading } = useDashboard(jobId);

  if (!jobId || (!isLoading && !dashboard)) return <EmptyState />;

  if (isLoading) {
    return (
      <div className="space-y-4 p-5">
        <div className="h-6 w-40 animate-pulse rounded bg-muted" />
        <div className="grid grid-cols-2 gap-px rounded-lg border border-border bg-border sm:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-card px-4 py-4">
              <div className="h-3 w-16 animate-pulse rounded bg-muted" />
              <div className="mt-2 h-5 w-20 animate-pulse rounded bg-muted" />
            </div>
          ))}
        </div>
        <div className="h-60 animate-pulse rounded-lg bg-muted" />
      </div>
    );
  }

  const multiPeriod = (dashboard as any)?.multi_period as MultiPeriodData | null | undefined;

  if (!multiPeriod) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center px-6">
        <div className="mb-4 rounded-full bg-muted p-4">
          <AlertCircle className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
        </div>
        <h2 className="text-base font-semibold">Dönem analizi bulunamadı</h2>
        <p className="mt-1.5 max-w-xs text-sm text-muted-foreground">
          Bu analiz için yeterli dönem verisi yok. En az 2 ay gerekli.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-5">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Dönem Analizi & Trendler</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          {multiPeriod.month_range} · {multiPeriod.months_available} ay veri
        </p>
      </div>

      <KpiTrendStrip
        trends={multiPeriod.kpi_trends}
        direction={multiPeriod.trend_direction}
        months={multiPeriod.months_available}
      />

      {multiPeriod.narrative && (
        <div className="rounded-lg border border-border bg-card px-4 py-3.5">
          <p className="mb-1 text-xs font-medium text-primary">CFO Analizi</p>
          <p className="text-sm leading-relaxed text-muted-foreground max-w-prose">{multiPeriod.narrative}</p>
        </div>
      )}

      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="mb-0.5 text-sm font-medium">Aylık Trend Grafiği</h2>
        <p className="mb-4 text-xs text-muted-foreground">Gelir, gider ve net nakit akışı trendi</p>
        <TrendChart monthly={multiPeriod.monthly_summary} />
      </div>

      <PeriodComparisonCards data={multiPeriod} />

      <MonthlyTable monthly={multiPeriod.monthly_summary} />
    </div>
  );
}
