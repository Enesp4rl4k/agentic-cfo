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
export function formatCurrency(
  value: number,
  currency: string | null,
  locale = "tr-TR",
  unknownLabel = "para birimi bilinmiyor",
): string {
  const bare = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
  if (currency === null) return bare.format(value);
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
  // A string that is not a currency code (the backend sends "?" for rows that name none): the number and
  // an explicit label, never a symbol. Guessing dollars or lira would put a wrong unit on a real amount.
  return `${bare.format(value)} (${unknownLabel})`;
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function formatMonths(value: number | null | undefined): string {
  if (value == null) return "Stable";
  return `${value} mo`;
}
