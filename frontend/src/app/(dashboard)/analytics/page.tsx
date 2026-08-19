"use client";

export const dynamic = "force-dynamic";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  TrendingUp, TrendingDown, AlertCircle, BarChart3, Zap, RefreshCw,
} from "lucide-react";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import { useActiveCFOJob } from "@/hooks/useCompanyContext";
import { apiClient } from "@/lib/api/client";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { BenchmarkReport } from "@/lib/api/kernels";
import { BenchmarkComparisonChart } from "@/components/analytics/BenchmarkComparisonChart";

// ── Type definitions ──────────────────────────────────────────────────────────

interface MacroSnapshot {
  usd_try: number;
  eur_try: number;
  policy_rate_pct: number;
  inflation_pct: number;
  ppi_pct: number;
  repo_rate_pct: number;
  real_cost_of_capital: number;
  as_of: string;
}

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

interface BenchmarkData {
  company_name: string;
  sector: string;
  company_size: string;
  items: BenchmarkMetric[];
  summary: string | null;
  strengths: string[];
  weaknesses: string[];
}

// ── Macro Snapshot Card ────────────────────────────────────────────────────────

function MacroCard({ data, loading }: { data: MacroSnapshot | null; loading: boolean }) {
  if (loading) {
    return (
      <Card className="p-4 space-y-3 animate-pulse">
        <div className="h-4 w-32 bg-muted rounded" />
        <div className="grid grid-cols-3 gap-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="space-y-1">
              <div className="h-3 w-24 bg-muted rounded" />
              <div className="h-5 w-16 bg-muted rounded" />
            </div>
          ))}
        </div>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card className="p-4 text-center text-sm text-muted-foreground">
        TCMB verileri yüklenemedi
      </Card>
    );
  }

  const metrics = [
    { label: "USD/TRY", value: data.usd_try, format: (v: number) => v.toFixed(2) },
    { label: "EUR/TRY", value: data.eur_try, format: (v: number) => v.toFixed(2) },
    { label: "Politika Oranı", value: data.policy_rate_pct, format: (v: number) => `${v.toFixed(1)}%` },
    { label: "Enflasyon", value: data.inflation_pct, format: (v: number) => `${v.toFixed(1)}%` },
    { label: "UFE", value: data.ppi_pct, format: (v: number) => `${v.toFixed(1)}%` },
    { label: "Repo Oranı", value: data.repo_rate_pct, format: (v: number) => `${v.toFixed(1)}%` },
  ];

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">TCMB Makroekonomik Göstergeler</h3>
        <span className="text-xs text-muted-foreground">
          {new Date(data.as_of).toLocaleDateString("tr-TR")}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {metrics.map((m) => (
          <div key={m.label} className="space-y-1 p-2 rounded bg-muted/30">
            <p className="text-xs text-muted-foreground">{m.label}</p>
            <p className="text-sm font-semibold tabular">{m.format(m.value)}</p>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Gerçek Sermaye Maliyeti: {data.real_cost_of_capital.toFixed(1)}%
      </p>
    </Card>
  );
}

// ── Benchmark Metric Row ──────────────────────────────────────────────────────

function BenchmarkMetricRow({ item }: { item: BenchmarkMetric }) {
  const pct = item.percentile ?? 50;
  const barColor =
    item.higher_is_better
      ? pct >= 75 ? "bg-emerald-500" : pct >= 50 ? "bg-yellow-500" : pct >= 25 ? "bg-orange-500" : "bg-red-500"
      : pct <= 25 ? "bg-emerald-500" : pct <= 50 ? "bg-yellow-500" : pct <= 75 ? "bg-orange-500" : "bg-red-500";

  const fmt = (v: number | null) => {
    if (v === null) return "—";
    if (item.unit === "%") return `${(v * 100).toFixed(1)}%`;
    if (item.unit === "x") return `${v.toFixed(2)}x`;
    return v.toFixed(1);
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium truncate flex-1">{item.metric}</span>
        <span className="text-xs font-mono font-semibold shrink-0 text-primary">
          {fmt(item.company_value)}
        </span>
      </div>
      <div className="relative h-3 rounded bg-muted overflow-hidden">
        <div
          className="absolute top-0 h-full bg-muted-foreground/15"
          style={{ left: "25%", width: "50%" }}
        />
        <div className="absolute top-0 h-full w-px bg-muted-foreground/40" style={{ left: "50%" }} />
        {item.percentile !== null && (
          <div
            className={cn("absolute top-0.5 h-2 w-2 rounded-full -translate-x-1/2", barColor)}
            style={{ left: `${Math.max(4, Math.min(96, item.percentile))}%` }}
          />
        )}
      </div>
      <div className="flex items-center justify-between text-[10px] text-muted-foreground">
        <span>P25: {fmt(item.benchmark_p25)}</span>
        <span className="font-medium">{item.verdict}</span>
        <span>P75: {fmt(item.benchmark_p75)}</span>
      </div>
    </div>
  );
}

// ── Benchmark Widget Card ─────────────────────────────────────────────────────

function BenchmarkCard({ data, loading }: { data: BenchmarkData | null; loading: boolean }) {
  if (loading) {
    return (
      <Card className="p-4 space-y-3 animate-pulse">
        <div className="h-4 w-40 bg-muted rounded" />
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="space-y-1.5">
            <div className="flex justify-between">
              <div className="h-3 w-32 bg-muted rounded" />
              <div className="h-3 w-12 bg-muted rounded" />
            </div>
            <div className="h-4 bg-muted rounded" />
          </div>
        ))}
      </Card>
    );
  }

  if (!data) {
    return (
      <Card className="p-4 text-center text-sm text-muted-foreground">
        Benchmark verisi yüklenemedi
      </Card>
    );
  }

  const strengths = data.strengths ?? [];
  const weaknesses = data.weaknesses ?? [];

  return (
    <Card className="p-4 space-y-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-sm">{data.company_name} — Sektör Benchmark</p>
          <p className="text-xs text-muted-foreground capitalize">
            {data.sector} · {data.company_size}
          </p>
        </div>
        <span className="text-[10px] text-muted-foreground/60 shrink-0">
          P25 / şirket / P75
        </span>
      </div>

      {/* Metrics */}
      <div className="space-y-3">
        {data.items.map((item) => (
          <BenchmarkMetricRow key={item.metric} item={item} />
        ))}
      </div>

      {/* Summary */}
      {data.summary && (
        <p className="text-xs text-muted-foreground border-t border-border pt-3 leading-relaxed">
          {data.summary}
        </p>
      )}

      {/* Strengths / Weaknesses */}
      {(strengths.length > 0 || weaknesses.length > 0) && (
        <div className="grid grid-cols-2 gap-3 border-t border-border pt-3">
          {strengths.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-emerald-400 mb-1.5">Güçlü Yönler</p>
              <ul className="space-y-1">
                {strengths.slice(0, 3).map((s, i) => (
                  <li key={i} className="text-[11px] text-muted-foreground flex items-start gap-1">
                    <span className="text-emerald-400 mt-0.5 shrink-0">↑</span>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {weaknesses.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-orange-400 mb-1.5">Gelişim Alanları</p>
              <ul className="space-y-1">
                {weaknesses.slice(0, 3).map((w, i) => (
                  <li key={i} className="text-[11px] text-muted-foreground flex items-start gap-1">
                    <span className="text-orange-400 mt-0.5 shrink-0">↓</span>
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

// ── Main Analytics Page ───────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const contextJobId = useActiveCFOJob();
  const finalJobId = jobId ?? contextJobId;

  const [macro, setMacro] = useState<MacroSnapshot | null>(null);
  const [benchmark, setBenchmark] = useState<BenchmarkData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!finalJobId) {
      setLoading(false);
      return;
    }

    async function fetchData() {
      try {
        setLoading(true);
        setError(null);

        // Fetch TCMB macro data
        const macroRes = await apiClient.get<{ data: MacroSnapshot }>("/analytics/macro");
        setMacro(macroRes.data.data);

        // Fetch benchmark data
        const benchRes = await apiClient.get<{ data: BenchmarkData }>(
          `/benchmark/${finalJobId}?sector=default`
        );
        setBenchmark(benchRes.data.data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Veri yüklenemedi");
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, [finalJobId]);

  return (
    <main className="mx-auto max-w-screen-xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <BarChart3 className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">Analitik & Benchmark</h1>
            <p className="text-sm text-muted-foreground">
              TCMB makroekonomik göstergeler ve sektör karşılaştırması
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => window.location.reload()}
        >
          <RefreshCw className="h-4 w-4 mr-1" />
          Yenile
        </Button>
      </div>

      {/* Error state */}
      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/8 p-4">
          <AlertCircle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-destructive">Hata</p>
            <p className="text-sm text-muted-foreground">{error}</p>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!finalJobId && !loading && (
        <Card className="flex flex-col items-center justify-center py-16 text-center">
          <BarChart3 className="h-12 w-12 text-muted-foreground/40 mb-3" />
          <p className="font-medium">Analiz Beklemede</p>
          <p className="text-sm text-muted-foreground max-w-sm mt-1">
            Finansal verisi yüklendikten sonra benchmark analizi görüntülenecektir.
          </p>
        </Card>
      )}

      {/* Content */}
      {finalJobId && (
        <div className="space-y-6">
          {/* Macro + Benchmark row */}
          <div className="grid gap-6 lg:grid-cols-2">
            <MacroCard data={macro} loading={loading} />
            <BenchmarkCard data={benchmark} loading={loading} />
          </div>

          {/* Full-width benchmark comparison chart */}
          {benchmark && benchmark.items.length > 0 && (
            <Card className="p-4 sm:p-6">
              <BenchmarkComparisonChart
                items={benchmark.items}
                sector={benchmark.sector}
                companyName={benchmark.company_name}
              />
            </Card>
          )}

          {/* Loading skeleton for chart */}
          {loading && (
            <Card className="p-4 sm:p-6 space-y-4 animate-pulse">
              <div className="flex justify-between items-center">
                <div className="h-4 w-48 bg-muted rounded" />
                <div className="h-8 w-12 bg-muted rounded" />
              </div>
              <div className="h-48 bg-muted rounded" />
              <div className="space-y-2">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="h-12 bg-muted rounded" />
                ))}
              </div>
            </Card>
          )}
        </div>
      )}

      {/* Info banner */}
      <div className="flex items-start gap-2 rounded-lg border border-blue-500/20 bg-blue-500/5 p-4 text-sm text-blue-400">
        <Zap className="h-4 w-4 mt-0.5 shrink-0" />
        <p>
          TCMB makroekonomik veriler günlük güncellenir. Benchmark karşılaştırması şirketinizin
          finansal göstergelerini Türkiye sektör ortalaması ile kıyaslar. P25/P50/P75 = %25/50/75 persentil.
        </p>
      </div>
    </main>
  );
}
