"use client";

import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { DecisionList, type MemberNames } from "@/components/decisions/DecisionList";
import { useI18n } from "@/hooks/useI18n";
import { apiClient } from "@/lib/api/client";
import { listDecisionEntries } from "@/lib/api/decisionRecords";
import { isForbidden } from "@/lib/forbidden";

type Member = { user_id: string; full_name?: string | null; email: string };

/** Names of the members, for "who decided". Any member may read the list; if not, ids fall back to "Bilinmeyen üye". */
function useMemberNames(enabled: boolean): MemberNames | undefined {
  const members = useQuery({
    queryKey: ["org-members-names"],
    enabled,
    retry: false,
    staleTime: 60_000,
    queryFn: async () => {
      const res = await apiClient.get<{ data: { members: Member[] } }>("/org/members");
      return res.data.data.members;
    },
  });
  if (!enabled) return undefined;
  return Object.fromEntries((members.data ?? []).map((m) => [m.user_id, m.full_name || m.email]));
}

/**
 * "Karar geçmişi": the decisions recorded about ONE object (a settlement match, a payment-plan change,
 * a related party ...), newest first. Read-only; any member may open it (the API scopes it to the
 * company and to this one object).
 *
 * The request names the object and no kind: the server leaves out the kinds this role may not read
 * (`DECISION_READ`), so nothing a role cannot see is ever asked for. `kind` narrows an object that many
 * decisions share (the organisation itself) to the one question the screen is about. A 403 (a kind
 * the role may not read) is not an error to shout about: "Bu kayıtları görme yetkiniz yok."
 */
export function DecisionHistory({
  targetType,
  targetId,
  kind,
  names,
}: {
  targetType: string;
  targetId: string;
  kind?: string;
  names?: MemberNames;
}) {
  const { t } = useI18n();
  const d = t.decisionLog;
  const fetched = useMemberNames(names === undefined);
  const q = useQuery({
    queryKey: ["decision-history", targetType, targetId, kind ?? null],
    queryFn: () => listDecisionEntries({ targetType, targetId, kind }),
    retry: false,
  });
  return (
    <section aria-label={d.historyTitle} className="flex flex-col gap-2">
      <h3 className="m-0 text-sm font-medium">{d.historyTitle}</h3>
      {q.isLoading && <Skeleton aria-label={d.loading} className="h-12 w-full" />}
      {q.isError && isForbidden(q.error) && <p className="m-0 text-sm text-muted-foreground">{d.historyForbidden}</p>}
      {q.isError && !isForbidden(q.error) && <p role="alert" className="m-0 text-sm text-destructive">{d.historyFailed}</p>}
      {q.data && q.data.entries.length === 0 && <p className="m-0 text-sm text-muted-foreground">{d.historyEmpty}</p>}
      {q.data && q.data.entries.length > 0 && <DecisionList entries={q.data.entries} names={names ?? fetched} />}
    </section>
  );
}
