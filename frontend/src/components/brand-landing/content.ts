/**
 * Data for the brand landing. Copy does NOT live here: every visible string is in
 * `lib/i18n/messages/{tr,en}.ts` under `brandLanding` (the U4 gate keeps new copy
 * out of components). What remains is structure and sample figures.
 *
 * The sample company's figures stay internally consistent and match the product's
 * own route and report: opening ₺612.400, lowest −₺184.200 in week 6, close
 * −₺34.200 in week 13. They are marked as samples once, in the footer line.
 */
import type { MessageTree } from "@/lib/i18n";

export type BrandLandingMessages = MessageTree["brandLanding"];

export const tabOrder = ["cevap", "rota", "onay", "rapor"] as const;
export type TabId = (typeof tabOrder)[number];

/** 13-week sample: closing cash per week in thousand TRY, index 0 = today. */
export const sampleClose: readonly number[] = [
  612.4, 498, 371, 240, 96, -42, -184.2, -150, -96, -60, -20, -48, -10, -34.2,
];

/** Sample totals over the 13 weeks, thousand TRY. */
export const sampleTotals = { collections: 1284.9, payments: 1931.5 } as const;

/** Week 6 payments, thousand TRY (sums to 238,2 = salaries + suppliers + fixed). */
export const week6Payments = { salaries: 96.0, suppliers: 50.0, fixed: 92.2 } as const;

/** The sample bank transfer awaiting approval, thousand TRY. */
export const approvalAmount = 42.8;

/** Thousand TRY → "₺184.200" / "−₺184.200" (real minus, symbol before the amount). */
export function formatTry(thousands: number): string {
  const body = Math.round(Math.abs(thousands) * 1000).toLocaleString("tr-TR");
  return `${thousands < 0 ? "−" : ""}₺${body}`;
}

/** One-decimal thousand TRY for the breakdown table: 96,0. */
export function formatThousands(thousands: number): string {
  return thousands.toFixed(1).replace(".", ",");
}

/** Point on the 1000 × 310 sample curve for week i. */
export function curvePoint(i: number, thousands: number): { x: number; y: number } {
  return {
    x: i * 76.92,
    y: Math.max(-4, Math.min(310, (700 - thousands) * 0.3158)),
  };
}

export const curvePoints = sampleClose
  .map((v, i) => {
    const p = curvePoint(i, v);
    return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
  })
  .join(" ");
