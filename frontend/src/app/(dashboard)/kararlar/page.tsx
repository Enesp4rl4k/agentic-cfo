"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHead } from "@/components/brand-app/PageHead";
import { DecisionHistory } from "@/components/decisions/DecisionHistory";
import { DecisionList, type MemberNames } from "@/components/decisions/DecisionList";
import { useI18n } from "@/hooks/useI18n";
import { apiClient } from "@/lib/api/client";
import {
  DECISIONS_PAGE_SIZE,
  listDecisionEntries,
  type DecisionEntry,
  type DecisionFilters,
} from "@/lib/api/decisionRecords";
import { isForbidden } from "@/lib/forbidden";

type Member = { user_id: string; full_name?: string | null; email: string };

/** Company-wide decision log: who, type, date. The server refuses roles below owner/admin/cfo/smmm (403). */
export default function DecisionLogPage() {
  const { t } = useI18n();
  const d = t.decisionLog;
  const [filters, setFilters] = useState<DecisionFilters>({});
  const [page, setPage] = useState(0);
  const [object, setObject] = useState<DecisionEntry | null>(null);

  const members = useQuery({
    queryKey: ["org-members-names"],
    retry: false,
    staleTime: 60_000,
    queryFn: async () => {
      const res = await apiClient.get<{ data: { members: Member[] } }>("/org/members");
      return res.data.data.members;
    },
  });
  const names: MemberNames = Object.fromEntries(
    (members.data ?? []).map((m) => [m.user_id, m.full_name || m.email]),
  );

  const log = useQuery({
    queryKey: ["decision-log", filters, page],
    queryFn: () => listDecisionEntries(filters, page),
    retry: false,
  });
  const total = log.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / DECISIONS_PAGE_SIZE));

  const change = (patch: Partial<DecisionFilters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setPage(0);
  };
  const field = "h-9 rounded-md border border-input bg-transparent px-2 text-sm";

  return (
    <div className="flex flex-col gap-6">
      <PageHead title={d.title} subtitle={d.subtitle} />

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs">
          {d.filterKind}
          <select className={field} value={filters.kind ?? ""} onChange={(e) => change({ kind: e.target.value || undefined })}>
            <option value="">{d.allKinds}</option>
            {Object.entries(d.kinds).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          {d.filterWho}
          <select className={field} value={filters.decidedBy ?? ""} onChange={(e) => change({ decidedBy: e.target.value || undefined })}>
            <option value="">{d.everyone}</option>
            {Object.entries(names).map(([id, name]) => (
              <option key={id} value={id}>{name}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          {d.filterFrom}
          <input type="date" className={field} value={filters.since ?? ""} onChange={(e) => change({ since: e.target.value || undefined })} />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          {d.filterTo}
          <input type="date" className={field} value={filters.until ?? ""} onChange={(e) => change({ until: e.target.value || undefined })} />
        </label>
        <Button variant="outline" size="sm" onClick={() => { setFilters({}); setPage(0); setObject(null); }}>
          {d.clear}
        </Button>
      </div>

      {object ? (
        <div className="flex flex-col gap-3">
          <p className="m-0 flex items-center gap-3 text-sm text-muted-foreground">
            {d.historyShowing}
            <Button variant="outline" size="sm" onClick={() => setObject(null)}>{d.showAll}</Button>
          </p>
          <DecisionHistory targetType={object.target_type} targetId={object.target_id} names={names} />
        </div>
      ) : (
        <>
          {log.isLoading && <Skeleton aria-label={d.loading} className="h-24 w-full" />}
          {log.isError && (
            <p role="alert" className="m-0 text-sm text-destructive">
              {isForbidden(log.error) ? d.forbidden : d.failed}
            </p>
          )}
          {log.data && log.data.entries.length === 0 && <p className="m-0 text-sm text-muted-foreground">{d.empty}</p>}
          {log.data && log.data.entries.length > 0 && (
            <>
              <DecisionList entries={log.data.entries} names={names} onOpenHistory={setObject} />
              <nav className="flex items-center gap-3 text-sm" aria-label={d.page.replace("{n}", String(page + 1))}>
                <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>{d.prev}</Button>
                <span>{d.page.replace("{n}", `${page + 1} / ${pages}`)}</span>
                <Button variant="outline" size="sm" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>{d.next}</Button>
              </nav>
            </>
          )}
        </>
      )}
    </div>
  );
}
