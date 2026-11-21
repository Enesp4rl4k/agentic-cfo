"use client";

import { useI18n } from "@/hooks/useI18n";
import type { CashRadar } from "@/lib/api/ledger";

type Copy = ReturnType<typeof useI18n>["t"]["cashRadar"];

/**
 * The Monday answer as one sentence: where the route first goes negative and how
 * low it gets, or that it does not. It says nothing when no balance was proven: a
 * route without a starting balance cannot tell a gap from a missing statement.
 */
export function RadarAnswer({ radar, copy, fmt }: { radar: CashRadar; copy: Copy; fmt: (v: number) => string }) {
  if (radar.starting_cash_cents === null) return null;
  const gap = radar.shortfall;
  const text = gap
    ? copy.answerGap
        .replace("{week}", String(gap.week))
        .replace("{start}", gap.week_start)
        .replace("{end}", gap.week_end)
        .replace("{amount}", fmt(-gap.shortfall_cents / 100))
    : copy.answerClear;
  return <p className="tc-display m-0 max-w-3xl text-[28px] leading-[1.15] sm:text-[34px]">{text}</p>;
}
