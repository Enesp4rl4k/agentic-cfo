"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, DollarSign, Euro, Percent, RefreshCw, Sliders, TrendingUp } from "lucide-react";
import { useI18n } from "@/hooks/useI18n";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { ProvenanceBadge } from "@/components/ui/provenance-badge";
import type { MessageTree } from "@/lib/i18n";
import {
  getTcmbSnapshot,
  simulateMacroShock,
  type ShockInputs,
  type StressResponse,
  type TcmbSnapshot,
} from "@/lib/api/macro";

type RiskKey = keyof MessageTree["macroStress"]["risk"];
type RecKey = keyof MessageTree["macroStress"]["recs"];

const RISK_STYLES: Record<RiskKey, string> = {
  CRITICAL: "bg-red-500/10 text-red-400 border-red-500/30",
  CASH_NEGATIVE: "bg-red-500/10 text-red-400 border-red-500/30",
  HIGH: "bg-amber-500/10 text-amber-400 border-amber-500/30",
  MODERATE: "bg-blue-500/10 text-blue-400 border-blue-500/30",
  LOW: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
};

/** Live/cached TCMB readings are real; the static fallback is a fixed reference. */
function macroProvenance(source?: string | null): string | null {
  if (source === "tcmb_api" || source === "redis_cache") return "real";
  if (source === "static_fallback") return "benchmark";
  return null;
}

const DEFAULT_SHOCK: ShockInputs = {
  usd_shock_pct: 15,
  eur_shock_pct: 15,
  interest_rate_delta_bp: 500,
  payment_delay_days: 15,
};

