"use client";

/**
 * BenchmarkComparisonChart — Şirket vs Sektör Karşılaştırma
 *
 * Şirket değerini sektör P25/P50/P75 ile grouped bar chart'ta gösterir.
 * Her metrik için:
 *   - Şirket değeri (primary bar)
 *   - Sektör medyanı P50 (reference line)
 * Renk kodlaması: percentile'a göre emerald/yellow/orange/red
 */

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Cell,
  Legend,
} from "recharts";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────────

interface BenchmarkMetric {
  metric: string;
  company_value: number | null;
  benchmark_p25: number | null;
  benchmark_p50: number | null;
  benchmark_p75: number | null;
  percentile: number | null;
  unit: string;
  verdict: string;
  higher_is_better: boolean;
}

interface BenchmarkComparisonChartProps {
  items: BenchmarkMetric[];
  sector: string;
  companyName: string;
  className?: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function getBarColor(pct: number | null, higherIsBetter: boolean): string {
  if (pct === null) return "#71717a";
  const score = higherIsBetter ? pct : 100 - pct;
  if (score >= 75) return "#10b981"; // emerald
  if (score >= 50) return "#eab308"; // yellow
  if (score >= 25) return "#f97316"; // orange
  return "#ef4444";                   // red
}

function getScoreLabel(pct: number | null, higherIsBetter: boolean) {
  if (pct === null) return { label: "Veri yok", icon: Minus, color: "text-muted-foreground" };
  const score = higherIsBetter ? pct : 100 - pct;
  if (score >= 75) return { label: "Sektörde üst çeyrek", icon: TrendingUp, color: "text-emerald-400" };
  if (score >= 50) return { label: "Sektör ortalaması üstü", icon: TrendingUp, color: "text-yellow-400" };
  if (score >= 25) return { label: "Sektör ortalaması altı", icon: TrendingDown, color: "text-orange-400" };
  return { label: "Alt çeyrekte", icon: TrendingDown, color: "text-red-400" };
}

function formatValue(value: number | null, unit: string): string {
  if (value === null) return "—";
  if (unit === "%") return `${(value * 100).toFixed(1)}%`;
  if (unit === "x") return `${value.toFixed(2)}x`;
  if (unit === "TL" || unit === "₺") {
    if (Math.abs(value) >= 1_000_000) return `₺${(value / 1_000_000).toFixed(1)}M`;
    if (Math.abs(value) >= 1_000) return `₺${(value / 1_000).toFixed(0)}K`;
    return `₺${value.toFixed(0)}`;
  }
  return value.toFixed(1);
}

// ── Custom Tooltip ─────────────────────────────────────────────────────────────

function CustomTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; payload: ChartDataPoint }>;
  label?: string;
}) {
  if (!active || !payload || !payload.length) return null;
  const data = payload[0]?.payload;
  if (!data) return null;

  return (
    <div className="bg-card border border-border rounded-lg p-3 shadow-lg text-sm min-w-[200px]">
      <p className="font-semibold text-foreground mb-2">{label}</p>
      <div className="space-y-1">
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Şirket:</span>
          <span className="font-mono font-semibold text-primary">
            {formatValue(data.companyRaw, data.unit)}
          </span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Sektör Medyanı:</span>
          <span className="font-mono">{formatValue(data.p50Raw, data.unit)}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">P25 / P75:</span>
          <span className="font-mono text-xs">
            {formatValue(data.p25Raw, data.unit)} / {formatValue(data.p75Raw, data.unit)}
          </span>
        </div>
        {data.percentile !== null && (
          <div className="flex justify-between gap-4 border-t border-border pt-1 mt-1">
            <span className="text-muted-foreground">Yüzdelik:</span>
            <span className="font-mono font-semibold">%{data.percentile.toFixed(0)}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Chart Data Prep ────────────────────────────────────────────────────────────

interface ChartDataPoint {
  name: string;
  shortName: string;
  company: number;
  p50: number;
  companyRaw: number | null;
  p25Raw: number | null;
  p50Raw: number | null;
  p75Raw: number | null;
  percentile: number | null;
  unit: string;
  color: string;
  higherIsBetter: boolean;
}

function buildChartData(items: BenchmarkMetric[]): ChartDataPoint[] {
  return items
    .filter((item) => item.company_value !== null && item.benchmark_p50 !== null)
    .slice(0, 8) // max 8 metrik okunabilirlik için
    .map((item) => {
      // Normalize to 0-100 scale for visual comparison
      const allValues = [
        item.company_value,
        item.benchmark_p25,
        item.benchmark_p50,
        item.benchmark_p75,
      ].filter((v): v is number => v !== null);

      const minVal = Math.min(...allValues);
      const maxVal = Math.max(...allValues);
      const range = maxVal - minVal || 1;

      const normalize = (v: number | null): number => {
        if (v === null) return 0;
        return Math.max(0, Math.min(100, ((v - minVal) / range) * 100));
      };

      // Short metric name for x-axis
      const shortName = item.metric
        .replace(/Marjı|Oranı|Süresi|Katsayısı/g, "")
        .trim()
        .slice(0, 16);

      return {
        name: item.metric,
        shortName,
        company: normalize(item.company_value),
        p50: normalize(item.benchmark_p50),
        companyRaw: item.company_value,
        p25Raw: item.benchmark_p25,
        p50Raw: item.benchmark_p50,
        p75Raw: item.benchmark_p75,
        percentile: item.percentile,
        unit: item.unit,
        color: getBarColor(item.percentile, item.higher_is_better),
        higherIsBetter: item.higher_is_better,
      };
    });
}

// ── Summary Score Cards ────────────────────────────────────────────────────────

function SummaryScoreCard({ item }: { item: BenchmarkMetric }) {
  const { label, icon: Icon, color } = getScoreLabel(item.percentile, item.higher_is_better);

  return (
    <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/30 hover:bg-muted/50 transition-colors">
      <div
        className="w-1.5 h-10 rounded-full shrink-0"
        style={{ backgroundColor: getBarColor(item.percentile, item.higher_is_better) }}
      />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium truncate">{item.metric}</p>
        <p className={cn("text-[11px] flex items-center gap-1 mt-0.5", color)}>
          <Icon className="h-3 w-3 shrink-0" />
          {label}
        </p>
      </div>
      <div className="text-right shrink-0">
        <p className="text-sm font-mono font-semibold text-primary">
          {formatValue(item.company_value, item.unit)}
        </p>
        <p className="text-[10px] text-muted-foreground">
          Med: {formatValue(item.benchmark_p50, item.unit)}
        </p>
      </div>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────────

export function BenchmarkComparisonChart({
  items,
  sector,
  companyName,
  className,
}: BenchmarkComparisonChartProps) {
  const chartData = buildChartData(items);

  // Overall percentile score
  const validPercentiles = items
    .filter((i) => i.percentile !== null)
    .map((i) => (i.higher_is_better ? i.percentile! : 100 - i.percentile!));
  const avgScore =
    validPercentiles.length > 0
      ? validPercentiles.reduce((a, b) => a + b, 0) / validPercentiles.length
      : null;

  const overallColor =
    avgScore === null
      ? "text-muted-foreground"
      : avgScore >= 75
      ? "text-emerald-400"
      : avgScore >= 50
      ? "text-yellow-400"
      : avgScore >= 25
      ? "text-orange-400"
      : "text-red-400";

  return (
    <div className={cn("space-y-4", className)}>
      {/* Header with overall score */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold">Sektör Karşılaştırması</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {sector} sektörü • {items.length} metrik
          </p>
        </div>
        {avgScore !== null && (
          <div className="text-right">
            <p className={cn("text-2xl font-bold tabular-nums", overallColor)}>
              %{avgScore.toFixed(0)}
            </p>
            <p className="text-[10px] text-muted-foreground">genel skor</p>
          </div>
        )}
      </div>

      {/* Bar Chart */}
      {chartData.length > 0 && (
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={chartData}
              margin={{ top: 4, right: 4, left: -20, bottom: 4 }}
              barCategoryGap="20%"
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="hsl(var(--border))"
                vertical={false}
              />
              <XAxis
                dataKey="shortName"
                tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                domain={[0, 100]}
                tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => `${v}`}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend
                wrapperStyle={{ fontSize: 10 }}
                formatter={(value) =>
                  value === "company" ? companyName : "Sektör Medyanı"
                }
              />
              {/* Sektör medyanı reference bars */}
              <Bar dataKey="p50" name="p50" fill="hsl(var(--muted))" radius={[2, 2, 0, 0]} />
              {/* Şirket değeri — colored by performance */}
              <Bar dataKey="company" name="company" radius={[2, 2, 0, 0]}>
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Bar>
              {/* P50 median line */}
              <ReferenceLine y={50} stroke="hsl(var(--muted-foreground))" strokeDasharray="4 2" strokeWidth={1} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Metric Score Cards */}
      <div className="space-y-2">
        {items.slice(0, 6).map((item) => (
          <SummaryScoreCard key={item.metric} item={item} />
        ))}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 text-[10px] text-muted-foreground pt-1 border-t border-border">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-500" />
          Üst çeyrek (P75+)
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-yellow-500" />
          Ortalama üstü
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-orange-500" />
          Ortalama altı
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-red-500" />
          Alt çeyrek
        </span>
      </div>
    </div>
  );
}
