"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import { getBriefingRecipients, setBriefingToSmmm } from "@/lib/api/scale";

const KEY = ["briefing-recipients"] as const;

/**
 * The owner's standing choice that the Monday briefing also goes to the company's accountant. It only
 * names a recipient: the e-mail still goes out through the outbox and, when there is an accountant, only
 * when they release it. With no accountant there is nothing to send to, and the card says how to get one.
 */
export function BriefingRecipientsCard() {
  const { t } = useI18n();
  const r = t.scale.recipients;
  const qc = useQueryClient();
  const { refresh } = useOrgSettings();
  const { data } = useQuery({ queryKey: KEY, queryFn: getBriefingRecipients, retry: false });
  const [notice, setNotice] = useState<"saved" | "error" | null>(null);

  if (!data) return null;

  async function change(on: boolean) {
    setNotice(null);
    try {
      qc.setQueryData(KEY, await setBriefingToSmmm(on));
      setNotice("saved");
      await refresh();
    } catch {
      setNotice("error");
    }
  }

  return (
    <Card className="space-y-2 p-4">
      <h2 className="tc-display m-0 text-[20px]">{r.title}</h2>
      {data.has_smmm ? (
        <>
          <label className="flex min-h-[44px] cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" checked={data.send_to_smmm} onChange={(e) => void change(e.target.checked)} />
            {r.toSmmm}
          </label>
          <p className="m-0 text-xs text-muted-foreground">{r.hint}</p>
          {data.suggested && !data.send_to_smmm && <p className="m-0 text-xs text-muted-foreground">{r.suggested}</p>}
        </>
      ) : (
        <p className="m-0 text-sm text-muted-foreground">{r.noSmmm}</p>
      )}
      {notice === "saved" && <p role="status" className="m-0 text-sm text-success">{r.saved}</p>}
      {notice === "error" && <p role="alert" className="m-0 text-sm text-destructive">{r.error}</p>}
    </Card>
  );
}
