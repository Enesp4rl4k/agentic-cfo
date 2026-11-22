"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { useCallback } from "react";
import { apiClient } from "@/lib/api/client";
import { effectiveCurrencyOf } from "@/lib/effective-currency";

export type OrgSettings = {
  org_id: string;
  name: string;
  locale?: string;
  base_currency?: string;
  /** The stored `base_currency` is a column default until an owner confirms it. */
  base_currency_confirmed?: boolean;
  /** The currency money is labelled in (backend `effective_base`); null when several are present and none confirmed. */
  effective_currency?: string | null;
  base_state?: string;
  country_code?: string;
  regional_packs?: string[];
  focus_mode?: boolean;
  size_profile?: "micro" | "small" | "medium" | null;
};

export const ORG_SETTINGS_KEY = ["org-settings"] as const;

async function fetchOrgSettings(): Promise<OrgSettings | null> {
  const res = await apiClient.get("/org/me");
  return (res.data?.data ?? res.data ?? null) as OrgSettings | null;
}

/**
 * The organisation the current user belongs to.
 *
 * Backed by React Query on a fixed key, so every component that asks shares one
 * request. It used to hold its own `useState` + `useEffect`, which meant a fetch
 * per calling component — and since `useI18n` calls this hook, every
 * locale-aware component added another. A page load fired `/org/me` eight or
 * nine times; across a full page sweep that was enough to trip the API's rate
 * limiter, at which point the 429s came back without CORS headers and the
 * browser reported them as opaque CORS failures.
 *
 * The org changes rarely, so it is cached for a minute and not refetched on
 * window focus. `refresh()` invalidates it after a settings change.
 *
 * Only fetched with an authenticated session: on public pages (login, landing)
 * a visitor has no org, and an unauthenticated `/org/me` 401 makes apiClient
 * sign out and redirect to the login page — which, rendered by a locale-aware
 * component there, asked again: an endless reload loop. Without a session the
 * org is simply `null` and the locale falls back to cookie/browser detection.
 */
export function useOrgSettings() {
  const qc = useQueryClient();
  const { status } = useSession();

  const { data, isLoading, error } = useQuery<OrgSettings | null>({
    queryKey: ORG_SETTINGS_KEY,
    queryFn: fetchOrgSettings,
    enabled: status === "authenticated",
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const refresh = useCallback(
    () => qc.invalidateQueries({ queryKey: ORG_SETTINGS_KEY }),
    [qc],
  );

  const org = data ?? null;

  return {
    org,
    loading: status === "loading" || (status === "authenticated" && isLoading),
    error: error instanceof Error ? error.message : null,
    refresh,
    hasTrPack: Boolean(org?.regional_packs?.includes("tr")),
    focusMode: Boolean(org?.focus_mode),
    sizeProfile: org?.size_profile ?? null,
    baseCurrency: effectiveCurrencyOf(org),
    locale: org?.locale || "tr-TR",
  };
}
