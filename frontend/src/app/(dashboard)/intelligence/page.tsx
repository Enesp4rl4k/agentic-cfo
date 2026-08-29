"use client";

export const dynamic = "force-dynamic";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  AlertTriangle, TrendingUp, Calendar, Zap, RefreshCw, Clock,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";
import { useActiveCFOJob } from "@/hooks/useCompanyContext";
import { apiClient } from "@/lib/api/client";
import { formatCurrency, cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { BaselineSourceBadge } from "@/components/ui/baseline-source-badge";
import { SemanticMetricsPanel } from "@/components/ui/semantic-metrics-panel";
import {
  getSemanticMe,
  getLiveDataStatus,
  type LiveDataStatus,
  type MetricPoint,
} from "@/lib/api/semantic";

// ── Type definitions ──────────────────────────────────────────────────────────

interface KRIMetric {
  metric: string;
  value: number;
  unit: string;
  threshold: number;
  status: "healthy" | "warning" | "critical";
  trend: number; // % change
}

interface KRIHistory {
  date: string;
  cash_runway_months: number;
  burn_rate_daily: number;
  revenue_daily: number;
  cash_position: number;
  margin_percent: number;
}

interface KRIData {
  current_metrics: KRIMetric[];
  history: KRIHistory[];
  critical_count: number;
  warning_count: number;
  summary: string;
  recommendations: string[];
}

// ── KRI Status Badge ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: "healthy" | "warning" | "critical" }) {
  const colors = {
    healthy: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    warning: "bg-amber-500/15 text-amber-400 border-amber-500/30",
    critical: "bg-red-500/15 text-red-400 border-red-500/30",
  };
  const icons = {
    healthy: "✓",
    warning: "⚠",
    critical: "!",
  };
  return (
    <span className={cn("inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium", colors[status])}>
      {icons[status]}
      {status === "healthy" ? "Sağlıklı" : status === "warning" ? "Uyarı" : "Kritik"}
    </span>
  );
}

// ── KRI Metric Card ───────────────────────────────────────────────────────────

function KRICard({ metric }: { metric: KRIMetric }) {
  const trendColor = metric.trend >= 0 ? "text-emerald-400" : "text-red-400";
  const trendIcon = metric.trend >= 0 ? "↑" : "↓";

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-xs text-muted-foreground">{metric.metric}</p>
          <p className="text-lg font-semibold tabular mt-1">
            {metric.value.toFixed(1)}{metric.unit}
          </p>
        </div>
        <StatusBadge status={metric.status} />
      </div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">Eşik: {metric.threshold}{metric.unit}</span>
        <span className={cn("font-medium", trendColor)}>
          {trendIcon} {Math.abs(metric.trend).toFixed(1)}%
        </span>
      </div>
    </div>
  );
}

// ── KRI History Chart ─────────────────────────────────────────────────────────

function KRIHistoryChart({ data }: { data: KRIHistory[] }) {
  if (!data || data.length === 0) {
    return (
      <Card className="flex items-center justify-center py-20 text-center">
        <p className="text-sm text-muted-foreground">KRI geçmiş verisi yok</p>
      </Card>
    );
  }

  const chartData = data.map((d) => ({
    date: new Date(d.date).toLocaleDateString("tr-TR", { month: "short", day: "numeric" }),
    runway: d.cash_runway_months,
    margin: d.margin_percent * 100,
  }));

  return (
    <Card className="p-4 space-y-3">
      <h3 className="text-sm font-semibold">KRI Trend (Son 30 Gün)</h3>
      <ResponsiveContainer width="100%" height={250}>
        <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.1} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: "currentColor" }}
            opacity={0.6}
          />
          <YAxis
            yAxisId="left"
            tick={{ fontSize: 11 }}
            opacity={0.6}
            tickFormatter={(v: number) => `${v.toFixed(1)}ay`}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={{ fontSize: 11 }}
            opacity={0.6}
            tickFormatter={(v: number) => `${v.toFixed(0)}%`}
          />
          <Tooltip
            contentStyle={{
              background: "var(--card)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              fontSize: 12,
            }}
          />
          <Legend />
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="runway"
            name="Nakit Pisti (ay)"
            stroke="oklch(0.60 0.19 255)"
            strokeWidth={2}
            dot={false}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="margin"
            name="Marj (%)"
            stroke="oklch(0.58 0.14 145)"
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </Card>
  );
}

// ── Main Intelligence Page ────────────────────────────────────────────────────

