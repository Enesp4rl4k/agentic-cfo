"use client";
/**
 * useCompanyContext — TanStack Query hooks for Company Context API.
 *
 * Combines:
 *   - Server state (TanStack Query → /api/v1/context/me/summary)
 *   - Client state (localStorage store → active CFO job ID)
 *
 * Usage:
 *   const { summary, isLoading } = useContextSummary();
 *   const { context } = useFullContext();
 */
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getCompanyContext,
  getContextSummary,
  resetCompanyContext,
} from "@/lib/api/context";
import { useCompanyContextStore } from "@/store/companyContext";

// ── Query keys ────────────────────────────────────────────────────────────────

export const contextKeys = {
  summary: ["context", "summary"] as const,
  full:    ["context", "full"]    as const,
};

// ── Hooks ─────────────────────────────────────────────────────────────────────

/**
 * Lightweight summary — which agents have run, active jobs.
 * Refetches every 60 seconds automatically.
 */
export function useContextSummary() {
  return useQuery({
    queryKey: contextKeys.summary,
    queryFn: getContextSummary,
    staleTime: 30 * 1000,       // 30 s
    refetchInterval: 60 * 1000, // poll every 60 s
    retry: 1,
    refetchOnWindowFocus: false,
  });
}

/**
 * Full context including all agent result payloads.
 * Heavier — only fetch when needed (e.g., Command Center deep view).
 */
export function useFullContext() {
  return useQuery({
    queryKey: contextKeys.full,
    queryFn: getCompanyContext,
    staleTime: 2 * 60 * 1000,  // 2 min
    retry: 1,
    refetchOnWindowFocus: false,
  });
}


/**
 * Reset the full company context (new reporting period).
 */
export function useResetContext() {
  const qc = useQueryClient();
  const store = useCompanyContextStore();

  const mutation = useMutation({
    mutationFn: resetCompanyContext,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: contextKeys.summary });
      qc.invalidateQueries({ queryKey: contextKeys.full });
      store.clearWorkspace();
    },
  });

  return {
    resetContext: mutation.mutate,
    isResetting: mutation.isPending,
  };
}

/**
 * Convenience hook — returns the active CFO job ID from local store,
 * falling back to server context if store is empty.
 */
export function useActiveCFOJob(): string | null {
  const store = useCompanyContextStore();
  const { data: summary } = useContextSummary();

  // Local store takes precedence (set immediately after upload)
  if (store.activeCFOJobId) return store.activeCFOJobId;

  // Fall back to server context
  return summary?.active_jobs?.cfo ?? null;
}
