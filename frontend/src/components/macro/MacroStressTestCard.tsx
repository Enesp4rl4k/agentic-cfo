"use client";

import { useEffect, useState, useTransition } from "react";
import {
  TrendingUp,
  AlertTriangle,
  ShieldCheck,
  DollarSign,
  Percent,
  RefreshCw,
  Sliders,
  ArrowRight,
  Sparkles,
} from "lucide-react";

interface MacroData {
  usd_try: number;
  eur_try: number;
  policy_rate_pct: number;
  inflation_pct: number;
  real_cost_of_capital: number;
}

interface SimResult {
  baseline_runway_months: number;
  stressed_runway_months: number;
  runway_delta_months: number;
  monthly_cost_increase_lira: number;
  additional_fx_cost_lira: number;
  additional_interest_cost_lira: number;
  risk_level: string;
  risk_label: string;
  risk_color: string;
  recommendations: string[];
}

export function MacroStressTestCard({ accessToken }: { accessToken?: string }) {
  const [macro, setMacro] = useState<MacroData | null>(null);
  const [loading, setLoading] = useState(true);
  const [simulating, setSimulating] = useState(false);
  const [, startTransition] = useTransition();

  // Slider inputs
  const [usdShock, setUsdShock] = useState(15);
  const [rateDelta, setRateDelta] = useState(500);
  const [delayDays, setDelayDays] = useState(15);

  const [result, setResult] = useState<SimResult | null>(null);

  const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  const fetchMacro = async () => {
    setLoading(true);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

      const res = await fetch(`${API_BASE}/api/v1/macro/tcmb`, { headers });
      if (res.ok) {
        const json = await res.json();
        setMacro(json.data);
      }
    } catch (err) {
      console.error("TCMB macro fetch failed", err);
    } finally {
      setLoading(false);
    }
  };

  const runSimulation = async (usd: number, rate: number, delay: number) => {
    setSimulating(true);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

      const res = await fetch(`${API_BASE}/api/v1/macro/simulate`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          usd_shock_pct: usd,
          eur_shock_pct: usd,
          interest_rate_delta_bp: rate,
          payment_delay_days: delay,
        }),
      });

      if (res.ok) {
        const json = await res.json();
        setResult(json.data.simulation_result);
      }
    } catch (err) {
      console.error("Simulation failed", err);
    } finally {
      setSimulating(false);
    }
  };

  useEffect(() => {
    void fetchMacro();
    void runSimulation(usdShock, rateDelta, delayDays);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken]);

  const handleSliderChange = (usd: number, rate: number, delay: number) => {
    startTransition(() => {
      void runSimulation(usd, rate, delay);
    });
  };

  return (
    <div className="rounded-lg border border-border bg-card p-6 shadow-sm">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between pb-4 border-b border-border gap-2">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded bg-secondary/80 border border-border text-foreground">
            <TrendingUp className="h-4 w-4" />
          </div>
          <div>
            <h3 className="font-semibold text-base text-foreground flex items-center gap-2">
              TCMB Makro Göstergeleri & Kur/Faiz Şok Simülatörü
              <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-secondary border border-border text-muted-foreground">
                TCMB EVDS
              </span>
            </h3>
            <p className="text-xs text-muted-foreground">
              Döviz kuru ve faiz şoklarının nakit ömrü (runway) ve borçlanma maliyeti üzerindeki deterministik etkisi
            </p>
          </div>
        </div>
        <button
          onClick={fetchMacro}
          disabled={loading}
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors self-start sm:self-auto font-mono"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
          Yenile
        </button>
      </div>

      {/* TCMB Live Macro Tickers */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 my-4">
        <div className="rounded bg-secondary/40 p-3 border border-border">
          <div className="text-[11px] font-mono uppercase text-muted-foreground flex items-center gap-1.5">
            <DollarSign className="h-3 w-3 text-muted-foreground" /> USD / TRY
          </div>
          <div className="text-lg font-bold font-mono tabular-nums mt-1 text-foreground">
            {macro ? `${macro.usd_try.toFixed(2)} ₺` : "—"}
          </div>
        </div>

        <div className="rounded bg-secondary/40 p-3 border border-border">
          <div className="text-[11px] font-mono uppercase text-muted-foreground flex items-center gap-1.5">
            <DollarSign className="h-3 w-3 text-muted-foreground" /> EUR / TRY
          </div>
          <div className="text-lg font-bold font-mono tabular-nums mt-1 text-foreground">
            {macro ? `${macro.eur_try.toFixed(2)} ₺` : "—"}
          </div>
        </div>

        <div className="rounded bg-secondary/40 p-3 border border-border">
          <div className="text-[11px] font-mono uppercase text-muted-foreground flex items-center gap-1.5">
            <Percent className="h-3 w-3 text-muted-foreground" /> Politika Faizi
          </div>
          <div className="text-lg font-bold font-mono tabular-nums mt-1 text-foreground">
            {macro ? `%${macro.policy_rate_pct.toFixed(1)}` : "—"}
          </div>
        </div>

        <div className="rounded bg-secondary/40 p-3 border border-border">
          <div className="text-[11px] font-mono uppercase text-muted-foreground flex items-center gap-1.5">
            <Percent className="h-3 w-3 text-muted-foreground" /> Yıllık TÜFE
          </div>
          <div className="text-lg font-bold font-mono tabular-nums mt-1 text-foreground">
            {macro ? `%${macro.inflation_pct.toFixed(1)}` : "—"}
          </div>
        </div>
      </div>

      {/* Interactive Controls & Results Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 pt-2">
        {/* Left: Sliders */}
        <div className="lg:col-span-6 space-y-4 rounded bg-secondary/30 p-4 border border-border">
          <div className="text-xs font-mono uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
            <Sliders className="h-3.5 w-3.5 text-muted-foreground" />
            Şok Senaryo Parametreleri
          </div>

          {/* USD Shock Slider */}
          <div className="space-y-1.5">
            <div className="flex justify-between text-xs">
              <span className="text-muted-foreground">Dolar Kuru Artışı (%)</span>
              <span className="font-mono font-semibold text-foreground">+{usdShock}%</span>
            </div>
            <input
              type="range"
              min="0"
              max="50"
              step="5"
              value={usdShock}
              onChange={(e) => {
                const val = Number(e.target.value);
                setUsdShock(val);
                handleSliderChange(val, rateDelta, delayDays);
              }}
              className="w-full h-1.5 bg-secondary rounded appearance-none cursor-pointer accent-foreground"
            />
          </div>

          {/* Interest Rate Delta Slider */}
          <div className="space-y-1.5">
            <div className="flex justify-between text-xs">
              <span className="text-muted-foreground">Faiz Değişimi (Baz Puan)</span>
              <span className="font-mono font-semibold text-foreground">
                {rateDelta >= 0 ? `+${rateDelta} bp (+${(rateDelta / 100).toFixed(1)}%)` : `${rateDelta} bp`}
              </span>
            </div>
            <input
              type="range"
              min="-500"
              max="2000"
              step="100"
              value={rateDelta}
              onChange={(e) => {
                const val = Number(e.target.value);
                setRateDelta(val);
                handleSliderChange(usdShock, val, delayDays);
              }}
              className="w-full h-1.5 bg-secondary rounded appearance-none cursor-pointer accent-foreground"
            />
          </div>

          {/* Payment Delay Slider */}
          <div className="space-y-1.5">
            <div className="flex justify-between text-xs">
              <span className="text-muted-foreground">Alacak Tahsilat Gecikmesi</span>
              <span className="font-mono font-semibold text-foreground">+{delayDays} gün</span>
            </div>
            <input
              type="range"
              min="0"
              max="60"
              step="5"
              value={delayDays}
              onChange={(e) => {
                const val = Number(e.target.value);
                setDelayDays(val);
                handleSliderChange(usdShock, rateDelta, val);
              }}
              className="w-full h-1.5 bg-secondary rounded appearance-none cursor-pointer accent-foreground"
            />
          </div>
        </div>

        {/* Right: Simulation Output */}
        <div className="lg:col-span-6 space-y-4">
          {result && (
            <div className="rounded bg-secondary/30 p-4 border border-border space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                  Simülasyon Çıktısı
                </span>
                <span
                  className={`text-[11px] font-mono uppercase px-2 py-0.5 rounded border ${
                    result.risk_level === "CRITICAL"
                      ? "bg-red-500/10 text-red-400 border-red-500/30"
                      : result.risk_level === "HIGH"
                      ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                      : "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                  }`}
                >
                  {result.risk_label}
                </span>
              </div>

              {/* Stressed Runway Highlight */}
              <div className="flex items-baseline justify-between pt-1">
                <div>
                  <div className="text-xs text-muted-foreground">Stres Altında Nakit Ömrü</div>
                  <div className="text-2xl font-bold font-mono tabular-nums text-foreground mt-0.5">
                    {result.stressed_runway_months}{" "}
                    <span className="text-xs font-normal text-muted-foreground">ay</span>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-xs text-muted-foreground">Runway Değişimi</div>
                  <div className="text-base font-bold font-mono tabular-nums text-red-400">
                    {result.runway_delta_months} ay
                  </div>
                </div>
              </div>

              {/* Incremental Cost */}
              <div className="flex items-center justify-between pt-2 border-t border-border text-xs">
                <span className="text-muted-foreground">Aylık İlave Nakit Çıkışı (FX + Faiz):</span>
                <span className="font-bold font-mono tabular-nums text-foreground">
                  +{result.monthly_cost_increase_lira.toLocaleString("tr-TR")} ₺ / ay
                </span>
              </div>

              {/* Recommendations */}
              {result.recommendations.length > 0 && (
                <div className="pt-2 border-t border-border">
                  <div className="text-xs font-semibold text-foreground mb-1.5 flex items-center gap-1">
                    Önerilen Eylemler
                  </div>
                  <ul className="space-y-1 text-xs text-muted-foreground">
                    {result.recommendations.slice(0, 2).map((rec, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <ArrowRight className="h-3 w-3 text-muted-foreground mt-0.5 shrink-0" />
                        <span>{rec}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

