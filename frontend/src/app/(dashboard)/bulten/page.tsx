"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { OodaFooter } from "@/components/brand-app/OodaFooter";
import { RadarCurve } from "@/components/radar/RadarCurve";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { useI18n } from "@/hooks/useI18n";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import {
  getMondayBriefing,
  respondToMondayBriefing,
  type BriefingResponse,
  type MondayBriefing,
} from "@/lib/api/briefing";
import { getCashRadar, getPossibleDuplicates, getProposedSettlements } from "@/lib/api/ledger";
import { listPlanChanges } from "@/lib/api/planChanges";
import { cn } from "@/lib/utils";

const BRIEFING_KEY = ["monday-briefing"];

type Copy = ReturnType<typeof useI18n>["t"]["bulten"];
type Fmt = (value: number) => string;

/**
 * The Monday screen: this week's answer first, as the server wrote it, then the figures that back
 * it, the route, what waits for the owner's decision and how they answer. The page computes no
 * figure of its own: the sentences and the stats are the briefing's, the curve is the radar's, the
 * count of decisions is the sum of the lists the approvals page shows.
 */

function Stat({ label, value, negative }: Readonly<{ label: string; value: string; negative?: boolean }>) {
  return (
    <div className="flex flex-col gap-0.5 rounded-xl border border-border bg-card px-4 py-3">
      <dt className="text-[12.5px] text-muted-foreground">{label}</dt>
      <dd className={cn("tc-mono m-0 text-[22px]", negative && "text-destructive")}>{value}</dd>
    </div>
  );
}

function Stats({ briefing, copy, fmt }: Readonly<{ briefing: MondayBriefing; copy: Copy; fmt: Fmt }>) {
  const known = briefing.balance_known;
  return (
    <dl className="m-0 grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-3">
      {known && briefing.starting_cash_cents !== null && (
        <Stat label={copy.statToday} value={fmt(briefing.starting_cash_cents / 100)} negative={briefing.starting_cash_cents < 0} />
      )}
      <Stat label={copy.statNet} value={fmt(briefing.net_change_cents / 100)} negative={briefing.net_change_cents < 0} />
      {known && <Stat label={copy.statEnd} value={fmt(briefing.end_balance_cents / 100)} negative={briefing.end_balance_cents < 0} />}
      {briefing.approaching_amount_cents > 0 && (
        <Stat
          label={copy.statNext}
          value={`${fmt(briefing.approaching_amount_cents / 100)}${briefing.approaching_date ? ` · ${briefing.approaching_date}` : ""}`}
        />
      )}
    </dl>
  );
}

function Answer({ briefing, copy }: Readonly<{ briefing: MondayBriefing; copy: Copy }>) {
  const queryClient = useQueryClient();
  const answer = useMutation({
    mutationFn: (response: BriefingResponse) =>
      respondToMondayBriefing(response, briefing.week_start, briefing.fingerprint),
    // 409: the briefing changed after it was loaded (or there is no analysis yet).
    // Load the current one so the owner answers what is true now.
    onError: (error) => {
      if ((error as { status?: number }).status === 409) {
        void queryClient.invalidateQueries({ queryKey: BRIEFING_KEY });
      }
    },
  });
  const buttons: [BriefingResponse, string][] = [
    ["done", copy.done],
    ["deferred", copy.deferred],
    ["dismissed", copy.dismissed],
  ];
  return (
    <Card className="space-y-3 p-5">
      <h2 className="tc-display m-0 text-[22px] leading-tight">{copy.answerTitle}</h2>
      <div className="flex flex-wrap gap-2">
        {buttons.map(([response, label], index) => (
          <Button
            key={response}
            type="button"
            variant={index === 0 ? "default" : "outline"}
            className="min-h-[44px]"
            disabled={answer.isPending}
            onClick={() => answer.mutate(response)}
          >
            {label}
          </Button>
        ))}
      </div>
      {answer.isPending && <p className="m-0 text-sm text-muted-foreground">{copy.saving}</p>}
      {/* Saved is said only once the server has answered that it is. */}
      {answer.isSuccess && <p className="m-0 text-sm">{copy.saved}</p>}
      {answer.isError && (
        <p className="m-0 text-sm text-destructive" role="alert">
          {copy.saveFailed} {answer.error instanceof Error ? answer.error.message : ""}
        </p>
      )}
    </Card>
  );
}

function Route({ copy, fmt }: Readonly<{ copy: Copy; fmt: Fmt }>) {
  const { t } = useI18n();
  const { org } = useOrgSettings();
  const { data: radar } = useQuery({ queryKey: ["cash-radar"], queryFn: getCashRadar });
  if (!radar || radar.weeks.length === 0) return null;
  return (
    <Card className="space-y-3 overflow-x-auto p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="tc-display m-0 text-[22px] leading-tight">{copy.routeTitle}</h2>
        <Link href="/nakit-radari" className="inline-flex min-h-[44px] items-center text-sm font-medium text-primary underline-offset-4 hover:underline">
          {copy.routeLink}
        </Link>
      </div>
      <RadarCurve
        weeks={radar.weeks}
        known={radar.starting_cash_cents !== null}
        selected={null}
        onSelect={() => {}}
        copy={t.cashRadar}
        fmt={fmt}
        locale={org?.locale || "en-US"}
      />
    </Card>
  );
}

