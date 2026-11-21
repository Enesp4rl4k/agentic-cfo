"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CanButton } from "@/components/ui/can-button";
import { DecisionPacketPanel } from "@/components/ui/decision-packet-panel";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { HeldReasons } from "@/components/held-analyses/HeldReasons";
import { useI18n } from "@/hooks/useI18n";
import { approveJob } from "@/lib/api/cfo";
import { listHeldAnalyses, rejectAnalysis, type HeldAnalysis } from "@/lib/api/heldAnalyses";

export const HELD_ANALYSES_KEY = ["held-analyses"];

/** What an answer changes: the setup page, the radar, the company view and the result pages. */
const AFFECTED = [["baslangic"], ["cash-radar"], ["ledger-summary"], ["jobs"], ["job"], ["dashboard"]];

type Pending = { analysis: HeldAnalysis; action: "approve" | "reject" } | null;

/**
 * Analyses that finished but wait for a person: why each was held, and approve or reject. Approving is a
 * writer's action (the server answers 403 to anyone else, and the buttons say so). Renders nothing when
 * none wait. The decision packet (options, consequences, data freshness) sits under each, before signing.
 */
export function HeldAnalysesSection() {
  const { t } = useI18n();
  const copy = t.heldAnalysis;
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<Pending>(null);
  const [reason, setReason] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const { data } = useQuery({ queryKey: HELD_ANALYSES_KEY, queryFn: listHeldAnalyses });

  const decide = useMutation({
    mutationFn: ({ analysis, action }: NonNullable<Pending>) =>
      action === "approve" ? approveJob(analysis.id) : rejectAnalysis(analysis.id, reason),
    onSuccess: (_void, { action }) => {
      setFailed(false);
      setDone(action === "approve" ? copy.approved : copy.rejected);
      setPending(null);
      setReason("");
      for (const key of [HELD_ANALYSES_KEY, ...AFFECTED]) queryClient.invalidateQueries({ queryKey: key });
    },
    onError: () => {
      setFailed(true);
      setPending(null);
    },
  });

  const held = data ?? [];
  if (held.length === 0 && !done) return null;

  return (
    <section aria-label={copy.title.replace("{n}", String(held.length))} className="space-y-3">
      {held.length > 0 && (
        <>
          <h2 className="tc-display m-0 text-[26px] leading-[1.1]">{copy.title.replace("{n}", String(held.length))}</h2>
          <p className="m-0 text-sm text-muted-foreground">{copy.hint}</p>
        </>
      )}
      {done && <p role="status" className="text-sm font-medium">{done}</p>}
      {failed && <p role="alert" className="text-sm text-destructive">{copy.actionFailed}</p>}
      <ul className="space-y-3">
        {held.map((analysis) => (
          <li key={analysis.id}>
            <Card className="space-y-3 p-4">
              <p className="m-0 text-sm font-medium">{analysis.filename}</p>
              <HeldReasons reasons={analysis.reasons} />
              {analysis.proves_balance && <p className="m-0 text-sm">{copy.balanceProven}</p>}
              <div className="flex flex-wrap items-center gap-2">
                <CanButton action="edit" className="min-h-[44px]" disabled={decide.isPending} onClick={() => setPending({ analysis, action: "approve" })}>
                  {copy.approve}
                </CanButton>
                <CanButton action="edit" variant="outline" className="min-h-[44px]" disabled={decide.isPending} onClick={() => setPending({ analysis, action: "reject" })}>
                  {copy.reject}
                </CanButton>
                <Button asChild variant="outline" className="min-h-[44px]">
                  <Link href={`/pnl?job=${analysis.id}`}>{copy.viewResults}</Link>
                </Button>
              </div>
              <DecisionPacketPanel jobId={analysis.id} />
            </Card>
          </li>
        ))}
      </ul>

      <Dialog open={pending !== null} onOpenChange={(open) => { if (!open) setPending(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{pending?.action === "reject" ? copy.confirmRejectTitle : copy.confirmTitle}</DialogTitle>
            <DialogDescription>
              {pending?.action === "reject" ? copy.confirmRejectBody : copy.confirmBody}
            </DialogDescription>
          </DialogHeader>
          {pending?.action === "reject" && (
            <input
              aria-label={copy.rejectReason}
              placeholder={copy.rejectReason}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="min-h-[44px] w-full rounded-md border border-border bg-card px-3 text-sm"
            />
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setPending(null)}>{copy.cancel}</Button>
            <Button
              disabled={decide.isPending}
              onClick={() => pending && decide.mutate(pending)}
            >
              {decide.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              {pending?.action === "reject" ? copy.confirmReject : copy.confirmApprove}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
