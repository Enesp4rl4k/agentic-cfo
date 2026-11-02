"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ShieldAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { approveHeldJob, getReviewQueue, rejectHeldJob } from "@/lib/api/agentReview";

const QUEUE_KEY = ["agent-review-queue"];

/** Role results waiting for the owner. Renders nothing while the queue is empty. */
export function ReviewQueueCard() {
  const { t } = useI18n();
  const copy = t.reviewQueue;
  const queryClient = useQueryClient();
  const { data: queue } = useQuery({ queryKey: QUEUE_KEY, queryFn: getReviewQueue });

  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) =>
      approve ? approveHeldJob(id) : rejectHeldJob(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUEUE_KEY }),
  });

  if (!queue?.length) return null;

  return (
    <Card className="space-y-3 border-warning/40 p-4">
      <div>
        <p className="flex items-center gap-2 text-sm font-semibold">
          <ShieldAlert className="h-4 w-4 text-warning" aria-hidden="true" />
          {copy.title.replace("{n}", String(queue.length))}
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">{copy.body}</p>
      </div>
      <ul className="space-y-2">
        {queue.map((job) => (
          <li
            key={job.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium uppercase">{job.agent_type}</p>
              {job.gate?.reasons.map((reason) => (
                <p key={reason} className="text-xs text-muted-foreground">{reason}</p>
              ))}
            </div>
            <div className="flex shrink-0 gap-2">
              <Button
                size="sm"
                className="gap-1.5"
                disabled={decide.isPending}
                onClick={() => decide.mutate({ id: job.id, approve: true })}
              >
                <Check className="h-4 w-4" aria-hidden="true" />
                {copy.approve}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="gap-1.5"
                disabled={decide.isPending}
                onClick={() => decide.mutate({ id: job.id, approve: false })}
              >
                <X className="h-4 w-4" aria-hidden="true" />
                {copy.reject}
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {decide.isError && <p className="text-xs text-destructive">{copy.ownerOnly}</p>}
    </Card>
  );
}
