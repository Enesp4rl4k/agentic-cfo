"use client";

export const dynamic = "force-dynamic";

import { useState } from "react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, BarChart, Bar, Cell,
} from "recharts";
import { TrendingUp, RefreshCw, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { runMonteCarlo } from "@/lib/api/analytics";
import type { MonteCarloResult } from "@/lib/api/analytics";

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmtTRY = (v: number) =>
  `₺${(v / 1000).toLocaleString("tr-TR", { minimumFractionDigits: 0 })}K`;

// ── Input form ────────────────────────────────────────────────────────────────

interface FormState {
  current_cash_try:     string;
  monthly_revenue_try:  string;
  monthly_burn_try:     string;
  revenue_std_pct:      string;
  burn_std_pct:         string;
  growth_rate_monthly:  string;
  months:               string;
  simulations:          string;
}

const DEFAULT_FORM: FormState = {
  current_cash_try:    "6000000",
  monthly_revenue_try: "1000000",
  monthly_burn_try:    "800000",
  revenue_std_pct:     "0.15",
  burn_std_pct:        "0.10",
  growth_rate_monthly: "0.02",
  months:              "12",
  simulations:         "1000",
};

// ── Chart: sample paths ───────────────────────────────────────────────────────

function SamplePathsChart({ paths, months }: { paths: number[][]; months: number }) {
  const labels = Array.from({ length: months + 1 }, (_, i) => `Ay ${i}`);

  // Build recharts data: one entry per month, each path as a key
  const data = labels.map((label, monthIdx) => {
    const entry: Record<string, number | string> = { label };
    paths.forEach((path, pi) => {
      entry[`path_${pi}`] = path[monthIdx] ?? 0;
    });
    return entry;
  });

  const colors = [
    "#3b82f6", "#10b981", "#f59e0b", "#ef4444",
    "#8b5cf6", "#06b6d4", "#f97316", "#84cc16",
    "#ec4899", "#14b8a6", "#a855f7", "#eab308",
    "#6366f1", "#22c55e", "#fb923c", "#f43f5e",
    "#0ea5e9", "#34d399", "#fbbf24", "#a78bfa",
  ];

  return (
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.07} />
        <XAxis dataKey="label" tick={{ fontSize: 10 }} stroke="currentColor" opacity={0.4} />
        <YAxis tickFormatter={(v) => fmtTRY(v)} tick={{ fontSize: 10 }} stroke="currentColor" opacity={0.4} width={60} />
        <Tooltip
          formatter={(v: number) => [fmtTRY(v), ""]}
          contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 11 }}
        />
        <ReferenceLine y={0} stroke="#ef4444" strokeDasharray="4 4" label={{ value: "İflas sınırı", fontSize: 10, fill: "#ef4444" }} />
        {paths.slice(0, 20).map((_, pi) => (
          <Area
            key={pi}
            type="monotone"
            dataKey={`path_${pi}`}
            stroke={colors[pi % colors.length]}
            strokeWidth={1}
            fill="none"
            dot={false}
            opacity={0.5}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ── Chart: survival bar ───────────────────────────────────────────────────────

function SurvivalGauge({ survivalRate }: { survivalRate: number }) {
  const pct   = Math.round(survivalRate * 100);
  const color = pct >= 85 ? "#10b981" : pct >= 60 ? "#f59e0b" : "#ef4444";

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">Hayatta Kalma Oranı</span>
        <span className="font-bold tabular-nums" style={{ color }}>%{pct}</span>
      </div>
      <div className="h-3 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        {pct >= 85 ? "Güçlü finansal pozisyon" : pct >= 60 ? "Orta risk — dikkat gerekiyor" : "Yüksek risk — acil aksiyon gerekli"}
      </p>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function MonteCarloPage() {
  const [form,    setForm]    = useState<FormState>(DEFAULT_FORM);
  const [result,  setResult]  = useState<MonteCarloResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  function setField(key: keyof FormState, val: string) {
    setForm((prev) => ({ ...prev, [key]: val }));
  }

  async function handleRun(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await runMonteCarlo({
        current_cash_try:     parseFloat(form.current_cash_try),
        monthly_revenue_try:  parseFloat(form.monthly_revenue_try),
        monthly_burn_try:     parseFloat(form.monthly_burn_try),
        revenue_std_pct:      parseFloat(form.revenue_std_pct),
        burn_std_pct:         parseFloat(form.burn_std_pct),
        growth_rate_monthly:  parseFloat(form.growth_rate_monthly),
        months:               parseInt(form.months),
        simulations:          parseInt(form.simulations),
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Simülasyon başarısız");
    } finally {
      setLoading(false);
    }
  }

  const FIELDS: { key: keyof FormState; label: string; suffix?: string; step?: string }[] = [
    { key: "current_cash_try",    label: "Mevcut Nakit (TRY)",       suffix: "₺" },
    { key: "monthly_revenue_try", label: "Aylık Gelir (TRY)",        suffix: "₺" },
    { key: "monthly_burn_try",    label: "Aylık Tüketim (TRY)",      suffix: "₺" },
    { key: "revenue_std_pct",     label: "Gelir Volatilitesi",       suffix: "σ", step: "0.01" },
    { key: "burn_std_pct",        label: "Tüketim Volatilitesi",     suffix: "σ", step: "0.01" },
    { key: "growth_rate_monthly", label: "Aylık Büyüme Oranı",      suffix: "%", step: "0.001" },
    { key: "months",              label: "Simülasyon Süresi (Ay)",   suffix: "ay" },
    { key: "simulations",         label: "Senaryo Sayısı",           suffix: "adet" },
  ];

  return (
    <main className="mx-auto max-w-screen-xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <TrendingUp className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">Monte Carlo Simülasyonu</h1>
          <p className="text-sm text-muted-foreground">
            Nakit akışı için olasılıksal senaryo analizi — {form.simulations} rastgele yol
          </p>
        </div>
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-2 rounded-lg border border-blue-500/20 bg-blue-500/5 px-4 py-3 text-sm text-blue-400">
        <Info className="h-4 w-4 mt-0.5 shrink-0" />
        <p>
          Monte Carlo simülasyonu, gelir ve giderlerdeki belirsizliği modelleyerek nakit pozisyonunuzun
          olası dağılımını gösterir. Hayatta kalma oranı %85+ ise finansal pozisyon güçlüdür.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Input form */}
        <Card className="p-5 lg:col-span-1">
          <h2 className="font-semibold text-sm mb-4">Parametreler</h2>
          <form onSubmit={handleRun} className="space-y-3">
            {FIELDS.map(({ key, label, suffix, step }) => (
              <div key={key} className="space-y-1">
                <label className="text-xs text-muted-foreground">{label}</label>
                <div className="flex items-center gap-1">
                  <input
                    type="number"
                    value={form[key]}
                    step={step ?? "1"}
                    onChange={(e) => setField(key, e.target.value)}
                    className="flex-1 rounded border border-input bg-background px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-ring"
                    required
                  />
                  {suffix && (
                    <span className="text-xs text-muted-foreground w-8 text-right">{suffix}</span>
                  )}
                </div>
              </div>
            ))}

            {error && (
              <p className="text-xs text-red-400 border border-red-500/20 bg-red-500/5 rounded px-2 py-1">
                {error}
              </p>
            )}

            <Button type="submit" disabled={loading} className="w-full mt-2">
              {loading ? (
                <><RefreshCw className="h-4 w-4 mr-2 animate-spin" />Hesaplanıyor…</>
              ) : (
                <><TrendingUp className="h-4 w-4 mr-2" />Simülasyonu Çalıştır</>
              )}
            </Button>
          </form>
        </Card>

        {/* Results */}
        <div className="lg:col-span-2 space-y-4">
          {!result ? (
            <Card className="flex flex-col items-center justify-center py-20 text-center space-y-3">
              <TrendingUp className="h-12 w-12 text-muted-foreground/40" />
              <p className="font-medium">Simülasyon Hazır</p>
              <p className="text-sm text-muted-foreground max-w-sm">
                Sol formdaki parametreleri girin ve simülasyonu çalıştırın.
                {parseInt(form.simulations).toLocaleString("tr-TR")} senaryo hesaplanacak.
              </p>
            </Card>
          ) : (
            <>
              {/* Summary cards */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  {
                    label: "Hayatta Kalma",
                    value: `%${Math.round(result.survival_rate * 100)}`,
                    color: result.survival_rate >= 0.85 ? "text-emerald-400" :
                           result.survival_rate >= 0.60 ? "text-yellow-400" : "text-red-400",
                  },
                  {
                    label: "Ort. Nakit Pisti",
                    value: `${result.avg_runway_months.toFixed(1)} ay`,
                    color: "text-foreground",
                  },
                  {
                    label: "Medyan Nihai Nakit",
                    value: fmtTRY(result.final_cash.median),
                    color: result.final_cash.median > 0 ? "text-emerald-400" : "text-red-400",
                  },
                  {
                    label: "İflas Olasılığı",
                    value: `%${result.bankruptcy_pct.toFixed(1)}`,
                    color: result.bankruptcy_pct < 15 ? "text-emerald-400" :
                           result.bankruptcy_pct < 40 ? "text-yellow-400" : "text-red-400",
                  },
                ].map((s) => (
                  <Card key={s.label} className="p-3 space-y-1">
                    <p className="text-xs text-muted-foreground">{s.label}</p>
                    <p className={cn("text-xl font-bold tabular-nums", s.color)}>{s.value}</p>
                  </Card>
                ))}
              </div>

              {/* Survival gauge */}
              <Card className="p-4">
                <SurvivalGauge survivalRate={result.survival_rate} />
              </Card>

              {/* Sample paths chart */}
              <Card className="p-4 space-y-3">
                <h3 className="font-semibold text-sm">
                  Nakit Yolları (20 Örnek Senaryo)
                </h3>
                <SamplePathsChart paths={result.sample_paths} months={parseInt(form.months)} />
                <p className="text-xs text-muted-foreground">
                  Her çizgi farklı bir rastgele senaryo. Kırmızı çizgi = iflas sınırı (₺0).
                </p>
              </Card>

              {/* P10/P50/P90 */}
              <Card className="p-4 space-y-3">
                <h3 className="font-semibold text-sm">Nakit Dağılımı ({parseInt(form.months)}. Ayda)</h3>
                <div className="grid grid-cols-3 gap-4 text-center">
                  {[
                    { label: "Kötümser (P10)", value: result.final_cash.p10, color: "text-red-400" },
                    { label: "Orta (P50)",     value: result.final_cash.median, color: "text-yellow-400" },
                    { label: "İyimser (P90)",  value: result.final_cash.p90, color: "text-emerald-400" },
                  ].map((p) => (
                    <div key={p.label} className="rounded-lg bg-muted/30 p-3">
                      <p className="text-xs text-muted-foreground">{p.label}</p>
                      <p className={cn("text-lg font-bold tabular-nums mt-1", p.color)}>
                        {fmtTRY(p.value)}
                      </p>
                    </div>
                  ))}
                </div>
              </Card>

              {/* Interpretation */}
              <Card className={cn("p-4 flex items-start gap-3 border",
                result.survival_rate >= 0.85 ? "border-emerald-500/30 bg-emerald-500/5" :
                result.survival_rate >= 0.60 ? "border-yellow-500/30 bg-yellow-500/5" :
                "border-red-500/30 bg-red-500/5"
              )}>
                {result.survival_rate >= 0.85
                  ? <CheckCircle2 className="h-5 w-5 text-emerald-400 shrink-0 mt-0.5" />
                  : <AlertTriangle className="h-5 w-5 text-orange-400 shrink-0 mt-0.5" />
                }
                <p className="text-sm">{result.interpretation}</p>
              </Card>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
