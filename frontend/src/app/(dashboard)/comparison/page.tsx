"use client";

export const dynamic = "force-dynamic";

import { useEffect, useState } from "react";
import {
  TrendingUp, TrendingDown, Calendar, BarChart3, Loader2, RefreshCw,
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, LineChart, Line,
} from "recharts";
import { apiClient } from "@/lib/api/client";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { JobSummary } from "@/lib/api/cfo";

// ── Type definitions ──────────────────────────────────────────────────────────

interface PeriodMetrics {
  period: string;
  revenue: number;
  gross_profit: number;
  gross_margin: number;
  ebitda: number;
  ebitda_margin: number;
  net_income: number;
  net_margin: number;
  opex: number;
  cash_flow: number;
}

interface ComparisonResult {
  periods: PeriodMetrics[];
  changes: {
    metric: string;
    period1_value: number;
    period2_value: number;
    change_amount: number;
    change_percent: number;
    unit: string;
    direction: "up" | "down" | "neutral";
  }[];
  narrative: string;
}

// ── Period Selector ───────────────────────────────────────────────────────────

function PeriodSelector({
  jobs,
  selectedIds,
  onSelect,
  loading,
  onCompare,
}: {
  jobs: JobSummary[];
  selectedIds: string[];
  onSelect: (ids: string[]) => void;
  loading: boolean;
  onCompare: () => void;
}) {
  if (jobs.length === 0) {
    return (
      <Card className="p-4 text-center text-sm text-muted-foreground">
        Karşılaştırılacak analiz bulunamadı. En az 2 dönem yükleyin.
      </Card>
    );
  }

  return (
    <Card className="p-4 space-y-3">
      <p className="text-sm font-semibold">Dönem Seçimi</p>
      <div className="space-y-2">
        {jobs.map((job) => (
          <label key={job.job_id} className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={selectedIds.includes(job.job_id)}
              onChange={(e) => {
                if (e.target.checked && selectedIds.length < 3) {
                  onSelect([...selectedIds, job.job_id]);
                } else if (!e.target.checked) {
                  onSelect(selectedIds.filter((id) => id !== job.job_id));
                }
              }}
              disabled={!selectedIds.includes(job.job_id) && selectedIds.length >= 3}
              className="rounded"
            />
            <span className="text-sm flex-1 min-w-0">
              {job.filename} · {new Date(job.created_at).toLocaleDateString("tr-TR")}
            </span>
            <span className="text-xs text-muted-foreground shrink-0">
              {job.status === "completed" ? "✓" : "…"}
            </span>
          </label>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        2-3 dönem seçebilirsiniz. {selectedIds.length}/{Math.min(3, jobs.length)} seçili.
      </p>
      <Button
        disabled={selectedIds.length < 2 || loading}
        className="w-full"
        onClick={onCompare}
      >
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
            Karşılaştırılıyor…
          </>
        ) : (
          "Karşılaştır"
        )}
      </Button>
    </Card>
  );
}

// ── Metrics Table ─────────────────────────────────────────────────────────────

function MetricsTable({ periods }: { periods: PeriodMetrics[] }) {
  const metrics = [
    { key: "revenue", label: "Ciro", format: formatCurrency, unit: "TRY" },
    { key: "gross_profit", label: "Brüt Kâr", format: formatCurrency, unit: "TRY" },
    { key: "gross_margin", label: "Brüt Marj", format: formatPercent, unit: "%" },
    { key: "ebitda", label: "FAVÖK", format: formatCurrency, unit: "TRY" },
    { key: "ebitda_margin", label: "FAVÖK Marjı", format: formatPercent, unit: "%" },
    { key: "net_income", label: "Net Gelir", format: formatCurrency, unit: "TRY" },
    { key: "net_margin", label: "Net Marj", format: formatPercent, unit: "%" },
    { key: "opex", label: "OpEx", format: formatCurrency, unit: "TRY" },
    { key: "cash_flow", label: "Nakit Akışı", format: formatCurrency, unit: "TRY" },
  ];

  return (
    <Card className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground">
              Metrik
            </th>
            {periods.map((p) => (
              <th
                key={p.period}
                className="px-4 py-3 text-right text-xs font-medium text-muted-foreground"
              >
                {p.period}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metrics.map((m) => (
            <tr key={m.key} className="border-b border-border/50 last:border-0">
              <td className="px-4 py-3 font-medium text-xs">{m.label}</td>
              {periods.map((p) => {
                const val = (p as any)[m.key];
                return (
                  <td key={p.period} className="px-4 py-3 text-right font-mono text-xs">
                    {m.format(val)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

// ── Change Indicator ──────────────────────────────────────────────────────────

function ChangeIndicator({
  change,
}: {
  change: ComparisonResult["changes"][0];
}) {
  const isPositive = change.direction === "up";
  const icon = isPositive ? "↑" : change.direction === "down" ? "↓" : "→";
  const color = isPositive
    ? "text-emerald-400"
    : change.direction === "down"
      ? "text-red-400"
      : "text-muted-foreground";

  return (
    <div className="rounded-lg border border-border bg-card p-3 space-y-1">
      <p className="text-xs text-muted-foreground">{change.metric}</p>
      <div className="flex items-end justify-between gap-2">
        <div>
          <p className={cn("text-sm font-mono font-semibold", color)}>
            {icon} {Math.abs(change.change_percent).toFixed(1)}%
          </p>
          <p className="text-xs text-muted-foreground">
            {formatCurrency(change.change_amount)}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground">
            {formatCurrency(change.period1_value)}
          </p>
          <p className="text-xs font-medium">→</p>
          <p className="text-xs text-muted-foreground">
            {formatCurrency(change.period2_value)}
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Main Comparison Page ──────────────────────────────────────────────────────

export default function ComparisonPage() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [result, setResult] = useState<ComparisonResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch available jobs
  useEffect(() => {
    async function fetchJobs() {
      try {
        // The endpoint returns {data: {jobs, total}}, not {data: [...]}. Reading
        // it as an array put an object in state and every render died on
        // `jobs.map is not a function`.
        const res = await apiClient.get<{ data: { jobs: JobSummary[]; total: number } }>(
          "/comparison/jobs",
        );
        setJobs(res.data.data?.jobs ?? []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "İşler yüklenemedi");
      }
    }

    fetchJobs();
  }, []);

  // Run comparison
  const handleCompare = async () => {
    if (selectedIds.length < 2) return;

    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<{ data: ComparisonResult }>(
        "/comparison/multi-period",
        { job_ids: selectedIds }
      );
      setResult(res.data.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Karşılaştırma başarısız");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-screen-xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <BarChart3 className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">Dönem Karşılaştırması</h1>
            <p className="text-sm text-muted-foreground">
              Q1 vs Q2, 2023 vs 2024 — finansal metrikleri yan yana karşılaştırın
            </p>
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
          <p className="text-sm text-destructive">{error}</p>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Period selector */}
        <div className="lg:col-span-1">
          <PeriodSelector
            jobs={jobs}
            selectedIds={selectedIds}
            onSelect={setSelectedIds}
            loading={loading}
            onCompare={handleCompare}
          />
        </div>

        {/* Results */}
        <div className="lg:col-span-2 space-y-6">
          {!result ? (
            <Card className="flex flex-col items-center justify-center py-20 text-center">
              <Calendar className="h-12 w-12 text-muted-foreground/40 mb-3" />
              <p className="font-medium">Karşılaştırma Hazır</p>
              <p className="text-sm text-muted-foreground max-w-sm mt-1">
                Sol panelden 2-3 dönem seçerek karşılaştırma yapın.
              </p>
            </Card>
          ) : (
            <>
              {/* Metrics table */}
              <MetricsTable periods={result.periods} />

              {/* Narrative */}
              {result.narrative && (
                <Card className="p-4 border-blue-500/20 bg-blue-500/5">
                  <p className="text-xs font-semibold text-blue-400 mb-2">Özet</p>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    {result.narrative}
                  </p>
                </Card>
              )}

              {/* Changes grid */}
              <div className="space-y-3">
                <p className="text-sm font-semibold">Dönemler Arası Değişiklikler</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {result.changes.slice(0, 8).map((c, i) => (
                    <ChangeIndicator key={i} change={c} />
                  ))}
                </div>
              </div>

              {/* Dual-axis chart */}
              {result.periods.length >= 2 && (
                <Card className="p-4 space-y-3">
                  <p className="text-sm font-semibold">Ciro vs Marj Trendi</p>
                  <ResponsiveContainer width="100%" height={250}>
                    <BarChart
                      data={result.periods.map((p) => ({
                        period: p.period,
                        revenue: p.revenue / 1000000, // millions
                        margin: p.net_margin * 100, // %
                      }))}
                      margin={{ top: 5, right: 30, left: 0, bottom: 5 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.1} />
                      <XAxis dataKey="period" tick={{ fontSize: 11 }} opacity={0.6} />
                      <YAxis
                        yAxisId="left"
                        tickFormatter={(v: number) => `${v}M₺`}
                        tick={{ fontSize: 11 }}
                        opacity={0.6}
                      />
                      <YAxis
                        yAxisId="right"
                        orientation="right"
                        tickFormatter={(v: number) => `${v}%`}
                        tick={{ fontSize: 11 }}
                        opacity={0.6}
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
                      <Bar
                        yAxisId="left"
                        dataKey="revenue"
                        name="Ciro (Milyon TRY)"
                        fill="oklch(0.60 0.19 255)"
                        radius={[4, 4, 0, 0]}
                      />
                      <Line
                        yAxisId="right"
                        type="monotone"
                        dataKey="margin"
                        name="Net Marj (%)"
                        stroke="oklch(0.58 0.14 145)"
                        strokeWidth={2}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </Card>
              )}
            </>
          )}
        </div>
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-2 rounded-lg border border-blue-500/20 bg-blue-500/5 p-4 text-sm text-blue-400">
        <BarChart3 className="h-4 w-4 mt-0.5 shrink-0" />
        <p>
          En fazla 3 dönem seçebilirsiniz. Karşılaştırma her dönemdeki finansal göstergeler arasındaki
          farkları, yüzde değişimleri ve trendleri gösterir.
        </p>
      </div>
    </main>
  );
}
