import type { OrgSettings } from "@/hooks/useOrgSettings";

/**
 * The currency this organisation's money is shown in: the backend's effective base, never the stored
 * default. A stored value counts only when the API says it was confirmed (or says nothing, as test
 * doubles do). Null: there is no single currency to label with, so none is claimed.
 */
export function effectiveCurrencyOf(org: OrgSettings | null | undefined): string | null {
  if (!org) return null;
  if (org.effective_currency) return org.effective_currency.toUpperCase();
  if (org.base_state === "ambiguous" || org.base_currency_confirmed === false) return null;
  return org.base_currency ? org.base_currency.toUpperCase() : null;
}
