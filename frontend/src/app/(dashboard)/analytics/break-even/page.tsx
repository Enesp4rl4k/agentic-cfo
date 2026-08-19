"use client";

export const dynamic = "force-dynamic";

import { useState } from "react";
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Legend,
} from "recharts";
import { BarChart3, RefreshCw, Info, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { analyzeBreakEven } from "@/lib/api/analytics";
import type { BreakEvenResult } from "@/lib/api/analytics";

const fmtTRY = (v: number) =>
  `₺${v.toLocaleString("tr-TR", { minimumFractionDigits: 0 })}`;

export default function BreakEvenPage() {
  const [form, setForm] = useState({
    fixed_costs_monthly_try:    "500000",
    variable_cost_per_unit_try: "150",
    price_per_unit_try:         "400",
    current_units_monthly:      "1800",
  });
  const [result,  setResult]  = useState<BreakEvenResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  function setField(key: string, val: string) {
    setForm((prev) => ({ ...prev, [key]: val }));
  }

  async function handleRun(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true); setError(null);
    try {
      const res = await analyzeBreakEven({
        fixed_costs_monthly_try:    parseFloat(form.fixed_costs_monthly_try),
        variable_cost_per_unit_try: parseFloat(form.variable_cost_per_unit_try),
        price_per_unit_try:         parseFloat(form.price_per_unit_try),
        current_units_monthly:      parseFloat(form.current_units_monthly) || 0,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analiz başarısız");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-screen-xl space-y-6 p-4 sm:p-6 lg:p-8">
      <div className="flex items-center gap-3">
        <BarChart3 className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">Break-Even Analizi</h1>
          <p className="text-sm text-muted-foreground">Başabaş noktası, katkı marjı ve senaryo analizi</p>
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-blue-500/20 bg-blue-500/5 px-4 py-3 text-sm text-blue-400">
        <Info className="h-4 w-4 mt-0.5 shrink-0" />
        <p>Break-even = Sabit Maliyet / (Fiyat - Değişken Maliyet). Bu noktanın üzerindeki her satış kar üretir.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Form */}
        <Card className="p-5 lg:col-span-1">
          <h2 className="font-semibold text-sm mb-4">Maliyet Yapısı</h2>
          <form onSubmit={handleRun} className="space-y-3">
            {[
              { key: "fixed_costs_monthly_try",    label: "Aylık Sabit Giderler (TRY)" },
              { key: "variable_cost_per_unit_try", label: "Birim Değişken Maliyet (TRY)" },
              { key: "price_per_unit_try",         label: "Birim Satış Fiyatı (TRY)" },
              { key: "current_units_monthly",      label: "Mevcut Aylık Satış (Adet, opsiyonel)" },
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
            {error && <p className="text-xs text-red-400 border border-red-500/20 bg-red-500/5 rounded px-2 py-1">{error}</p>}
            <Button type="submit" disabled={loading} className="w-full mt-2">
              {loading ? <><RefreshCw className="h-4 w-4 mr-2 animate-spin" />Hesaplanıyor…</> : "Break-Even Hesapla"}
            </Button>
          </form>
        </Card>

        {/* Results */}
        <div className="lg:col-span-2 space-y-4">
          {!result ? (
            <Card className="flex flex-col items-center justify-center py-20 text-center space-y-3">
              <BarChart3 className="h-12 w-12 text-muted-foreground/40" />
              <p className="font-medium">Maliyet verilerini girin</p>
              <p className="text-sm text-muted-foreground">Break-even noktası ve katkı marjı hesaplanacak.</p>
            </Card>
          ) : (
            <>
              {/* Key metrics */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  { label: "Break-Even (Adet)", value: result.break_even_units.toLocaleString("tr-TR"), color: "text-foreground" },
                  { label: "Break-Even (TRY)",  value: fmtTRY(result.break_even_revenue_try), color: "text-foreground" },
                  { label: "Katkı Marjı",       value: `%${result.contribution_margin_pct.toFixed(1)}`, color: "text-primary" },
                  { label: "Güvenlik Marjı",    value: `%${result.margin_of_safety_pct.toFixed(1)}`, color: result.margin_of_safety_pct > 20 ? "text-emerald-400" : result.margin_of_safety_pct > 0 ? "text-yellow-400" : "text-red-400" },
                ].map((m) => (
                  <Card key={m.label} className="p-3 space-y-1">
                    <p className="text-xs text-muted-foreground">{m.label}</p>
                    <p className={cn("text-xl font-bold tabular-nums", m.color)}>{m.value}</p>
                  </Card>
                ))}
              </div>

              {/* Current profit */}
              {result.current_profit_monthly !== null && (
                <Card className={cn("p-4 border", result.current_profit_monthly >= 0 ? "border-emerald-500/30 bg-emerald-500/5" : "border-red-500/30 bg-red-500/5")}>
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium">Mevcut Aylık Kâr/Zarar</p>
                    <p className={cn("text-2xl font-bold tabular-nums", result.current_profit_monthly >= 0 ? "text-emerald-400" : "text-red-400")}>
                      {result.current_profit_monthly >= 0 ? "+" : ""}{fmtTRY(result.current_profit_monthly)}
                    </p>
                  </div>
                </Card>
              )}

              {/* Scenario chart */}
              <Card className="p-4 space-y-3">
                <h3 className="font-semibold text-sm">Kapasite Senaryoları</h3>
                <ResponsiveContainer width="100%" height={240}>
                  <ComposedChart data={result.scenarios} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.07} />
                    <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                    <YAxis yAxisId="left" tickFormatter={(v) => `${(v / 1000).toFixed(0)}K`} tick={{ fontSize: 10 }} />
                    <YAxis yAxisId="right" orientation="right" tickFormatter={(v) => `${(v / 1000).toFixed(0)}K`} tick={{ fontSize: 10 }} />
                    <Tooltip
                      formatter={(v: number) => [fmtTRY(v), ""]}
                      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 11 }}
                    />
                    <Legend />
                    <Bar yAxisId="left" dataKey="revenue" name="Gelir" fill="#3b82f6" opacity={0.7} radius={[3, 3, 0, 0]} />
                    <Line yAxisId="right" type="monotone" dataKey="profit" name="Kâr/Zarar" stroke="#10b981" strokeWidth={2} dot={false} />
                    <ReferenceLine yAxisId="right" y={0} stroke="#ef4444" strokeDasharray="4 4" />
                  </ComposedChart>
                </ResponsiveContainer>
              </Card>

              {/* Scenario table */}
              <Card className="overflow-hidden">
                <div className="px-4 py-3 border-b border-border">
                  <h3 className="font-semibold text-sm">Senaryo Detayları</h3>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border bg-muted/30">
                        <th className="py-2.5 px-3 text-left font-semibold text-muted-foreground">Kapasite</th>
                        <th className="py-2.5 px-3 text-right font-semibold text-muted-foreground">Adet</th>
                        <th className="py-2.5 px-3 text-right font-semibold text-muted-foreground">Gelir</th>
                        <th className="py-2.5 px-3 text-right font-semibold text-muted-foreground">Kâr / Zarar</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.scenarios.map((s) => (
                        <tr key={s.label} className="border-b border-border hover:bg-muted/20">
                          <td className="py-2 px-3">{s.label}</td>
                          <td className="py-2 px-3 text-right font-mono">{s.units.toLocaleString("tr-TR")}</td>
                          <td className="py-2 px-3 text-right font-mono">{fmtTRY(s.revenue)}</td>
                          <td className={cn("py-2 px-3 text-right font-mono font-semibold", s.profit >= 0 ? "text-emerald-400" : "text-red-400")}>
                            {s.profit >= 0 ? "+" : ""}{fmtTRY(s.profit)}
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
