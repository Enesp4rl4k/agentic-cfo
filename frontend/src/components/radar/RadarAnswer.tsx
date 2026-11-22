"use client";

import { useI18n } from "@/hooks/useI18n";
import type { CashRadar } from "@/lib/api/ledger";
import { formatDay } from "@/components/radar/basis";

type Copy = ReturnType<typeof useI18n>["t"]["cashRadar"];

/**
 * The Monday answer as one sentence: where the route first goes negative and how
 * low it gets, or that it does not. It says nothing when no balance was proven: a
 * route without a starting balance cannot tell a gap from a missing statement.
 */
export function RadarAnswer({ radar, copy, fmt, locale }: { radar: CashRadar; copy: Copy; fmt: (v: number) => string; locale: string }) {
  if (radar.starting_cash_cents === null) return null;
  const gap = radar.shortfall;
  const text = gap
    ? copy.answerGap
        .replace("{week}", String(gap.week))
        .replace("{start}", gap.week_start)
        .replace("{end}", gap.week_end)
        .replace("{amount}", fmt(-gap.shortfall_cents / 100))
    : copy.answerClear;
  const opening = radar.opening_cash;
  return (
    <div className="space-y-1">
      <p className="tc-display m-0 max-w-3xl text-[28px] leading-[1.15] sm:text-[34px]">{text}</p>
      {/* An answer from an old statement says so where the answer is, not only further down. */}
      {opening?.stale && (
        <p className="m-0 text-sm text-muted-foreground">{copy.answerStaleCaveat.replace("{date}", formatDay(opening.as_of, locale))}</p>
      )}
    </div>
  );
}