/** How many decisions wait: said only when every list loaded, so a failed list never reads as zero. */
function Decisions({ copy }: Readonly<{ copy: Copy }>) {
  const settlements = useQuery({ queryKey: ["ledger-settlements"], queryFn: getProposedSettlements });
  const duplicates = useQuery({ queryKey: ["ledger-duplicates"], queryFn: getPossibleDuplicates });
  const plans = useQuery({ queryKey: ["plan-changes", "pending"], queryFn: () => listPlanChanges("pending") });
  const loaded = settlements.isSuccess && duplicates.isSuccess && plans.isSuccess;
  const waiting = loaded
    ? (settlements.data?.length ?? 0) + (duplicates.data?.length ?? 0) + (plans.data?.changes.length ?? 0)
    : null;
  return (
    <Card className="space-y-3 p-5" style={waiting ? { borderColor: "var(--tc-ember)", borderWidth: 1.5 } : undefined}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="tc-display m-0 text-[22px] leading-tight">{copy.approvalsTitle}</h2>
        {waiting !== null && waiting > 0 && <span className="tc-mono text-sm">{waiting}</span>}
      </div>
      {waiting === 0 && <p className="m-0 text-sm text-muted-foreground">{copy.noApprovals}</p>}
      {waiting !== null && waiting > 0 && (
        <p className="m-0 text-sm text-muted-foreground">{copy.approvalsBody.replace("{n}", String(waiting))}</p>
      )}
      {waiting !== 0 && (
        <Link href="/onay" className="inline-flex min-h-[44px] items-center text-sm font-medium text-primary underline-offset-4 hover:underline">
          {copy.approvalsLink}
        </Link>
      )}
    </Card>
  );
}

export default function BultenPage() {
  const { t } = useI18n();
  const copy = t.bulten;
  const fmt = useCurrencyFormat();
  const { data: briefing, isLoading, isError } = useQuery({ queryKey: BRIEFING_KEY, queryFn: getMondayBriefing });

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-8">
      {isLoading && <p className="text-sm text-muted-foreground">{copy.loading}</p>}
      {isError && <p className="text-sm text-destructive">{copy.failed}</p>}

      {briefing && !briefing.has_data && (
        <>
          <h1 className="tc-display m-0 text-4xl leading-[1.05]">{copy.title}</h1>
          <Card className="space-y-2 p-5">
            <p className="m-0 text-sm font-semibold">{copy.emptyTitle}</p>
            <p className="m-0 text-sm text-muted-foreground">{copy.emptyBody}</p>
            <Link href="/baglan" className="inline-flex min-h-[44px] items-center text-sm font-medium text-primary underline-offset-4 hover:underline">
              {copy.connect}
            </Link>
          </Card>
        </>
      )}

      {briefing && briefing.has_data && (
        <>
          <header className="space-y-3">
            <span className="tc-eyebrow text-muted-foreground">
              {copy.eyebrow.replace("{start}", briefing.week_start).replace("{end}", briefing.week_end)}
            </span>
            {/* The sentences are shown as the server wrote them; this page computes nothing. */}
            <h1 className="tc-display m-0 max-w-4xl text-[32px] leading-[1.1] sm:text-[42px]">{briefing.sentence_radar}</h1>
            <p className="m-0 max-w-3xl text-base text-muted-foreground">{briefing.sentence_obligation}</p>
            <p className="m-0 max-w-3xl text-base font-medium">{briefing.sentence_action}</p>
            {!briefing.balance_known && <p className="m-0 text-xs text-muted-foreground">{copy.unknownBalance}</p>}
            {briefing.fallback_used && <p className="m-0 text-xs text-muted-foreground">{copy.fallbackNote}</p>}
          </header>

          <Stats briefing={briefing} copy={copy} fmt={fmt} />

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
            <Route copy={copy} fmt={fmt} />
            <div className="space-y-4">
              <Decisions copy={copy} />
              <Answer briefing={briefing} copy={copy} />
            </div>
          </div>

          <p className="m-0 text-xs text-muted-foreground">
            {copy.radarHint}{" "}
            <Link href="/nakit-radari" className="font-medium text-primary underline-offset-4 hover:underline">
              {copy.radarLink}
            </Link>
          </p>
        </>
      )}

      <div className="flex flex-wrap items-baseline gap-3 pt-2">
        <span className="tc-display text-[22px] italic">{copy.carpe}</span>
        <span className="tc-eyebrow text-[11px] text-muted-foreground">{copy.carpeSub}</span>
      </div>
      <OodaFooter />
    </div>
  );
}