export function MacroStressTestCard() {
  const { t, locale } = useI18n();
  const m = t.macroStress;
  const fmtMoney = useCurrencyFormat();
  // Exchange rates are always lira per unit and need their decimals — not the
  // org-currency, whole-number money formatter.
  const fmtRate = (value: number) =>
    new Intl.NumberFormat(locale, {
      style: "currency",
      currency: "TRY",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  const fmtPct = (value: number) =>
    `%${new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value)}`;

  const [macro, setMacro] = useState<TcmbSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [shock, setShock] = useState<ShockInputs>(DEFAULT_SHOCK);
  const [response, setResponse] = useState<StressResponse | null>(null);
  const [failed, setFailed] = useState(false);
  // Slider drags fire overlapping requests; only the latest may land.
  const requestSeq = useRef(0);

  const fetchMacro = useCallback(async () => {
    setLoading(true);
    try {
      setMacro(await getTcmbSnapshot());
    } catch (err) {
      console.error("TCMB macro fetch failed", err);
    } finally {
      setLoading(false);
    }
  }, []);

  const runSimulation = useCallback(async (inputs: ShockInputs) => {
    const seq = ++requestSeq.current;
    try {
      const res = await simulateMacroShock(inputs);
      if (seq !== requestSeq.current) return;
      setResponse(res);
      setFailed(false);
    } catch (err) {
      if (seq !== requestSeq.current) return;
      console.error("Simulation failed", err);
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void fetchMacro();
    void runSimulation(DEFAULT_SHOCK);
  }, [fetchMacro, runSimulation]);

  const update = (patch: Partial<ShockInputs>) => {
    const next = { ...shock, ...patch };
    setShock(next);
    void runSimulation(next);
  };

  const result = response?.simulation_result ?? null;
  const riskKey = (result?.risk_level ?? "") as RiskKey;
  const riskLabel = m.risk[riskKey] ?? result?.risk_level;
  const recs = (result?.recommendations ?? [])
    .map((code) => m.recs[code as RecKey])
    .filter((text): text is string => Boolean(text));

  const tickers = [
    { label: m.usdTry, icon: DollarSign, value: macro ? fmtRate(macro.usd_try) : "—" },
    { label: m.eurTry, icon: Euro, value: macro ? fmtRate(macro.eur_try) : "—" },
    { label: m.policyRate, icon: Percent, value: macro ? fmtPct(macro.policy_rate_pct) : "—" },
    { label: m.inflation, icon: Percent, value: macro ? fmtPct(macro.inflation_pct) : "—" },
  ];

  const sliders: {
    key: keyof ShockInputs;
    label: string;
    min: number;
    max: number;
    step: number;
    display: string;
  }[] = [
    { key: "usd_shock_pct", label: m.usdShock, min: 0, max: 50, step: 5, display: `+${shock.usd_shock_pct}%` },
    { key: "eur_shock_pct", label: m.eurShock, min: 0, max: 50, step: 5, display: `+${shock.eur_shock_pct}%` },
    {
      key: "interest_rate_delta_bp",
      label: m.rateDelta,
      min: -500,
      max: 2000,
      step: 100,
      display: shock.interest_rate_delta_bp >= 0
        ? `+${shock.interest_rate_delta_bp} bp`
        : `${shock.interest_rate_delta_bp} bp`,
    },
    {
      key: "payment_delay_days",
      label: m.delayDays,
      min: 0,
      max: 60,
      step: 5,
      display: m.daysValue.replace("{n}", String(shock.payment_delay_days)),
    },
  ];

  return (
    <div className="rounded-lg border border-border bg-card p-6 shadow-sm">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between pb-4 border-b border-border gap-2">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded bg-secondary/80 border border-border text-foreground">
            <TrendingUp className="h-4 w-4" />
          </div>
          <div>
            <h3 className="font-semibold text-base text-foreground flex flex-wrap items-center gap-2">
              {m.title}
              <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-secondary border border-border text-muted-foreground">
                {m.sourceTag}
              </span>
              <ProvenanceBadge dataSource={macroProvenance(macro?.data_source)} />
            </h3>
            <p className="text-xs text-muted-foreground">{m.subtitle}</p>
          </div>
        </div>
        <button
          onClick={() => void fetchMacro()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors self-start sm:self-auto font-mono"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
          {m.refresh}
        </button>
      </div>

      {/* TCMB tickers */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 my-4">
        {tickers.map(({ label, icon: Icon, value }) => (
          <div key={label} className="rounded bg-secondary/40 p-3 border border-border">
            <div className="text-[11px] font-mono uppercase text-muted-foreground flex items-center gap-1.5">
              <Icon className="h-3 w-3 text-muted-foreground" /> {label}
            </div>
            <div className="text-lg font-bold font-mono tabular-nums mt-1 text-foreground">{value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 pt-2">
        {/* Sliders */}
        <div className="lg:col-span-6 space-y-4 rounded bg-secondary/30 p-4 border border-border">
          <div className="text-xs font-mono uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
            <Sliders className="h-3.5 w-3.5 text-muted-foreground" />
            {m.paramsTitle}
          </div>
          {sliders.map((s) => (
            <div key={s.key} className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <label htmlFor={`stress-${s.key}`} className="text-muted-foreground">{s.label}</label>
                <span className="font-mono font-semibold text-foreground">{s.display}</span>
              </div>
              <input
                id={`stress-${s.key}`}
                type="range"
                min={s.min}
                max={s.max}
                step={s.step}
                value={shock[s.key]}
                onChange={(e) => update({ [s.key]: Number(e.target.value) })}
                className="w-full h-1.5 bg-secondary rounded appearance-none cursor-pointer accent-foreground"
              />
            </div>
          ))}
        </div>

        {/* Output */}
        <div className="lg:col-span-6 space-y-4">
          {failed && !response && (
            <output className="block text-xs text-muted-foreground">{m.loadError}</output>
          )}

          {response && !result && (
            <output className="block rounded bg-secondary/30 p-4 border border-border text-xs text-muted-foreground">
              {m.noBaseline}
            </output>
          )}

          {result && (
            <div className="rounded bg-secondary/30 p-4 border border-border space-y-3">
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-xs font-mono uppercase tracking-wider text-muted-foreground">
                  {m.outputTitle}
                  <ProvenanceBadge dataSource={result.data_source} basis={m.estimateBasis} />
                </span>
                <span
                  className={`text-[11px] font-mono uppercase px-2 py-0.5 rounded border ${
                    RISK_STYLES[riskKey] ?? RISK_STYLES.MODERATE
                  }`}
                >
                  {riskLabel}
                </span>
              </div>

              <div className="flex items-baseline justify-between pt-1">
                <div>
                  <div className="text-xs text-muted-foreground">{m.stressedRunway}</div>
                  <div className="text-2xl font-bold font-mono tabular-nums text-foreground mt-0.5">
                    {result.stressed_runway_months === null
                      ? m.noRunwayLimit
                      : m.monthsValue.replace("{n}", String(result.stressed_runway_months))}
                  </div>
                </div>
                {result.runway_delta_months !== null && (
                  <div className="text-right">
                    <div className="text-xs text-muted-foreground">{m.runwayDelta}</div>
                    <div className="text-base font-bold font-mono tabular-nums text-red-400">
                      {m.monthsValue.replace("{n}", String(result.runway_delta_months))}
                    </div>
                  </div>
                )}
              </div>

              {result.risk_level === "CASH_NEGATIVE" && (
                <p className="text-xs text-red-400">{m.cashTurnsNegative}</p>
              )}

              <div className="flex items-center justify-between pt-2 border-t border-border text-xs">
                <span className="text-muted-foreground">{m.monthlyIncrease}</span>
                <span className="font-bold font-mono tabular-nums text-foreground">
                  +{fmtMoney(result.monthly_cost_increase_lira)} {m.perMonth}
                </span>
              </div>

              {recs.length > 0 && (
                <div className="pt-2 border-t border-border">
                  <div className="text-xs font-semibold text-foreground mb-1.5">{m.recsTitle}</div>
                  <ul className="space-y-1 text-xs text-muted-foreground">
                    {recs.slice(0, 2).map((rec) => (
                      <li key={rec} className="flex items-start gap-1.5">
                        <ArrowRight className="h-3 w-3 text-muted-foreground mt-0.5 shrink-0" />
                        <span>{rec}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <p className="pt-2 border-t border-border text-[11px] text-muted-foreground">
                {m.assumptionsNote
                  .replace("{fx}", String(Math.round((result.assumptions.fx_exposure_ratio ?? 0) * 100)))
                  .replace("{debt}", String(result.assumptions.working_capital_debt_months ?? "—"))
                  .replace("{months}", String(result.months_observed))}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
