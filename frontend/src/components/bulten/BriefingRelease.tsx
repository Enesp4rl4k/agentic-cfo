"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { getBriefingDeliveries, releaseMondayBriefing, type MondayBriefing } from "@/lib/api/briefing";
import { getMemberships } from "@/lib/api/orgs";
import { useI18n } from "@/hooks/useI18n";

const SMMM_ROLE = "smmm";

type Phase = "none" | "held" | "sending" | "sent";

/** What the e-mails say together: any held one holds the whole briefing. */
function phaseOf(rows: { status: string }[]): Phase {
  if (rows.length === 0) return "none";
  if (rows.some((r) => r.status === "held")) return "held";
  if (rows.some((r) => r.status === "pending")) return "sending";
  return "sent";
}

/**
 * The Monday e-mail of a company that has an accountant waits for the accountant (ADR 0008). The
 * accountant, acting in this company, releases it after a confirmation; the owner only sees that it
 * waits. Nothing is shown for a briefing with no e-mail. The server decides who may release (403).
 */
export function BriefingRelease({ briefing }: Readonly<{ briefing: MondayBriefing }>) {
  const { t } = useI18n();
  const copy = t.bulten.release;
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const key = ["briefing-deliveries", briefing.briefing_id];

  const deliveries = useQuery({ queryKey: key, queryFn: () => getBriefingDeliveries(briefing.briefing_id) });
  const memberships = useQuery({ queryKey: ["org-memberships"], queryFn: getMemberships, retry: false, staleTime: 60_000 });
  const isAccountant = memberships.data?.memberships.find((m) => m.active)?.role === SMMM_ROLE;

  const release = useMutation({
    mutationFn: () => releaseMondayBriefing(briefing.briefing_id),
    // Released or already released by someone else: either way the truth is the server's list.
    onSettled: () => {
      setConfirming(false);
      void queryClient.invalidateQueries({ queryKey: key });
    },
  });

  const phase = phaseOf(deliveries.data ?? []);
  if (phase === "none") return null;
  const forbidden = (release.error as { status?: number } | null)?.status === 403;
  const week = `${briefing.week_start} – ${briefing.week_end}`;

  return (
    <Card className="space-y-3 p-5">
      <h2 className="tc-display m-0 text-[22px] leading-tight">{copy.title}</h2>
      <p className="m-0 text-xs text-muted-foreground">{copy.week.replace("{week}", week)}</p>

      {phase === "held" && (
        <p className="m-0 text-sm">{isAccountant ? copy.heldAccountant : copy.heldOwner}</p>
      )}
      {phase === "sending" && <p className="m-0 text-sm">{copy.sending}</p>}
      {phase === "sent" && <p className="m-0 text-sm">{copy.sent}</p>}
      {release.isSuccess && release.data.released === 0 && phase !== "held" && (
        <p className="m-0 text-xs text-muted-foreground">{copy.alreadyReleased}</p>
      )}

      {phase === "held" && isAccountant && (
        <Button type="button" className="min-h-[44px]" disabled={release.isPending} onClick={() => setConfirming(true)}>
          {copy.action}
        </Button>
      )}
      {forbidden && (
        <p className="m-0 text-sm text-destructive" role="alert">{copy.forbidden}</p>
      )}
      {release.isError && !forbidden && (
        <p className="m-0 text-sm text-destructive" role="alert">{copy.failed}</p>
      )}

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{copy.confirmTitle}</DialogTitle>
            <DialogDescription>{copy.confirmBody.replace("{week}", week)}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>{copy.cancel}</Button>
            <Button disabled={release.isPending} onClick={() => release.mutate()}>{copy.confirm}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
