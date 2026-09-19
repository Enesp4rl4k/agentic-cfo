"use client";

export const dynamic = "force-dynamic";

import { useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, ReferenceLine,
} from "recharts";
import { DollarSign, RefreshCw, Info, TrendingUp, TrendingDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { analyzeWorkingCapital } from "@/lib/api/analytics";
import type { WorkingCapitalResult } from "@/lib/api/analytics";

const fmtTRY = (v: number) =>
  `₺${(v / 1000).toLocaleString("tr-TR", { minimumFractionDigits: 0 })}K`;

const fmtDays = (v: number) => `${v.toFixed(1)} gün`;

const SECTORS = ["saas", "ecommerce", "services", "retail", "manufacturing"];

export default function WorkingCapitalPage() {
  const [form, setForm] = useState({
    accounts_receivable_try: "500000",
    annual_revenue_try:      "12000000",
    accounts_payable_try:    "300000",
    annual_cogs_try:         "7200000",
    inventory_try:           "0",
    sector:                  "saas",
  });
  const [result,  setResult]  = useState<WorkingCapitalResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  function setField(key: string, val: string) {
    setForm((prev) => ({ ...prev, [key]: val }));
  }

  async function handleRun(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true); setError(null);
    try {
      const res = await analyzeWorkingCapital({
        accounts_receivable_try:  parseFloat(form.accounts_receivable_try),
        annual_revenue_try:       parseFloat(form.annual_revenue_try),
        accounts_payable_try:     parseFloat(form.accounts_payable_try),
        annual_cogs_try:          parseFloat(form.annual_cogs_try),
        inventory_try:            parseFloat(form.inventory_try) || 0,
        sector:                   form.sector,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analiz başarısız");
    } finally {
      setLoading(false);
    }
  }

  // Chart data for DSO/DPO/DIO comparison
  const chartData = result ? [
    { name: "DSO", actual: result.metrics.dso_days, bench: result.benchmarks.dso, gap: result.gaps.dso_gap },
    { name: "DPO", actual: result.metrics.dpo_days, bench: result.benchmarks.dpo, gap: result.gaps.dpo_gap },
    { name: "DIO", actual: result.metrics.dio_days, bench: result.benchmarks.dio ?? 0, gap: 0 },
    { name: "CCC", actual: result.metrics.ccc_days, bench: result.benchmarks.ccc, gap: 0 },
  ] : [];

  return (
    <main className="mx-auto max-w-screen-xl space-y-6 p-4 sm:p-6 lg:p-8">
      <div className="flex items-center gap-3">
        <DollarSign className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">Working Capital Optimizasyonu</h1>
          <p className="text-sm text-muted-foreground">DSO · DPO · DIO · Cash Conversion Cycle</p>
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-blue-500/20 bg-blue-500/5 px-4 py-3 text-sm text-blue-400">
        <Info className="h-4 w-4 mt-0.5 shrink-0" />
        <p>DSO (alacak vade) + DIO (stok vade) - DPO (borç vade) = Cash Conversion Cycle. CCC ne kadar düşükse nakit o kadar hızlı döner.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Form */}
        <Card className="p-5 lg:col-span-1">
          <h2 className="font-semibold text-sm mb-4">Finansal Veriler</h2>
          <form onSubmit={handleRun} className="space-y-3">
            {[
              { key: "accounts_receivable_try", label: "Alacaklar (TRY)" },
              { key: "annual_revenue_try",      label: "Yıllık Gelir (TRY)" },
              { key: "accounts_payable_try",    label: "Borçlar / Ödenecekler (TRY)" },
              { key: "annual_cogs_try",         label: "Yıllık COGS (TRY)" },
              { key: "inventory_try",           label: "Stok (TRY, 0 = yok)" },
            ].map(({ key, label }) => (
              <div key={key} className="space-y-1">
                <label className="text-xs text-muted-foreground">{label}</label>
                <input
                  type="number"
                  value={(form as Record<string, string>)[key]}
                  onChange={(e) => setField(key, e.target.value)}
                  className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
            ))}
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Sektör</label>
              <select
                value={form.sector}
                onChange={(e) => setField("sector", e.target.value)}
                className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              >
                {SECTORS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            {error && <p className="text-xs text-red-400 border border-red-500/20 bg-red-500/5 rounded px-2 py-1">{error}</p>}
            <Button type="submit" disabled={loading} className="w-full mt-2">
              {loading ? <><RefreshCw className="h-4 w-4 mr-2 animate-spin" />Hesaplanıyor…</> : "Analizi Çalıştır"}
            </Button>
          </form>
        </Card>

        {/* Results */}
        <div className="lg:col-span-2 space-y-4">
          {!result ? (
            <Card className="flex flex-col items-center justify-center py-20 text-center space-y-3">
              <DollarSign className="h-12 w-12 text-muted-foreground/40" />
              <p className="font-medium">Verilerinizi Girin</p>
              <p className="text-sm text-muted-foreground">DSO, DPO, DIO ve CCC hesaplanacak, sektör benchmarklarıyla karşılaştırılacak.</p>
            </Card>
          ) : (
            <>
              {/* Metric cards */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  { label: "DSO (Alacak Vade)", value: fmtDays(result.metrics.dso_days), gap: result.gaps.dso_gap },
                  { label: "DPO (Borç Vade)",   value: fmtDays(result.metrics.dpo_days), gap: -result.gaps.dpo_gap },
                  { label: "DIO (Stok Vade)",   value: fmtDays(result.metrics.dio_days), gap: 0 },
                  { label: "CCC (Nakit Döngüsü)", value: fmtDays(result.metrics.ccc_days), gap: result.metrics.ccc_days > result.benchmarks.ccc ? 1 : -1 },
                ].map((m) => (
                  <Card key={m.label} className="p-3 space-y-1">
                    <p className="text-xs text-muted-foreground">{m.label}</p>
                    <p className="text-xl font-bold tabular-nums">{m.value}</p>
                    {m.gap !== 0 && (
                      <div className={cn("flex items-center gap-1 text-xs", m.gap > 0 ? "text-red-400" : "text-emerald-400")}>
                        {m.gap > 0 ? <TrendingDown className="h-3 w-3" /> : <TrendingUp className="h-3 w-3" />}
                        {m.gap > 0 ? `${m.gap.toFixed(1)} gün fazla` : `${Math.abs(m.gap).toFixed(1)} gün iyi`}
                      </div>
                    )}
                  </Card>
                ))}
              </div>

              {/* Bar chart — actual vs benchmark */}
              <Card className="p-4 space-y-3">
                <h3 className="font-semibold text-sm">Gerçekleşen vs Sektör Ortalaması</h3>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={chartData} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.07} />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}g`} />
                    <Tooltip formatter={(v: number) => [`${v.toFixed(1)} gün`, ""]} contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 11 }} />
                    <Bar dataKey="actual" name="Sizin" fill="#3b82f6" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="bench"  name="Sektör" fill="#10b981" radius={[3, 3, 0, 0]} opacity={0.6} />
                  </BarChart>
                </ResponsiveContainer>
              </Card>

              {/* Opportunity */}
              <Card className="p-4 border-primary/20 bg-primary/5">
                <p className="font-semibold text-sm text-primary mb-1">Nakit Serbest Bırakma Fırsatı</p>
                <p className="text-2xl font-bold tabular-nums text-emerald-400">
                  {fmtTRY(result.opportunity.cash_release_try)}
                </p>
                <p className="text-xs text-muted-foreground mt-1">{result.opportunity.description}</p>
              </Card>

              {/* Recommendations */}
              <Card className="p-4 space-y-2">
                <h3 className="font-semibold text-sm">Öneriler</h3>
                {result.recommendations.map((r, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm">
                    <span className="mt-1 h-1.5 w-1.5 rounded-full bg-primary shrink-0" />
                    <p className="text-muted-foreground">{r}</p>
                  </div>
                ))}
              </Card>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
