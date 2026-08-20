"use client";

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";

export type OrgSettings = {
  org_id: string;
  name: string;
  locale?: string;
  base_currency?: string;
  country_code?: string;
  regional_packs?: string[];
};

export function useOrgSettings() {
  const [org, setOrg] = useState<OrgSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.get("/org/me");
      const data = res.data?.data ?? res.data;
      setOrg(data as OrgSettings);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load org");
      setOrg(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const hasTrPack = Boolean(org?.regional_packs?.includes("tr"));
  const baseCurrency = org?.base_currency || "USD";
  const locale = org?.locale || "en-US";

  return { org, loading, error, refresh, hasTrPack, baseCurrency, locale };
}
