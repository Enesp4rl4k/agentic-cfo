"use client";

import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { useI18n } from "@/hooks/useI18n";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import { getRadarBacktest, type RadarBacktest } from "@/lib/api/pilot";
import { cn } from "@/lib/utils";

const TIER_KEY = {
  HIGH: "tierHigh",
  MODERATE: "tierModerate",
  LOW: "tierLow",
  NO_ACTUAL: "tierNoActual",
  NO_FORECAST_SNAPSHOT: "tierNoForecastSnapshot",
  ZERO_ACTUAL: "tierZeroActual",
} as const;

const TIER_TONE: Record<RadarBacktest["accuracy_tier"], string> = {
  HIGH: "text-success",
  MODERATE: "text-warning",
  LOW: "text-destructive",
  NO_ACTUAL: "text-muted-foreground",
  NO_FORECAST_SNAPSHOT: "text-muted-foreground",
  ZERO_ACTUAL: "text-muted-foreground",
};

/**
 * The forecast scorecard: what the radar said earlier against what the ledger shows now. It speaks
 * only from a saved forecast and a proven balance; without either it names which one is missing and
 * shows no number. The tier is the backend's, not ours.
 */
export function ForecastScorecard() {
  const { t } = useI18n();
  const copy = t.reports.scorecard;
  const labels = t.pilot.radarBacktest;
  const fmt = useCurrencyFormat();
  const { org } = useOrgSettings();
  const locale = org?.locale || "tr-TR";
  const { data, isLoading, isError } = useQuery({ queryKey: ["radar-backtest"], queryFn: () => getRadarBacktest() });

  const pct = (value: number) =>
    new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1, signDisplay: "exceptZero" }).format(value / 100);
  const hasNumbers =
    data && data.projected_end_balance_cents !== null && data.actual_proven_balance_cents !== null && data.variance_cents !== null;

  return (
    <section aria-label={copy.title} className="space-y-3">
      <div className="space-y-1">
        <h2 className="tc-display m-0 text-[26px] leading-[1.1]">{copy.title}</h2>
        <p className="m-0 max-w-2xl text-sm text-muted-foreground">{copy.intro}</p>
      </div>
      {isError && <p role="alert" className="text-sm text-destructive">{copy.failed}</p>}
      {isLoading && <p className="text-sm text-muted-foreground">{t.cashRadar.loading}</p>}
      {data && (
        <Card className="space-y-3 p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="tc-mono text-sm text-muted-foreground">{data.target_date}</span>
            <span className={cn("text-sm font-medium", TIER_TONE[data.accuracy_tier])}>
              {labels[TIER_KEY[data.accuracy_tier]]}
            </span>
          </div>
          {hasNumbers ? (
            <dl className="grid grid-cols-3 gap-3 text-sm">
              <div>
                <dt className="text-xs text-muted-foreground">{labels.projected}</dt>
                <dd className="tc-mono">{fmt((data.projected_end_balance_cents as number) / 100)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{labels.actual}</dt>
                <dd className="tc-mono">{fmt((data.actual_proven_balance_cents as number) / 100)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{labels.variance}</dt>
                <dd className="tc-mono">
                  {fmt((data.variance_cents as number) / 100)}
                  {data.variance_pct !== null && <span className="text-muted-foreground"> · {pct(data.variance_pct)}</span>}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">{data.summary}</p>
          )}
        </Card>
      )}
    </section>
  );
}
