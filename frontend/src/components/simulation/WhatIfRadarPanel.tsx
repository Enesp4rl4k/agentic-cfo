"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertCircle, Calculator, ChevronDown, ChevronUp, Sparkles } from "lucide-react";
import { Card } from "@/components/ui/card";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { useI18n } from "@/hooks/useI18n";
import {
  simulateWhatIf,
  type ScenarioItem,
  type SimulationResponse,
} from "@/lib/api/simulation";
import { cn } from "@/lib/utils";

type Copy = ReturnType<typeof useI18n>["t"]["cashRadar"];
type Fmt = (value: number) => string;

export function WhatIfRadarPanel({ copy, fmt }: { copy: Copy; fmt: Fmt }) {
  const [isOpen, setIsOpen] = useState(false);
  const [headcount, setHeadcount] = useState<number>(0);
  const [salaryLira, setSalaryLira] = useState<number>(45000);
  const [revenueShock, setRevenueShock] = useState<number>(0);
  const [deferAmountLira, setDeferAmountLira] = useState<number>(0);
  const [capexLira, setCapexLira] = useState<number>(0);

  const [simResult, setSimResult] = useState<SimulationResponse | null>(null);

  const mutation = useMutation({
    mutationFn: (scenarios: ScenarioItem[]) => simulateWhatIf(scenarios, 5000),
    onSuccess: (data) => {
      setSimResult(data);
    },
  });

  const handleSimulate = () => {
    const scenarios: ScenarioItem[] = [];

    if (headcount > 0) {
      scenarios.push({
        scenario_type: "hire_headcount",
        headcount,
        net_monthly_salary_cents: Math.round(salaryLira * 100),
        start_week: 1,
      });
    }

    if (revenueShock !== 0) {
      scenarios.push({
        scenario_type: "revenue_shock",
        percentage_change: revenueShock,
        delay_days: revenueShock < 0 ? 10 : 0,
      });
    }

    if (deferAmountLira > 0) {
      scenarios.push({
        scenario_type: "defer_payable",
        amount_cents: Math.round(deferAmountLira * 100),
        from_week: 1,
        to_week: 6,
      });
    }

    if (capexLira > 0) {
      scenarios.push({
        scenario_type: "capex_investment",
        amount_cents: Math.round(capexLira * 100),
        target_week: 3,
      });
    }

    mutation.mutate(scenarios);
  };

  const handleReset = () => {
    setHeadcount(0);
    setSalaryLira(45000);
    setRevenueShock(0);
    setDeferAmountLira(0);
    setCapexLira(0);
    setSimResult(null);
  };

  return (
    <Card className="space-y-4 border-primary/40 bg-gradient-to-b from-card to-primary/5 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-3">
        <div className="flex items-center gap-2">
          <Calculator className="h-5 w-5 text-primary" aria-hidden="true" />
          <div>
            <h2 className="text-base font-semibold">{copy.simTitle}</h2>
            <p className="text-xs text-muted-foreground">{copy.simSubtitle}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          className="inline-flex min-h-[44px] items-center gap-1 rounded-md border border-border px-3 py-1 text-xs font-medium hover:bg-accent"
        >
          {isOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          {isOpen ? copy.simHide : copy.simEdit}
        </button>
      </div>

      {isOpen && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {/* 1. İşe Alım */}
          <div className="space-y-1.5 rounded-lg border border-border/60 bg-background/50 p-3">
            <label className="text-xs font-medium text-foreground">{copy.simHireLabel}</label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min="0"
                max="20"
                value={headcount}
                onChange={(e) => setHeadcount(Number(e.target.value))}
                className="w-16 rounded border border-border bg-background px-2 py-1 text-sm tabular-nums"
              />
              <span className="text-xs text-muted-foreground">{copy.simHeadcountUnit}</span>
            </div>
            {headcount > 0 && (
              <div className="pt-1">
                <span className="text-[11px] text-muted-foreground">{copy.simNetSalaryLabel}: ₺</span>
                <input
                  type="number"
                  step="1000"
                  value={salaryLira}
                  onChange={(e) => setSalaryLira(Number(e.target.value))}
                  className="w-24 rounded border border-border bg-background px-1.5 py-0.5 text-xs tabular-nums"
                />
              </div>
            )}
          </div>

          {/* 2. Ciro Şoku */}
          <div className="space-y-1.5 rounded-lg border border-border/60 bg-background/50 p-3">
            <label className="text-xs font-medium text-foreground">{copy.simShockLabel}</label>
            <div className="flex items-center gap-2">
              <input
                type="range"
                min="-50"
                max="50"
                step="5"
                value={revenueShock}
                onChange={(e) => setRevenueShock(Number(e.target.value))}
                className="w-full accent-primary"
              />
              <span className={cn("text-xs font-semibold tabular-nums", revenueShock < 0 ? "text-destructive" : revenueShock > 0 ? "text-emerald-500" : "text-muted-foreground")}>
                %{revenueShock > 0 ? `+${revenueShock}` : revenueShock}
              </span>
            </div>
          </div>

          {/* 3. Borç Öteleme */}
          <div className="space-y-1.5 rounded-lg border border-border/60 bg-background/50 p-3">
            <label className="text-xs font-medium text-foreground">{copy.simDeferLabel}</label>
            <input
              type="number"
              step="10000"
              value={deferAmountLira}
              onChange={(e) => setDeferAmountLira(Number(e.target.value))}
              placeholder="0"
              className="w-full rounded border border-border bg-background px-2 py-1 text-sm tabular-nums"
            />
            <span className="text-[11px] text-muted-foreground">{copy.simDeferHint}</span>
          </div>

          {/* 4. Yatırım Harcaması */}
          <div className="space-y-1.5 rounded-lg border border-border/60 bg-background/50 p-3">
            <label className="text-xs font-medium text-foreground">{copy.simCapexLabel}</label>
            <input
              type="number"
              step="25000"
              value={capexLira}
              onChange={(e) => setCapexLira(Number(e.target.value))}
              placeholder="0"
              className="w-full rounded border border-border bg-background px-2 py-1 text-sm tabular-nums"
            />
            <span className="text-[11px] text-muted-foreground">{copy.simCapexHint}</span>
          </div>
        </div>
      )}

      {isOpen && (
        <div className="flex items-center justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={handleReset}
            className="min-h-[44px] rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-accent"
          >
            {copy.simBtnReset}
          </button>
          <button
            type="button"
            disabled={mutation.isPending}
            onClick={handleSimulate}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground shadow hover:bg-primary/90 disabled:opacity-50"
          >
            <Sparkles className="h-3.5 w-3.5" />
            {mutation.isPending ? copy.simCalculating : copy.simBtnSimulate}
          </button>
        </div>
      )}

      {simResult && (
        <div className="mt-4 space-y-4 rounded-lg border border-primary/30 bg-background/90 p-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-md border border-border/60 bg-muted/30 p-3">
              <span className="text-xs text-muted-foreground">{copy.simDeficitRisk}</span>
              <p
                className={cn(
                  "text-lg font-bold tabular-nums",
                  simResult.simulated.cash_deficit_probability_pct > 20
                    ? "text-destructive"
                    : "text-emerald-500"
                )}
              >
                %{simResult.simulated.cash_deficit_probability_pct}
              </p>
            </div>

            <div className="rounded-md border border-border/60 bg-muted/30 p-3">
              <span className="text-xs text-muted-foreground">{copy.simVar95}</span>
              <p className="text-lg font-bold tabular-nums">
                {fmt(simResult.simulated.var_95_cents / 100)}
              </p>
            </div>

            <div className="rounded-md border border-border/60 bg-muted/30 p-3">
              <span className="text-xs text-muted-foreground">{copy.simVolume}</span>
              <p className="text-lg font-bold tabular-nums">
                {simResult.simulated.iterations.toLocaleString()} {copy.simIterationsUnit}
              </p>
            </div>
          </div>

          {simResult.simulated.insights.length > 0 && (
            <div className="space-y-1.5 rounded-md border border-primary/20 bg-primary/5 p-3">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-primary">
                <AlertCircle className="h-4 w-4" />
                <span>{copy.simInsightsTitle}</span>
              </div>
              <ul className="list-inside list-disc space-y-1 text-xs text-foreground/90">
                {simResult.simulated.insights.map((ins, idx) => (
                  <li key={idx}>{ins}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="overflow-x-auto">
            <p className="pb-2 text-xs font-semibold text-muted-foreground">{copy.simCorridor}</p>
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th className="py-1.5 font-medium">{copy.colWeek}</th>
                  <th className="py-1.5 text-right font-medium">{copy.simBaseBalance}</th>
                  <th className="py-1.5 text-right font-medium text-destructive">{copy.simP10}</th>
                  <th className="py-1.5 text-right font-medium">{copy.simP50}</th>
                  <th className="py-1.5 text-right font-medium text-emerald-500">{copy.simP90}</th>
                  <th className="py-1.5 text-right font-medium">{copy.simDeficitRiskShort}</th>
                </tr>
              </thead>
              <tbody>
                {simResult.simulated.weeks.map((w) => (
                  <tr key={w.week} className="border-b border-border/40 hover:bg-muted/30">
                    <td className="py-1.5 tabular-nums">{w.week}. {copy.simWeekSuffix}</td>
                    <td className="py-1.5 text-right tabular-nums">{fmt(w.baseline_cents / 100)}</td>
                    <td className="py-1.5 text-right font-medium text-destructive tabular-nums">
                      {fmt(w.p10_cents / 100)}
                    </td>
                    <td className="py-1.5 text-right font-semibold tabular-nums">{fmt(w.p50_cents / 100)}</td>
                    <td className="py-1.5 text-right font-medium text-emerald-500 tabular-nums">
                      {fmt(w.p90_cents / 100)}
                    </td>
                    <td className="py-1.5 text-right font-medium tabular-nums">
                      %{w.deficit_prob_pct}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}
