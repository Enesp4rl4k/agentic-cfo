"use client";

import { createContext, createElement, useCallback, useContext, type ReactNode } from "react";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import { effectiveCurrencyOf } from "@/lib/effective-currency";
import { formatCurrency } from "@/lib/utils";

const Scope = createContext<{ currency: string | null } | null>(null);

/**
 * A screen's money is in the currency its payload states. Wrap the screen (or a section) in this and every
 * `useCurrencyFormat()` / `useCurrencySymbol()` below it follows, without threading a prop through each chart.
 * `currency` undefined (an older payload that does not say) leaves the effective-base default in force.
 */
export function CurrencyScope({ currency, children }: { currency?: string | null; children: ReactNode }) {
  if (currency === undefined) return children as never;
  return createElement(Scope.Provider, { value: { currency: currency ? currency.toUpperCase() : null } }, children);
}

function useResolved(currency: string | null | undefined): string | null {
  const { org } = useOrgSettings();
  const scope = useContext(Scope);
  if (currency !== undefined) return currency ? currency.toUpperCase() : null;
  if (scope) return scope.currency;
  return effectiveCurrencyOf(org);
}

/**
 * Currency formatter for money the system computed.
 *
 * Pass the currency the payload states (`pnl.currency`, `summary.currency`, a row's own currency): a figure is
 * written in the currency it is in. With no argument it uses the organisation's EFFECTIVE currency (backend
 * `effective_base`: the confirmed currency, else the only one present), never the stored `org.base_currency`,
 * whose column default is USD. When there is none (several currencies, none confirmed) it writes the bare number.
 */
export function useCurrencyFormat(currency?: string | null): (value: number) => string {
  const { org } = useOrgSettings();
  const code = useResolved(currency);
  const locale = org?.locale || "tr-TR";
  return useCallback((value: number) => formatCurrency(value, code, locale), [code, locale]);
}

/**
 * Compact axis/ticker symbol ("$", "₺", "€"…) for the same currency `useCurrencyFormat` would use; empty when
 * no single currency applies. Chart ticks render `{symbol}30k`, so they must match the KPI cards.
 */
export function useCurrencySymbol(currency?: string | null): string {
  const { org } = useOrgSettings();
  const code = useResolved(currency);
  const locale = org?.locale || "tr-TR";
  if (!code) return "";
  try {
    const parts = new Intl.NumberFormat(locale, { style: "currency", currency: code }).formatToParts(1);
    return parts.find((p) => p.type === "currency")?.value ?? code;
  } catch {
    return code;
  }
}

/**
 * Formatter for ledger money in kuruş/cents (an em dash for a missing value), in the organisation's effective
 * currency, or a payload-stated one. For the decision and report panels that used to write lira unconditionally.
 */
export function useCentsFormat(currency?: string | null): (cents: number | null | undefined) => string {
  const fmt = useCurrencyFormat(currency);
  return useCallback((cents) => (cents === null || cents === undefined ? "—" : fmt(cents / 100)), [fmt]);
}
