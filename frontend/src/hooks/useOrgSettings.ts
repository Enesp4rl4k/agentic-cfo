"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { apiClient } from "@/lib/api/client";

export type OrgSettings = {
  org_id: string;
  name: string;
  locale?: string;
  base_currency?: string;
  country_code?: string;
  regional_packs?: string[];
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
 */
export function useOrgSettings() {
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery<OrgSettings | null>({
    queryKey: ORG_SETTINGS_KEY,
    queryFn: fetchOrgSettings,
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
    loading: isLoading,
    error: error instanceof Error ? error.message : null,
    refresh,
    hasTrPack: Boolean(org?.regional_packs?.includes("tr")),
    baseCurrency: org?.base_currency || "USD",
    locale: org?.locale || "en-US",
  };
}
