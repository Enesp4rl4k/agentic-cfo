"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { useCompanyContextStore } from "@/store/companyContext";
import { switchOrg } from "@/lib/api/orgs";
import { getSmmmWorkload, type WorkloadOrg } from "@/lib/api/scale";

/**
 * The companies the signed-in person is the accountant of, each with what waits for them: entries in the
 * approval queue, last month's close, briefing e-mails held for their release. Counts only; seeing a
 * company's data still means switching into it. Renders nothing for someone who is nobody's accountant.
 */
export function SmmmWorkload() {
  const { t } = useI18n();
  const w = t.scale.workload;
  const { update } = useSession();
  const { clearWorkspace } = useCompanyContextStore();
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const { data, isError } = useQuery({ queryKey: ["smmm-workload"], queryFn: getSmmmWorkload, retry: false });

  if (isError) return null;
  if (!data || data.organizations.length === 0) return null;

  async function go(orgId: string) {
    setBusy(orgId);
    setFailed(false);
    try {
      await switchOrg(orgId);
      await update(); // the session still carries the role of the organisation just left
      clearWorkspace();
      window.location.assign("/smmm-onay");
    } catch {
      setBusy(null);
      setFailed(true);
    }
  }

  const lines = (o: WorkloadOrg) => [
    ...(o.pending_onay > 0 ? [w.onay.replace("{n}", String(o.pending_onay))] : []),
    ...(o.month_to_close ? [w.close.replace("{month}", o.month_to_close)] : []),
    ...(o.briefings_held > 0 ? [w.briefing.replace("{n}", String(o.briefings_held))] : []),
  ];

  return (
    <Card className="space-y-3 p-4">
      <div>
        <h2 className="text-base font-semibold">{w.title}</h2>
        <p className="m-0 text-xs text-muted-foreground">{w.subtitle}</p>
      </div>
      {data.total_waiting === 0 ? (
        <p className="m-0 text-sm text-muted-foreground">{w.empty}</p>
      ) : (
        <p className="m-0 text-sm font-medium">{w.total.replace("{n}", String(data.total_waiting))}</p>
      )}
      <ul className="space-y-2">
        {data.organizations.map((o) => (
          <li key={o.org_id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3">
            <div className="min-w-0">
              <p className="m-0 text-sm font-medium">{o.name}</p>
              {lines(o).length === 0 ? (
                <p className="m-0 text-xs text-muted-foreground">{w.nothing}</p>
              ) : (
                lines(o).map((line) => (
                  <p key={line} className="m-0 text-xs text-muted-foreground">{line}</p>
                ))
              )}
            </div>
            <Button variant="outline" className="min-h-[44px]" disabled={busy !== null} onClick={() => void go(o.org_id)}>
              {w.switch}
            </Button>
          </li>
        ))}
      </ul>
      {failed && <p role="alert" className="m-0 text-sm text-destructive">{w.failed}</p>}
    </Card>
  );
}
