import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format a number as currency in the given currency and locale.
 * Money screens pass the currency the data is in (see useCurrencyFormat); `null` formats the bare number;
 * the USD default is only for legacy call sites that do not say.
 */
export function formatCurrency(value: number, currency: string | null = "USD", locale = "en-US"): string {
  // No currency known (several, none confirmed): the number alone, never a symbol we cannot vouch for.
  if (currency === null) {
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value);
  }
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  }
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function formatMonths(value: number | null | undefined): string {
  if (value == null) return "Stable";
  return `${value} mo`;
}
