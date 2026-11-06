"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Waves } from "lucide-react";
import { Card } from "@/components/ui/card";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { useI18n } from "@/hooks/useI18n";
import { getCashRadar, type CashRadar, type RadarWeek } from "@/lib/api/ledger";
import { cn } from "@/lib/utils";

const RADAR_KEY = ["cash-radar"];

type Copy = ReturnType<typeof useI18n>["t"]["cashRadar"];
type Fmt = (value: number) => string;

function StartingCash({ radar, copy, fmt }: { radar: CashRadar; copy: Copy; fmt: Fmt }) {
  if (radar.starting_cash_cents === null) {
    return (
      <Card className="space-y-1 p-4">
        <p className="text-sm font-semibold">{copy.unknownCash}</p>
        <p className="text-xs text-muted-foreground">{copy.unknownCashBody}</p>
      </Card>
    );
  }
  return (
    <Card className="p-4">
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">{copy.startingCash}</dt>
          <dd className="text-lg font-semibold tabular-nums">{fmt(radar.starting_cash_cents / 100)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">{copy.asOf}</dt>
          <dd className="font-medium tabular-nums">{radar.starting_cash_as_of}</dd>
        </div>
      </dl>
    </Card>
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

function WeekRow({ week, known, gapWeek, fmt }: { week: RadarWeek; known: boolean; gapWeek: number | null; fmt: Fmt }) {
  const below = known && week.end_balance_cents < 0;
  return (
    <tr className={cn("border-t border-border", gapWeek === week.week && "bg-destructive/5")}>
      <td className="px-3 py-2 tabular-nums">{week.week}</td>
      <td className="px-3 py-2 text-xs text-muted-foreground tabular-nums">{week.start_date} – {week.end_date}</td>
      <td className="px-3 py-2 text-right tabular-nums">{week.inflow_cents ? fmt(week.inflow_cents / 100) : "–"}</td>
      <td className="px-3 py-2 text-right tabular-nums">{week.outflow_cents ? fmt(week.outflow_cents / 100) : "–"}</td>
      <td className={cn("px-3 py-2 text-right font-medium tabular-nums", below && "text-destructive")}>
        {fmt(week.end_balance_cents / 100)}
      </td>
    </tr>
  );
}

function Weeks({ radar, copy, fmt }: { radar: CashRadar; copy: Copy; fmt: Fmt }) {
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
            <WeekRow key={week.week} week={week} known={known} gapWeek={radar.shortfall?.week ?? null} fmt={fmt} />
          ))}
        </tbody>
      </table>
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

export default function NakitRadariPage() {
  const { t } = useI18n();
  const copy = t.cashRadar;
  const fmt = useCurrencyFormat();
  const { data: radar, isLoading, isError } = useQuery({ queryKey: RADAR_KEY, queryFn: getCashRadar });

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <Waves className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
          {copy.title}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">{copy.subtitle}</p>
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">{copy.loading}</p>}
      {isError && <p className="text-sm text-destructive">{copy.failed}</p>}
      {radar && (
        <>
          <StartingCash radar={radar} copy={copy} fmt={fmt} />
          {isEmpty(radar) ? (
            <Card className="space-y-2 p-4">
              <p className="text-sm text-muted-foreground">{copy.emptyBody}</p>
              <Link href="/baglan" className="text-sm font-medium text-primary underline-offset-4 hover:underline">
                {copy.connect}
              </Link>
            </Card>
          ) : (
            <>
              <Shortfall radar={radar} copy={copy} fmt={fmt} />
              <Weeks radar={radar} copy={copy} fmt={fmt} />
              <NotCounted radar={radar} copy={copy} fmt={fmt} />
            </>
          )}
        </>
      )}
    </div>
  );
}
