"use client";

import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { DecisionList, type MemberNames } from "@/components/decisions/DecisionList";
import { useI18n } from "@/hooks/useI18n";
import { listDecisionEntries } from "@/lib/api/decisionRecords";

/**
 * "Karar geçmişi": the decisions recorded about ONE object (a settlement match, a payment-plan change,
 * a related party ...), newest first. Read-only; any member may open it (the API scopes it to the
 * company and to this one object).
 */
export function DecisionHistory({
  targetType,
  targetId,
  names,
}: {
  targetType: string;
  targetId: string;
  names?: MemberNames;
}) {
  const { t } = useI18n();
  const d = t.decisionLog;
  const q = useQuery({
    queryKey: ["decision-history", targetType, targetId],
    queryFn: () => listDecisionEntries({ targetType, targetId }),
  });
  return (
    <section aria-label={d.historyTitle} className="flex flex-col gap-2">
      <h3 className="m-0 text-sm font-medium">{d.historyTitle}</h3>
      {q.isLoading && <Skeleton className="h-12 w-full" />}
      {q.isError && <p className="m-0 text-sm text-destructive">{d.historyFailed}</p>}
      {q.data && q.data.entries.length === 0 && <p className="m-0 text-sm text-muted-foreground">{d.historyEmpty}</p>}
      {q.data && q.data.entries.length > 0 && <DecisionList entries={q.data.entries} names={names} />}
    </section>
  );
}
