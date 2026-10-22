"use client";

import { useCallback } from "react";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import { formatCurrency } from "@/lib/utils";

/**
 * Currency formatter bound to the organisation's base currency and locale.
 *
 * The same number must never appear as `$` in one card and `₺` in another:
 * the CFO narrative, decision brief, and KPI cards all label values with the
 * org's base currency (backend `_regional_defaults`), so the interface formats
 * with the same source of truth. Falls back to en-US / USD before org settings
 * resolve — the same window in which the backend would fall back too.
 */
export function useCurrencyFormat(): (value: number) => string {
  const { org } = useOrgSettings();
  const currency = org?.base_currency || "USD";
  const locale = org?.locale || "en-US";
  return useCallback(
    (value: number) => formatCurrency(value, currency, locale),
    [currency, locale],
  );
}

/**
 * Compact axis/ticker symbol for the org's currency ("$", "₺", "€"…).
 * Chart ticks render `{symbol}30k`, so they must match the KPI cards.
 */
export function useCurrencySymbol(): string {
  const { org } = useOrgSettings();
  const currency = org?.base_currency || "USD";
  const locale = org?.locale || "en-US";
  try {
    const parts = new Intl.NumberFormat(locale, { style: "currency", currency }).formatToParts(1);
    return parts.find((p) => p.type === "currency")?.value ?? "$";
  } catch {
    return "$";
  }
}
