import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format a number as currency in the given currency and locale.
 * Org screens pass the organisation's base currency (see useCurrencyFormat);
 * the USD default keeps legacy call sites stable until they migrate.
 */
export function formatCurrency(
  value: number,
  currency = "USD",
  locale = "en-US",
  unknownLabel = "currency unknown",
): string {
  const code = currency.trim();
  if (/^[A-Za-z]{3}$/.test(code)) {
    try {
      return new Intl.NumberFormat(locale, {
        style: "currency",
        currency: code,
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      }).format(value);
    } catch {
      // fall through: a code Intl rejects is as unknown as no code
    }
  }
  // Not a currency (the backend sends "?" for rows that name none): the number, labelled, never a symbol.
  // Guessing dollars or lira here would put a wrong unit on a real amount.
  const plain = new Intl.NumberFormat(locale, { minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(value);
  return `${plain} (${unknownLabel})`;
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function formatMonths(value: number | null | undefined): string {
  if (value == null) return "Stable";
  return `${value} mo`;
}
