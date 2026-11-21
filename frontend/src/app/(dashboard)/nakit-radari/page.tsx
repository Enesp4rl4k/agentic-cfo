"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Calendar, ShieldCheck } from "lucide-react";
import { Card } from "@/components/ui/card";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { useI18n } from "@/hooks/useI18n";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import {
  getCashRadar,
  getMondayBriefing,
  respondToMondayBriefing,
  type CashRadar,
  type RadarWeek,
} from "@/lib/api/ledger";
import { cn, formatCurrency } from "@/lib/utils";
import { BaseCurrencyNotice } from "@/components/ui/other-currency-lines";
import { WhatIfRadarPanel } from "@/components/simulation/WhatIfRadarPanel";
import { ConsolidatedRadarView } from "@/components/consolidation/ConsolidatedRadarView";
import { getConsolidatedRadar } from "@/lib/api/consolidation";
import { OodaFooter } from "@/components/brand-app/OodaFooter";
import { RadarCurve } from "@/components/radar/RadarCurve";
import { RadarAnswer } from "@/components/radar/RadarAnswer";
import { WeekDetail } from "@/components/radar/WeekDetail";
import { HeldRowsLink } from "@/components/held-rows/HeldRowsLink";
import { BasisSplitLine, formatDay, hasUnverifiedTax, StaleBalanceNotice, TaxRulesNote } from "@/components/radar/basis";

const RADAR_KEY = ["cash-radar"];
const BRIEFING_KEY = ["monday-briefing"];

type Copy = ReturnType<typeof useI18n>["t"]["cashRadar"];
type Fmt = (value: number) => string;

