"use client";

import { useQuery } from "@tanstack/react-query";
import { getReviewQueue } from "@/lib/api/agentReview";
import { listHeldAnalyses } from "@/lib/api/heldAnalyses";
import { listHeldRows } from "@/lib/api/heldRows";
import { getPossibleDuplicates, getProposedSettlements } from "@/lib/api/ledger";
import { listPlanChanges } from "@/lib/api/planChanges";

// The query keys are the ones the approvals screen (/onay) and its sections use, so the screen, the
// menu badge and the setup page share one fetch and refresh together when a decision is made.
export const WAITING_KEYS = {
  analyses: ["held-analyses"],
  rows: ["held-rows", "all"],
  duplicates: ["ledger-duplicates"],
  settlements: ["ledger-settlements"],
  plans: ["plan-changes", "pending"],
  agents: ["agent-review-queue"],
} as const;

export type WaitingCounts = {
  analyses: number;
  rows: number;
  duplicates: number;
  settlements: number;
  plans: number;
  agents: number;
  total: number;
  /** Some kind has not answered yet: "nothing waits" is not yet known. */
  loading: boolean;
};

/**
 * How many decisions wait for this person, by kind. A kind that cannot be read (a role without access, a
 * network error) counts as zero: this is a pointer to the approvals screen, which shows the real state.
 */
export function useWaitingCounts(enabled = true): WaitingCounts {
  const options = { enabled, staleTime: 30_000, retry: false, refetchOnWindowFocus: false } as const;
  const analyses = useQuery({ queryKey: WAITING_KEYS.analyses, queryFn: listHeldAnalyses, ...options });
  const rows = useQuery({ queryKey: WAITING_KEYS.rows, queryFn: () => listHeldRows(), ...options });
  const duplicates = useQuery({ queryKey: WAITING_KEYS.duplicates, queryFn: getPossibleDuplicates, ...options });
  const settlements = useQuery({ queryKey: WAITING_KEYS.settlements, queryFn: getProposedSettlements, ...options });
  const plans = useQuery({ queryKey: WAITING_KEYS.plans, queryFn: () => listPlanChanges("pending"), ...options });
  const agents = useQuery({ queryKey: WAITING_KEYS.agents, queryFn: getReviewQueue, ...options });

  const counts = {
    analyses: analyses.data?.length ?? 0,
    rows: rows.data?.length ?? 0,
    duplicates: duplicates.data?.length ?? 0,
    settlements: settlements.data?.length ?? 0,
    plans: plans.data?.changes.length ?? 0,
    agents: agents.data?.length ?? 0,
  };
  const loading = [analyses, rows, duplicates, settlements, plans, agents].some((q) => q.isLoading);
  return { ...counts, total: Object.values(counts).reduce((a, b) => a + b, 0), loading };
}
