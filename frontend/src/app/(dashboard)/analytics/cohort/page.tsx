"use client";

export const dynamic = "force-dynamic";

import { useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";
import { Users, RefreshCw, Info, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { analyzeCohorts } from "@/lib/api/analytics";
import type { CohortResult } from "@/lib/api/analytics";

const fmtTRY = (v: number) =>
  `₺${v.toLocaleString("tr-TR", { minimumFractionDigits: 0 })}`;

// Sample cohort data for quick start
const SAMPLE_COHORTS: Record<string, string | number>[] = [
  { cohort_month: "2024-01", customers: 80,  revenue_month_0: 32000, revenue_month_1: 28000, revenue_month_2: 25000, revenue_month_3: 23000, revenue_month_4: 21000, revenue_month_5: 20000 },
  { cohort_month: "2024-02", customers: 95,  revenue_month_0: 40000, revenue_month_1: 35000, revenue_month_2: 31000, revenue_month_3: 28000, revenue_month_4: 26000, revenue_month_5: 24000 },
  { cohort_month: "2024-03", customers: 110, revenue_month_0: 48000, revenue_month_1: 43000, revenue_month_2: 38000, revenue_month_3: 35000, revenue_month_4: 32000, revenue_month_5: 0 },
  { cohort_month: "2024-04", customers: 130, revenue_month_0: 57000, revenue_month_1: 51000, revenue_month_2: 46000, revenue_month_3: 42000, revenue_month_4: 0,      revenue_month_5: 0 },
  { cohort_month: "2024-05", customers: 145, revenue_month_0: 65000, revenue_month_1: 59000, revenue_month_2: 54000, revenue_month_3: 0,     revenue_month_4: 0,      revenue_month_5: 0 },
  { cohort_month: "2024-06", customers: 160, revenue_month_0: 72000, revenue_month_1: 66000, revenue_month_2: 0,     revenue_month_3: 0,     revenue_month_4: 0,      revenue_month_5: 0 },
];

const COLORS = ["#3b82f6","#10b981","#f59e0b","#ef4444","#8b5cf6","#06b6d4","#f97316","#84cc16"];

export default function CohortPage() {
  const [cac,     setCac]     = useState("3000");
  const [result,  setResult]  = useState<CohortResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  async function handleRun(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true); setError(null);
    try {
      const res = await analyzeCohorts({
        cohorts:     SAMPLE_COHORTS,
        avg_cac_try: parseFloat(cac) || 0,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analiz başarısız");
    } finally {
      setLoading(false);
    }
  }

  // Build LTV chart data
  const ltvChartData = result
    ? Array.from({ length: 6 }, (_, month) => {
        const point: Record<string, number | string> = { month: `Ay ${month}` };
        result.cohorts.forEach((c) => {
          if (month < c.ltv_curve.length) {
            point[c.cohort_month] = c.ltv_curve[month];
          }
        });
        return point;
      })
    : [];

  // Build retention heatmap data
  const retentionData = result?.cohorts ?? [];

  return (
    <main className="mx-auto max-w-screen-xl space-y-6 p-4 sm:p-6 lg:p-8">
      <div className="flex items-center gap-3">
        <Users className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">Cohort Analizi</h1>
          <p className="text-sm text-muted-foreground">LTV eğrisi · Retention oranı · Payback period</p>
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-blue-500/20 bg-blue-500/5 px-4 py-3 text-sm text-blue-400">
        <Info className="h-4 w-4 mt-0.5 shrink-0" />
        <p>Her müşteri kohortu için kümülatif LTV hesaplanır. LTV/CAC ≥ 3 sağlıklı büyüme göstergesidir.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-4">
        {/* Form */}
        <Card className="p-5 lg:col-span-1">
          <h2 className="font-semibold text-sm mb-4">Parametreler</h2>
          <form onSubmit={handleRun} className="space-y-4">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Ortalama CAC (TRY)</label>
              <input
                type="number"
                value={cac}
                onChange={(e) => setCac(e.target.value)}
                className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>

            <div className="rounded-lg border border-border bg-muted/20 p-3 space-y-2">
              <p className="text-xs font-semibold text-muted-foreground">Örnek Veri</p>
              <p className="text-xs text-muted-foreground">{SAMPLE_COHORTS.length} kohort, Oca–Haz 2024</p>
              <p className="text-[10px] text-muted-foreground/70">
                Gerçek veri için CSV formatında cohort verisi entegrasyonu ileride eklenecek.
              </p>
            </div>

            {error && <p className="text-xs text-red-400 border border-red-500/20 bg-red-500/5 rounded px-2 py-1">{error}</p>}
            <Button type="submit" disabled={loading} className="w-full">
              {loading ? <><RefreshCw className="h-4 w-4 mr-2 animate-spin" />Hesaplanıyor…</> : "Cohort Analizi Çalıştır"}
            </Button>
          </form>
        </Card>

        {/* Results */}
        <div className="lg:col-span-3 space-y-4">
          {!result ? (
            <Card className="flex flex-col items-center justify-center py-20 text-center space-y-3">
              <Users className="h-12 w-12 text-muted-foreground/40" />
              <p className="font-medium">Cohort Analizi Hazır</p>
              <p className="text-sm text-muted-foreground">Örnek kohort verisi ile LTV, retention ve payback period hesaplanacak.</p>
            </Card>
          ) : (
            <>
              {/* Summary */}
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: "Ort. 12 Ay LTV", value: fmtTRY(result.summary.avg_ltv_12m), color: "text-foreground" },
                  { label: "LTV/CAC Oranı",  value: result.summary.ltv_cac_ratio ? `${result.summary.ltv_cac_ratio.toFixed(1)}x` : "—",
                    color: (result.summary.ltv_cac_ratio ?? 0) >= 3 ? "text-emerald-400" : "text-orange-400" },
                  { label: "Durum",           value: result.summary.verdict,
                    color: result.summary.verdict === "Sağlıklı" ? "text-emerald-400" : "text-orange-400" },
                ].map((s) => (
                  <Card key={s.label} className="p-3 space-y-1">
                    <p className="text-xs text-muted-foreground">{s.label}</p>
                    <p className={cn("text-xl font-bold", s.color)}>{s.value}</p>
                  </Card>
                ))}
              </div>

              {/* LTV curves chart */}
              <Card className="p-4 space-y-3">
                <h3 className="font-semibold text-sm">Kümülatif LTV Eğrileri (Müşteri Başına)</h3>
                <ResponsiveContainer width="100%" height={250}>
                  <LineChart data={ltvChartData} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.07} />
                    <XAxis dataKey="month" tick={{ fontSize: 10 }} />
                    <YAxis tickFormatter={(v) => `₺${(v/1000).toFixed(0)}K`} tick={{ fontSize: 10 }} />
                    <Tooltip formatter={(v: number) => [fmtTRY(v), ""]} contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 11 }} />
                    <Legend />
                    {result.cohorts.map((c, i) => (
                      <Line key={c.cohort_month} type="monotone" dataKey={c.cohort_month}
                        stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={false} name={c.cohort_month} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </Card>

              {/* Retention heatmap */}
              <Card className="overflow-hidden">
                <div className="px-4 py-3 border-b border-border">
                  <h3 className="font-semibold text-sm">Retention Matrisi (%)</h3>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border bg-muted/30">
                        <th className="py-2 px-3 text-left font-semibold text-muted-foreground">Kohort</th>
                        <th className="py-2 px-3 text-center font-semibold text-muted-foreground">Müşteri</th>
                        {["Ay 0","Ay 1","Ay 2","Ay 3","Ay 4","Ay 5"].map((m) => (
                          <th key={m} className="py-2 px-3 text-center font-semibold text-muted-foreground">{m}</th>
                        ))}
                        <th className="py-2 px-3 text-center font-semibold text-muted-foreground">LTV 12M</th>
                        <th className="py-2 px-3 text-center font-semibold text-muted-foreground">Payback</th>
                      </tr>
                    </thead>
                    <tbody>
                      {retentionData.map((c, ci) => (
                        <tr key={c.cohort_month} className="border-b border-border hover:bg-muted/20">
                          <td className="py-2 px-3 font-mono">{c.cohort_month}</td>
                          <td className="py-2 px-3 text-center">{c.customers}</td>
                          {Array.from({ length: 6 }, (_, month) => {
                            const ret = c.retention[month];
                            return (
                              <td key={month} className="py-2 px-3 text-center">
                                {ret !== undefined ? (
                                  <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium",
                                    ret >= 0.8 ? "bg-emerald-500/15 text-emerald-400" :
                                    ret >= 0.6 ? "bg-yellow-500/15 text-yellow-400" :
                                    ret >= 0.4 ? "bg-orange-500/15 text-orange-400" :
                                    "bg-red-500/15 text-red-400"
                                  )}>
                                    {(ret * 100).toFixed(0)}%
                                  </span>
                                ) : <span className="text-muted-foreground/40">—</span>}
                              </td>
                            );
                          })}
                          <td className="py-2 px-3 text-center font-mono font-semibold">
                            {fmtTRY(c.ltv_12m)}
                          </td>
                          <td className="py-2 px-3 text-center">
                            {c.payback_months ? (
                              <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium",
                                c.payback_months <= 6  ? "bg-emerald-500/15 text-emerald-400" :
                                c.payback_months <= 12 ? "bg-yellow-500/15 text-yellow-400" :
                                "bg-red-500/15 text-red-400"
                              )}>
                                {c.payback_months}ay
                              </span>
                            ) : <span className="text-muted-foreground/40">—</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