function MondayBriefingSection({ copy }: { copy: Copy }) {
  const [recordedDecision, setRecordedDecision] = useState<string | null>(null);
  const { data: briefing, isLoading } = useQuery({
    queryKey: BRIEFING_KEY,
    queryFn: () => getMondayBriefing(),
  });

  const respondMutation = useMutation({
    // The answer carries the briefing it is about: its week and fingerprint.
    mutationFn: (resp: "done" | "deferred" | "dismissed") => {
      if (!briefing) throw new Error("briefing not loaded");
      return respondToMondayBriefing(resp, briefing.week_start, briefing.fingerprint);
    },
    onSuccess: (data) => {
      setRecordedDecision(data.chosen_option_label);
    },
  });

  if (isLoading) {
    return (
      <Card className="border-primary/20 bg-primary/5 p-4">
        <p className="text-sm text-muted-foreground">{copy.briefingLoading}</p>
      </Card>
    );
  }

  if (!briefing) return null;

  return (
    <Card className="space-y-4 border-primary/30 bg-primary/5 p-4 sm:p-5" role="region">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-3">
        <div className="flex items-center gap-2">
          <Calendar className="h-5 w-5 text-primary" aria-hidden="true" />
          <h2 className="text-base font-semibold">{copy.briefingTitle}</h2>
        </div>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-400">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
          {copy.briefingVerified}
        </span>
      </div>

      <p className="text-sm font-normal leading-relaxed text-foreground">
        {briefing.full_text}
      </p>

      {briefing.action_title && (
        <div className="space-y-2 rounded-lg border border-border/60 bg-background/80 p-3 sm:p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {copy.briefingActionLabel}
            </span>
          </div>
          <p className="text-sm font-medium text-foreground">{briefing.action_title}</p>
          <p className="text-xs text-muted-foreground">{briefing.action_detail}</p>

          <div className="pt-2">
            {recordedDecision ? (
              <p className="text-xs font-medium text-emerald-600 dark:text-emerald-400">
                {copy.briefingRecorded} <span className="font-semibold">{recordedDecision}</span>
              </p>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={respondMutation.isPending}
                  onClick={() => respondMutation.mutate("done")}
                  className="inline-flex min-h-[44px] items-center rounded-md bg-emerald-700 px-4 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-emerald-800 disabled:opacity-50"
                >
                  {copy.briefingBtnDone}
                </button>
                <button
                  type="button"
                  disabled={respondMutation.isPending}
                  onClick={() => respondMutation.mutate("deferred")}
                  className="inline-flex min-h-[44px] items-center rounded-md border border-border bg-background px-4 py-1.5 text-sm font-medium text-foreground hover:bg-accent disabled:opacity-50"
                >
                  {copy.briefingBtnDefer}
                </button>
                <button
                  type="button"
                  disabled={respondMutation.isPending}
                  onClick={() => respondMutation.mutate("dismissed")}
                  className="inline-flex min-h-[44px] items-center rounded-md px-4 py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground disabled:opacity-50"
                >
                  {copy.briefingBtnDismiss}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

function StartingCash({ radar, copy, fmt, locale }: { radar: CashRadar; copy: Copy; fmt: Fmt; locale: string }) {
  if (radar.starting_cash_cents === null) {
    return (
      <Card className="space-y-1 p-4">
        <p className="text-sm font-semibold">{copy.unknownCash}</p>
        <p className="text-xs text-muted-foreground">{copy.unknownCashBody}</p>
      </Card>
    );
  }
  const opening = radar.opening_cash;
  return (
    <div className="space-y-2">
      <Card className="p-4">
        <dl className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-xs text-muted-foreground">{copy.startingCash}</dt>
            <dd className="text-lg font-semibold tabular-nums">{fmt(radar.starting_cash_cents / 100)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">{copy.asOf}</dt>
            <dd className="font-medium">
              {opening ? copy.cashAsOf.replace("{date}", formatDay(opening.as_of, locale)) : radar.starting_cash_as_of}
            </dd>
          </div>
        </dl>
      </Card>
      {opening?.stale && <StaleBalanceNotice asOf={opening.as_of} ageDays={opening.age_days} locale={locale} />}
    </div>
  );
}

function Shortfall({ radar, copy, fmt }: { radar: CashRadar; copy: Copy; fmt: Fmt }) {
  const gap = radar.shortfall;
  if (gap === null) {
    // No gap is only a claim when a balance was proven.
    return radar.starting_cash_cents === null ? null : (
      <p className="text-sm text-muted-foreground">{copy.noGap}</p>
    );
  }
  return (
    <Card className="space-y-3 border-destructive/40 p-4" role="alert">
      <p className="text-sm font-semibold text-destructive">{copy.gapTitle}</p>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">{copy.gapWeek}</dt>
          <dd className="font-medium tabular-nums">{gap.week} ({gap.week_start} – {gap.week_end})</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">{copy.gapLowest}</dt>
          <dd className="font-medium tabular-nums">{fmt(-gap.shortfall_cents / 100)}</dd>
        </div>
      </dl>
      <p className="text-sm">{gap.driver}</p>
      <div>
        <p className="text-xs font-medium text-muted-foreground">{copy.gapActions}</p>
        <ul className="mt-1 space-y-2">
          {gap.actions.map((action) => (
            <li key={action.type} className="text-sm">
              <p className="font-medium">{action.title}</p>
              <p className="text-xs text-muted-foreground">{action.detail}</p>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

function WeekRow({
  week,
  known,
  gapWeek,
  selected,
  onSelect,
  pickLabel,
  copy,
  fmt,
}: {
  week: RadarWeek;
  known: boolean;
  gapWeek: number | null;
  selected: boolean;
  onSelect: (week: number) => void;
  pickLabel: string;
  copy: Copy;
  fmt: Fmt;
}) {
  const below = known && week.end_balance_cents < 0;
  return (
    <tr className={cn("border-t border-border", gapWeek === week.week && "bg-destructive/5", selected && "bg-muted")}>
      <td className="px-3 py-1 tabular-nums">
        <button
          type="button"
          onClick={() => onSelect(week.week)}
          aria-pressed={selected}
          aria-label={pickLabel}
          className="inline-flex min-h-[36px] min-w-[36px] items-center justify-center rounded-md px-2 font-medium hover:bg-muted"
        >
          {week.week}
        </button>
      </td>
      <td className="px-3 py-2 text-xs text-muted-foreground tabular-nums">{week.start_date} – {week.end_date}</td>
      <td className="px-3 py-2 text-right tabular-nums">
        {week.inflow_cents ? fmt(week.inflow_cents / 100) : "–"}
        <BasisSplitLine split={week.inflow_basis} copy={copy} fmt={fmt} />
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {week.outflow_cents ? fmt(week.outflow_cents / 100) : "–"}
        <BasisSplitLine split={week.outflow_basis} copy={copy} fmt={fmt} />
      </td>
      <td className={cn("px-3 py-2 text-right font-medium tabular-nums", below && "text-destructive")}>
        {fmt(week.end_balance_cents / 100)}
      </td>
    </tr>
  );
}

function Weeks({
  radar,
  copy,
  fmt,
  selected,
  onSelect,
}: {
  radar: CashRadar;
  copy: Copy;
  fmt: Fmt;
  selected: number | null;
  onSelect: (week: number) => void;
}) {
  const known = radar.starting_cash_cents !== null;
  return (
    <Card className="overflow-x-auto p-0">
      <p className="px-4 pt-4 text-sm font-semibold">{copy.weekly}</p>
      <table className="mt-2 w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="px-3 py-2 font-medium">{copy.colWeek}</th>
            <th className="px-3 py-2 font-medium">{copy.colDates}</th>
            <th className="px-3 py-2 text-right font-medium">{copy.colIn}</th>
            <th className="px-3 py-2 text-right font-medium">{copy.colOut}</th>
            <th className="px-3 py-2 text-right font-medium">{known ? copy.colBalance : copy.colMovement}</th>
          </tr>
        </thead>
        <tbody>
          {radar.weeks.map((week) => (
            <WeekRow
              key={week.week}
              week={week}
              known={known}
              gapWeek={radar.shortfall?.week ?? null}
              selected={selected === week.week}
              onSelect={onSelect}
              pickLabel={copy.weekPick.replace("{week}", String(week.week))}
              copy={copy}
              fmt={fmt}
            />
          ))}
        </tbody>
      </table>
      {radar.weeks.some((w) => hasUnverifiedTax(w.payables)) && (
        <div className="px-4 pb-4">
          <TaxRulesNote copy={copy} />
        </div>
      )}
    </Card>
  );
}

function NotCounted({ radar, copy, fmt }: { radar: CashRadar; copy: Copy; fmt: Fmt }) {
  const amounts: [string, number][] = [
    [copy.undatedReceivables, radar.undated_receivables_cents],
    [copy.undatedPayables, radar.undated_payables_cents],
    [copy.beyondHorizon, radar.beyond_horizon_cents],
  ];
  return (
    <Card className="space-y-2 p-4">
      <p className="text-sm font-semibold">{copy.notCountedTitle}</p>
      <ul className="list-inside list-disc space-y-1 text-sm text-muted-foreground">
        {radar.not_included.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <HeldRowsLink />
      <dl className="space-y-1 text-sm">
        {amounts
          .filter(([, cents]) => cents > 0)
          .map(([label, cents]) => (
            <div key={label} className="flex justify-between gap-3">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="font-medium tabular-nums">{fmt(cents / 100)}</dd>
            </div>
          ))}
        {radar.other_currency_items > 0 && (
          <div className="flex justify-between gap-3">
            <dt className="text-muted-foreground">{copy.otherCurrency}</dt>
            <dd className="font-medium tabular-nums">{radar.other_currency_items}</dd>
          </div>
        )}
      </dl>
      {radar.overdue_receivables.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground">{copy.overdueReceivables}</p>
          <ul className="mt-1 space-y-1 text-sm">
            {radar.overdue_receivables.map((item) => (
              <li key={item.id} className="flex justify-between gap-3">
                <span>{item.counterparty} <span className="text-xs text-muted-foreground">({copy.expectedOn} {item.expected_date})</span></span>
                <span className="font-medium tabular-nums">{fmt(item.amount_cents / 100)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function isEmpty(radar: CashRadar): boolean {
  return (
    radar.starting_cash_cents === null &&
    radar.weeks.every((w) => !w.inflow_cents && !w.outflow_cents) &&
    radar.overdue_receivables.length === 0 &&
    radar.undated_receivables_cents + radar.undated_payables_cents + radar.beyond_horizon_cents === 0
  );
}

/** The week to open first: the gap's week, otherwise the week the route is lowest. */
function defaultWeek(radar: CashRadar): number | null {
  if (radar.shortfall) return radar.shortfall.week;
  if (radar.weeks.length === 0) return null;
  return radar.weeks.reduce((low, w) => (w.end_balance_cents < low.end_balance_cents ? w : low), radar.weeks[0]).week;
}

function Headline({ radar, copy, fmt }: { radar: CashRadar; copy: Copy; fmt: Fmt }) {
  if (radar.weeks.length === 0) return null;
  const known = radar.starting_cash_cents !== null;
  const lowest = Math.min(...radar.weeks.map((w) => w.end_balance_cents));
  const last = radar.weeks[radar.weeks.length - 1].end_balance_cents;
  const tone = (cents: number) => (known && cents < 0 ? "text-destructive" : "text-foreground");
  return (
    <div className="flex flex-wrap gap-6">
      <div className="flex flex-col">
        <span className="text-[12.5px] text-muted-foreground">{known ? copy.lowestCash : copy.lowestMovement}</span>
        <span className={cn("tc-mono text-[22px]", tone(lowest))}>{fmt(lowest / 100)}</span>
      </div>
      <div className="flex flex-col">
        <span className="text-[12.5px] text-muted-foreground">{copy.periodEnd}</span>
        <span className={cn("tc-mono text-[22px]", tone(last))}>{fmt(last / 100)}</span>
      </div>
    </div>
  );
}

export default function NakitRadariPage() {
  const { t } = useI18n();
  const copy = t.cashRadar;
  const orgFmt = useCurrencyFormat();
  const { org } = useOrgSettings();
  const locale = org?.locale || "en-US";
  const [viewMode, setViewMode] = useState<"individual" | "consolidated">("individual");
  const [pickedWeek, setPickedWeek] = useState<number | null>(null);

  const { data: radar, isLoading, isError } = useQuery({ queryKey: RADAR_KEY, queryFn: getCashRadar });
  // The radar is in the same effective currency as the P&L (backend `effective_base`), not the column default.
  const fmt: Fmt = (value) => (radar?.currency ? formatCurrency(value, radar.currency, locale) : orgFmt(value));
  const { data: consolidatedRadar } = useQuery({
    queryKey: ["consolidated-radar"],
    queryFn: () => getConsolidatedRadar([]),
    enabled: viewMode === "consolidated",
  });

  const selectedWeek =
    radar && pickedWeek !== null && radar.weeks.some((w) => w.week === pickedWeek)
      ? pickedWeek
      : radar
        ? defaultWeek(radar)
        : null;
  const detailWeek = radar?.weeks.find((w) => w.week === selectedWeek) ?? null;
  const period =
    radar && radar.weeks.length > 0
      ? `${radar.weeks[0].start_date} – ${radar.weeks[radar.weeks.length - 1].end_date}`
      : null;

  return (
      <div className="mx-auto max-w-5xl space-y-5 p-4 sm:p-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-col gap-1.5">
            {period && <span className="tc-eyebrow text-muted-foreground">{period}</span>}
            <h1 className="tc-display m-0 text-4xl leading-[1.05] sm:text-[44px]">{copy.title}</h1>
            <p className="m-0 text-sm text-muted-foreground">{copy.subtitle}</p>
          </div>
          {viewMode === "individual" && radar && !isEmpty(radar) && <Headline radar={radar} copy={copy} fmt={fmt} />}
        </div>
        {radar && <BaseCurrencyNotice state={radar.base_state} base={radar.currency} />}

        <div className="flex w-fit items-center rounded-lg border border-border bg-muted/40 p-1">
          {(["individual", "consolidated"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setViewMode(mode)}
              aria-pressed={viewMode === mode}
              className={cn(
                "min-h-[36px] rounded-md px-3 py-1 text-xs font-medium transition-colors",
                viewMode === mode ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {mode === "individual" ? copy.grpToggleIndividual : copy.grpToggleConsolidated}
            </button>
          ))}
        </div>

        {isLoading && <p className="text-sm text-muted-foreground">{copy.loading}</p>}
        {isError && <p className="text-sm text-destructive">{copy.failed}</p>}

        {viewMode === "consolidated" && consolidatedRadar && (
          <ConsolidatedRadarView radar={consolidatedRadar} copy={copy} fmt={fmt} />
        )}

        {viewMode === "individual" && radar && (
          <>
            {!isEmpty(radar) && <RadarAnswer radar={radar} copy={copy} fmt={fmt} locale={locale} />}
            <MondayBriefingSection copy={copy} />
            <StartingCash radar={radar} copy={copy} fmt={fmt} locale={locale} />
            {isEmpty(radar) ? (
              <Card className="space-y-2 p-4">
                <p className="text-sm text-muted-foreground">{copy.emptyBody}</p>
                <Link href="/baglan" className="text-sm font-medium text-primary underline-offset-4 hover:underline">
                  {copy.connect}
                </Link>
              </Card>
            ) : (
              <>
                <Card className="overflow-x-auto p-5">
                  <RadarCurve
                    weeks={radar.weeks}
                    known={radar.starting_cash_cents !== null}
                    selected={selectedWeek}
                    onSelect={setPickedWeek}
                    copy={copy}
                    fmt={fmt}
                    locale={locale}
                  />
                </Card>
                <Shortfall radar={radar} copy={copy} fmt={fmt} />
                <WhatIfRadarPanel copy={copy} fmt={fmt} />
                <div className="flex flex-wrap items-start gap-4">
                  <div className="min-w-0 flex-[999_1_520px]">
                    <Weeks radar={radar} copy={copy} fmt={fmt} selected={selectedWeek} onSelect={setPickedWeek} />
                  </div>
                  {detailWeek && (
                    <div className="min-w-0 flex-[1_1_320px]">
                      <WeekDetail week={detailWeek} copy={copy} fmt={fmt} locale={locale} />
                    </div>
                  )}
                </div>
                <NotCounted radar={radar} copy={copy} fmt={fmt} />
              </>
            )}
          </>
        )}
        <OodaFooter current={1} />
      </div>
  );
}
