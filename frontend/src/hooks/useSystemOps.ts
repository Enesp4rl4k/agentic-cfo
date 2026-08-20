"use client";

import { useQuery } from "@tanstack/react-query";
import { getSystemHealth, getSystemOps } from "@/lib/api/system";
import { useCompanyContextStore } from "@/store/companyContext";

export const systemKeys = {
  health: ["system", "health"] as const,
  ops: (orgId?: string | null) => ["system", "ops", orgId ?? "global"] as const,
};

export function useSystemHealth() {
  return useQuery({
    queryKey: systemKeys.health,
    queryFn: getSystemHealth,
    staleTime: 20_000,
    refetchInterval: 30_000,
    retry: 1,
    refetchOnWindowFocus: false,
  });
}

export function useSystemOps() {
  const orgId = useCompanyContextStore().orgId;
  return useQuery({
    queryKey: systemKeys.ops(orgId),
    queryFn: () => getSystemOps(orgId),
    staleTime: 20_000,
    refetchInterval: (query) => {
      const data = query.state.data;
      const hasIncident =
        (data?.sla?.breaches?.length ?? 0) > 0 ||
        (data?.jobs?.awaiting_review ?? 0) > 0 ||
        (data?.management?.open_conflicts ?? 0) > 0;
      return hasIncident ? 10_000 : 30_000;
    },
    retry: 1,
    refetchOnWindowFocus: false,
  });
}
