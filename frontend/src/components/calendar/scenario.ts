import type { CashRadar, RadarItem } from "@/lib/api/ledger";

/**
 * The payment calendar's scenario, as arithmetic.
 *
 * A payable moved from week `a` to week `b` keeps its money in the account until `b`: every week
 * from `a` up to (not including) `b` closes higher by the amount when it is delayed, and every week
 * from `b` up to `a` closes lower when it is brought forward. Receivables are not the company's to
 * move and are never touched. The scenario never writes anything: it is a calculation over the radar.
 */
export const WEEKS = 13;

/** Item id → the week it is moved to. */
export type Moves = Record<string, number>;

export interface PayableRef {
  id: string;
  week: number;
  amountCents: number;
  name: string | null;
  /** The date the radar expects the payment on today (ISO). */
  expectedDate: string;
  /** The radar row itself: its basis and reason are shown beside the payment. */
  item: RadarItem;
}

export function payables(radar: CashRadar): PayableRef[] {
  return radar.weeks.flatMap((w) =>
    w.payables.map((p) => ({
      id: p.id,
      week: w.week,
      amountCents: p.amount_cents,
      name: p.counterparty ?? p.description,
      expectedDate: p.expected_date,
      item: p,
    })),
  );
}

export const clampWeek = (week: number, last = WEEKS): number => Math.min(last, Math.max(1, week));

/** The week an item stands in once the moves are applied. */
export function weekOf(item: PayableRef, moves: Moves): number {
  return moves[item.id] ?? item.week;
}

export interface Scenario {
  base: number[];
  scenario: number[];
  lowBase: number;
  lowScenario: number;
}

/** Weekly closing balances (cents) with and without the moves; null when no balance was proven. */
export function runScenario(radar: CashRadar, moves: Moves): Scenario | null {
  if (radar.starting_cash_cents === null || radar.weeks.length === 0) return null;
  const items = payables(radar);
  const base = radar.weeks.map((w) => w.end_balance_cents);
  const scenario = radar.weeks.map((w) => {
    let adjusted = w.end_balance_cents;
    for (const item of items) {
      const to = moves[item.id];
      if (to === undefined || to === item.week) continue;
      adjusted += item.amountCents * ((w.week >= item.week ? 1 : 0) - (w.week >= to ? 1 : 0));
    }
    return adjusted;
  });
  return { base, scenario, lowBase: Math.min(...base), lowScenario: Math.min(...scenario) };
}

/** `iso` (YYYY-MM-DD) moved by whole weeks, in UTC so a daylight-saving change cannot shift the day. */
export function shiftDate(iso: string, weeks: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const moved = new Date(Date.UTC(y, m - 1, d + weeks * 7));
  return moved.toISOString().slice(0, 10);
}
