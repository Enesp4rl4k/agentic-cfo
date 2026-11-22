"use client";

import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { useI18n } from "@/hooks/useI18n";
import { apiClient } from "@/lib/api/client";
import { ACTION_CLASS, canClosePeriod, hasRoleClass, type GatedAction } from "@/lib/roles";

export type Can = {
  allowed: boolean;
  /** Why not, in the user's language; null when allowed. */
  reason: string | null;
  /** An explanation that applies even when allowed (which month-close case this is). */
  note: string | null;
};

type Member = { role: string; is_active?: boolean };

/** Whether the company has an accountant (`smmm` member); null while unknown. Any member may read the list. */
function useHasSmmm(enabled: boolean): boolean | null {
  const { data } = useQuery<boolean | null>({
    queryKey: ["org-has-smmm"],
    enabled,
    staleTime: 60_000,
    retry: false,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const res = await apiClient.get("/org/members");
      const members = (res.data?.data?.members ?? []) as Member[];
      return members.some((m) => m.role === "smmm" && m.is_active !== false);
    },
  });
  return data ?? null;
}

/**
 * May the signed-in role do `action`? The browser's answer is a courtesy: the
 * server is the gate and a 403 that still happens is shown (`lib/forbidden.ts`).
 * While the session loads nothing is claimed either way (allowed, no reason),
 * so a control does not flash disabled.
 */
export function useCan(action: GatedAction): Can {
  const { data, status } = useSession();
  const { t } = useI18n();
  const g = t.roleGate;
  const role = data?.user?.role;
  const needsSmmm = (action === "closePeriod" || action === "accountant") && (role === "owner" || role === "admin" || role === "cfo");
  const hasSmmm = useHasSmmm(needsSmmm);

  if (status === "loading") return { allowed: true, reason: null, note: null };

  if (action === "closePeriod" || action === "accountant") {
    const v = canClosePeriod(role, hasSmmm);
    const text = action === "closePeriod" ? g.closePeriod[v.case] : g.accountantAct[v.case];
    const note = action === "closePeriod" && (v.case === "accountant" || v.case === "ownBooks") ? text : null;
    return { allowed: v.allowed, reason: v.allowed ? null : text, note };
  }

  const allowed = hasRoleClass(role, ACTION_CLASS[action]);
  // The accountant gets her own sentence: she may advise on a payment date, the company decides it.
  const needPropose = role === "smmm" ? g.needProposeAccountant : g.needContribute;
  const reason = {
    upload: g.needContribute, analyze: g.needContribute, edit: g.needWrite, decide: g.needDecide, propose: needPropose,
  }[action];
  return { allowed, reason: allowed ? null : reason, note: null };
}
