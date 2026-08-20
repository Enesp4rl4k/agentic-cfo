"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listConflicts,
  resolveConflict,
  runConsensus,
} from "@/lib/api/negotiation";
import { useCompanyContextStore } from "@/store/companyContext";

export const conflictKeys = {
  all: (orgId: string) => ["conflicts", orgId] as const,
};

export function useConflicts() {
  const orgId = useCompanyContextStore().orgId;

  return useQuery({
    queryKey: conflictKeys.all(orgId ?? "none"),
    queryFn: () => listConflicts(orgId!),
    enabled: Boolean(orgId),
    staleTime: 15_000,
    refetchInterval: (query) => {
      const count = query.state.data?.count ?? 0;
      return count > 0 ? 10_000 : 30_000;
    },
    retry: 1,
    refetchOnWindowFocus: false,
  });
}

export function useResolveConflict() {
  const qc = useQueryClient();
  const orgId = useCompanyContextStore().orgId;
  return useMutation({
    mutationFn: ({
      conflictId,
      resolution,
      note,
    }: {
      conflictId: string;
      resolution: string;
      note?: string;
    }) => resolveConflict(conflictId, resolution, note ?? ""),
    onSuccess: () => {
      if (orgId) qc.invalidateQueries({ queryKey: conflictKeys.all(orgId) });
    },
  });
}

export function useRunConsensus() {
  const qc = useQueryClient();
  const orgId = useCompanyContextStore().orgId;
  return useMutation({
    mutationFn: (topic: string) => runConsensus(topic, orgId ?? undefined),
    onSuccess: () => {
      if (orgId) qc.invalidateQueries({ queryKey: conflictKeys.all(orgId) });
    },
  });
}
