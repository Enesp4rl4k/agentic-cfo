"use client";

import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Newspaper } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/hooks/useI18n";
import {
  getMondayBriefing,
  respondToMondayBriefing,
  type BriefingResponse,
  type MondayBriefing,
} from "@/lib/api/briefing";

const BRIEFING_KEY = ["monday-briefing"];

type Copy = ReturnType<typeof useI18n>["t"]["bulten"];

function Sentences({ briefing, copy }: { briefing: MondayBriefing; copy: Copy }) {
  return (
    <Card className="space-y-3 p-4">
      <p className="text-xs text-muted-foreground tabular-nums">
        {copy.week}: {briefing.week_start} – {briefing.week_end}
      </p>
      {/* The sentences are shown as the server wrote them; this page computes nothing. */}
      <p className="text-base">{briefing.sentence_radar}</p>
      <p className="text-base">{briefing.sentence_obligation}</p>
      <p className="text-base font-medium">{briefing.sentence_action}</p>
      {!briefing.balance_known && <p className="text-xs text-muted-foreground">{copy.unknownBalance}</p>}
      {briefing.fallback_used && <p className="text-xs text-muted-foreground">{copy.fallbackNote}</p>}
    </Card>
  );
}

function Answer({ briefing, copy }: { briefing: MondayBriefing; copy: Copy }) {
  const answer = useMutation({
    mutationFn: (response: BriefingResponse) => respondToMondayBriefing(response, briefing.week_start),
  });
  const buttons: [BriefingResponse, string][] = [
    ["done", copy.done],
    ["deferred", copy.deferred],
    ["dismissed", copy.dismissed],
  ];
  return (
    <Card className="space-y-3 p-4">
      <p className="text-sm font-semibold">{copy.answerTitle}</p>
      <div className="flex flex-wrap gap-2">
        {buttons.map(([response, label]) => (
          <Button
            key={response}
            type="button"
            variant="outline"
            disabled={answer.isPending}
            onClick={() => answer.mutate(response)}
          >
            {label}
          </Button>
        ))}
      </div>
      {answer.isPending && <p className="text-sm text-muted-foreground">{copy.saving}</p>}
      {/* Saved is said only once the server has answered that it is. */}
      {answer.isSuccess && <p className="text-sm">{copy.saved}</p>}
      {answer.isError && (
        <p className="text-sm text-destructive" role="alert">
          {copy.saveFailed} {answer.error instanceof Error ? answer.error.message : ""}
        </p>
      )}
    </Card>
  );
}

export default function BultenPage() {
  const { t } = useI18n();
  const copy = t.bulten;
  const { data: briefing, isLoading, isError } = useQuery({ queryKey: BRIEFING_KEY, queryFn: getMondayBriefing });

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <Newspaper className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
          {copy.title}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">{copy.subtitle}</p>
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">{copy.loading}</p>}
      {isError && <p className="text-sm text-destructive">{copy.failed}</p>}
      {briefing &&
        (briefing.has_data ? (
          <>
            <Sentences briefing={briefing} copy={copy} />
            <Answer briefing={briefing} copy={copy} />
            <p className="text-xs text-muted-foreground">
              {copy.radarHint}{" "}
              <Link href="/nakit-radari" className="font-medium text-primary underline-offset-4 hover:underline">
                {copy.radarLink}
              </Link>
            </p>
          </>
        ) : (
          <Card className="space-y-2 p-4">
            <p className="text-sm font-semibold">{copy.emptyTitle}</p>
            <p className="text-sm text-muted-foreground">{copy.emptyBody}</p>
            <Link href="/baglan" className="text-sm font-medium text-primary underline-offset-4 hover:underline">
              {copy.connect}
            </Link>
          </Card>
        ))}
    </div>
  );
}
