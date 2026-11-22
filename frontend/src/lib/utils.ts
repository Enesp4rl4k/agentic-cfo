import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format a number as currency in the given currency and locale.
 * Money screens pass the currency the data is in (see useCurrencyFormat). `null` (no currency is known)
 * formats the bare number: a symbol is a claim, and there is no default currency to fall back on.
 */
export function formatCurrency(value: number, currency: string | null, locale = "tr-TR"): string {
  const bare = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
  if (currency === null) return bare.format(value);
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    // Not an ISO 4217 code Intl knows: say the code as written rather than a symbol we invented.
    return `${bare.format(value)} ${currency}`;
  }
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function formatMonths(value: number | null | undefined): string {
  if (value == null) return "Stable";
  return `${value} mo`;
}