export default function IntelligencePage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const contextJobId = useActiveCFOJob();
  const finalJobId = jobId ?? contextJobId;

  const [data, setData] = useState<KRIData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [semanticMetrics, setSemanticMetrics] = useState<MetricPoint[]>([]);
  const [semanticPeriod, setSemanticPeriod] = useState<string | undefined>();
  const [liveStatus, setLiveStatus] = useState<LiveDataStatus | null>(null);
  const [semanticLoading, setSemanticLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [semantic, live] = await Promise.all([
          getSemanticMe(),
          getLiveDataStatus().catch(() => null),
        ]);
        if (cancelled) return;
        setSemanticMetrics(semantic.snapshot?.metrics ?? []);
        setSemanticPeriod(semantic.period_key);
        setLiveStatus(live);
      } catch {
        if (!cancelled) {
          setSemanticMetrics([]);
          setLiveStatus(null);
        }
      } finally {
        if (!cancelled) setSemanticLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!finalJobId) {
      setLoading(false);
      return;
    }

    async function fetchKRI() {
      try {
        setLoading(true);
        setError(null);
        const res = await apiClient.get<{ data: KRIData }>(
          `/intelligence/${finalJobId}/kri`
        );
        setData(res.data.data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "KRI verisi yüklenemedi");
      } finally {
        setLoading(false);
      }
    }

    fetchKRI();
  }, [finalJobId]);

  const hasSemantic = semanticMetrics.length > 0;
  const baselineSource = liveStatus?.baseline_source ?? (hasSemantic ? "semantic" : "none");

  return (
    <main className="mx-auto max-w-screen-xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Zap className="h-6 w-6 text-primary" />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-bold">Proaktif KRI Dashboard</h1>
              <BaselineSourceBadge source={baselineSource} />
            </div>
            <p className="text-sm text-muted-foreground">
              Key Risk Indicators — saatlik KRI taraması ve semantic metrikler
            </p>
            {liveStatus?.golden_path_ready && (
              <p className="text-xs text-emerald-400 mt-1">
                Live sync + semantic brief ready
              </p>
            )}
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
          <RefreshCw className="h-4 w-4 mr-1" />
          Yenile
        </Button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/8 p-4">
          <AlertTriangle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
          <p className="text-sm text-destructive">{error}</p>
        </div>
      )}

      {/* Semantic metrics — available without CFO job when live sync / brief exists */}
      {hasSemantic && (
        <Card className="p-4">
          <SemanticMetricsPanel
            metrics={semanticMetrics}
            periodKey={semanticPeriod}
          />
        </Card>
      )}

      {/* Empty state */}
      {!finalJobId && !loading && !semanticLoading && !hasSemantic && (
        <Card className="flex flex-col items-center justify-center py-16 text-center">
          <Zap className="h-12 w-12 text-muted-foreground/40 mb-3" />
          <p className="font-medium">KRI Analizi Beklemede</p>
          <p className="text-sm text-muted-foreground max-w-sm mt-1">
            Finansal verisi yüklendikten veya live sync tamamlandıktan sonra
            göstergeler görüntülenecektir.
          </p>
          <Link
            href="/command-center"
            className="mt-4 text-sm text-primary hover:underline"
          >
            Command Center →
          </Link>
        </Card>
      )}

      {!finalJobId && !loading && hasSemantic && !data && (
        <Card className="p-4 border-dashed">
          <p className="text-sm text-muted-foreground">
            Semantic metrikler hazır. Tam KRI trend grafiği için CFO analizi
            tamamlanmalı —{" "}
            <Link href="/" className="text-primary hover:underline">
              CFO analizi başlat
            </Link>
            .
          </p>
        </Card>
      )}

      {/* Content */}
      {finalJobId && data && (
        <div className="space-y-6">
          {/* Summary banner */}
          <div
            className={cn(
              "rounded-lg border p-4 flex items-start gap-3",
              data.critical_count > 0
                ? "border-red-500/30 bg-red-500/8"
                : data.warning_count > 0
                  ? "border-amber-500/30 bg-amber-500/8"
                  : "border-emerald-500/30 bg-emerald-500/8"
            )}
          >
            <Clock className={cn(
              "h-5 w-5 shrink-0 mt-0.5",
              data.critical_count > 0
                ? "text-red-400"
                : data.warning_count > 0
                  ? "text-amber-400"
                  : "text-emerald-400"
            )} />
            <div className="flex-1 min-w-0">
              <p className={cn(
                "text-sm font-semibold",
                data.critical_count > 0
                  ? "text-red-400"
                  : data.warning_count > 0
                    ? "text-amber-400"
                    : "text-emerald-400"
              )}>
                {data.critical_count > 0
                  ? `Bu hafta ${data.critical_count} kritik uyarı`
                  : data.warning_count > 0
                    ? `Bu hafta ${data.warning_count} uyarı`
                    : "Tüm göstergeler sağlıklı"}
              </p>
              <p className="text-xs text-muted-foreground mt-1">{data.summary}</p>
            </div>
          </div>

          {/* Current metrics grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.current_metrics.map((m) => (
              <KRICard key={m.metric} metric={m} />
            ))}
          </div>

          {/* History chart */}
          <KRIHistoryChart data={data.history} />

          {/* Recommendations */}
          {data.recommendations.length > 0 && (
            <Card className="p-4 space-y-3 border-amber-500/30 bg-amber-500/5">
              <h3 className="text-sm font-semibold text-amber-400">Öneriler</h3>
              <ul className="space-y-1.5">
                {data.recommendations.map((rec, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-muted-foreground">
                    <span className="text-amber-400 mt-0.5 shrink-0">→</span>
                    {rec}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}

      {loading && finalJobId && (
        <Card className="flex items-center justify-center py-20">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <RefreshCw className="h-4 w-4 animate-spin" />
            KRI verisi yükleniyor…
          </div>
        </Card>
      )}
    </main>
  );
}
