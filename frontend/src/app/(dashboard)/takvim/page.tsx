"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { BasisTag, formatDay, StaleBalanceNotice } from "@/components/radar/basis";
import { PageHead } from "@/components/brand-app/PageHead";
import { OodaFooter } from "@/components/brand-app/OodaFooter";
import { clampWeek, payables, runScenario, shiftDate, weekOf, WEEKS, type Moves } from "@/components/calendar/scenario";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { useI18n } from "@/hooks/useI18n";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import { getCashRadar } from "@/lib/api/ledger";
import { decidePlanChange, listPlanChanges, planChangeError, proposePlanChange } from "@/lib/api/planChanges";
import { cn } from "@/lib/utils";

/**
 * Payment calendar: move a payment to another week and watch the route. A scenario only: the moves
 * live in this page, nothing is written, the base forecast and the real payment plan stay as they
 * are. It needs a proven balance, and says so when there is none.
 */
export default function TakvimPage() {
  const { t } = useI18n();
  const { org } = useOrgSettings();
  const locale = org?.locale || "en-US";
  const copy = t.takvim;
  const weekCopy = t.cashRadar;
  const fmt = useCurrencyFormat();
  const [moves, setMoves] = useState<Moves>({});
  const [over, setOver] = useState<number | null>(null);
  const [sentMessage, setSentMessage] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: radar, isLoading, isError } = useQuery({ queryKey: ["cash-radar"], queryFn: getCashRadar });

  const { data: pending } = useQuery({ queryKey: ["plan-changes", "pending"], queryFn: () => listPlanChanges("pending") });
  const canDecide = Boolean(pending?.canDecide);

  // A payment moved in the scenario becomes a proposal. Someone who may decide holds the authority
  // themselves, so their proposal is approved at once; everyone else's waits in the approvals.
  const send = useMutation({
    mutationFn: async ({ id, toDate }: { id: string; toDate: string }) => {
      const change = await proposePlanChange(id, toDate);
      if (canDecide) await decidePlanChange(change.id, "approve");
      return change;
    },
    onSuccess: (_change, { id }) => {
      setSendError(null);
      setSentMessage(canDecide ? copy.applied : copy.sent);
      setMoves((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
      for (const key of [["cash-radar"], ["plan-changes", "pending"]]) queryClient.invalidateQueries({ queryKey: key });
    },
    onError: (error) => {
      setSentMessage(null);
      setSendError(planChangeError(error) ?? copy.sendFailed);
    },
  });

  const items = radar ? payables(radar) : [];
  const result = radar ? runScenario(radar, moves) : null;
  const movedCount = Object.keys(moves).length;

  function move(id: string, to: number) {
    const item = items.find((i) => i.id === id);
    if (!item) return;
    const target = clampWeek(to, radar?.weeks.length ?? WEEKS);
    setMoves((current) => {
      const next = { ...current };
      if (target === item.week) delete next[id];
      else next[id] = target;
      return next;
    });
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-4 sm:p-8">
      <PageHead step={1} title={copy.title} subtitle={copy.subtitle} />

      {isLoading && <p className="text-sm text-muted-foreground">{weekCopy.loading}</p>}
      {isError && <p role="alert" className="text-sm text-destructive">{copy.failed}</p>}

      {radar && radar.starting_cash_cents === null && (
        <Card className="space-y-2 p-4">
          <p className="text-sm text-muted-foreground">{copy.needBalance}</p>
          <Link href="/baglan" className="inline-flex min-h-[44px] items-center text-sm font-medium text-primary underline-offset-4 hover:underline">
            {copy.connect}
          </Link>
        </Card>
      )}

      {radar?.opening_cash?.stale && (
        <StaleBalanceNotice asOf={radar.opening_cash.as_of} ageDays={radar.opening_cash.age_days} locale={locale} />
      )}

      {radar && result && (
        <>
          {radar.opening_cash && (
            <p className="m-0 text-xs text-muted-foreground">{weekCopy.cashAsOf.replace("{date}", formatDay(radar.opening_cash.as_of, locale))}</p>
          )}
          <div className="flex flex-wrap items-end justify-between gap-4">
            <dl className="flex flex-wrap gap-6">
              <div>
                <dt className="text-[12.5px] text-muted-foreground">{copy.lowestBase}</dt>
                <dd className={cn("tc-mono text-[22px]", result.lowBase < 0 && "text-destructive")}>{fmt(result.lowBase / 100)}</dd>
              </div>
              <div>
                <dt className="text-[12.5px] text-muted-foreground">{copy.lowestScenario}</dt>
                <dd className={cn("tc-mono text-[22px]", result.lowScenario < 0 && "text-destructive")}>{fmt(result.lowScenario / 100)}</dd>
              </div>
              <div>
                <dt className="text-[12.5px] text-muted-foreground">{copy.difference}</dt>
                <dd className="tc-mono text-[22px]">{fmt((result.lowScenario - result.lowBase) / 100)}</dd>
              </div>
            </dl>
            <div className="flex items-center gap-3">
              {movedCount > 0 && <span className="text-sm text-muted-foreground">{copy.moved.replace("{n}", String(movedCount))}</span>}
              <Button variant="outline" className="min-h-[44px]" disabled={movedCount === 0} onClick={() => setMoves({})}>
                {copy.reset}
              </Button>
            </div>
          </div>
          <p className="m-0 text-sm text-muted-foreground">{copy.dragHint}</p>

          <ol className="flex gap-3 overflow-x-auto pb-2" aria-label={copy.title}>
            {radar.weeks.map((w, index) => {
              const here = items.filter((i) => weekOf(i, moves) === w.week);
              const closing = result.scenario[index];
              return (
                <li
                  key={w.week}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setOver(w.week);
                  }}
                  onDragLeave={() => setOver((current) => (current === w.week ? null : current))}
                  onDrop={(e) => {
                    e.preventDefault();
                    setOver(null);
                    const id = e.dataTransfer.getData("text/plain");
                    if (id) move(id, w.week);
                  }}
                  className={cn(
                    "flex min-h-[220px] w-[190px] shrink-0 flex-col gap-2 rounded-xl border bg-card p-3",
                    over === w.week ? "border-[color:var(--tc-ember)]" : "border-border",
                  )}
                >
                  <div className="space-y-0.5">
                    <h2 className="tc-eyebrow m-0 text-[11px] text-muted-foreground">{copy.weekLabel.replace("{n}", String(w.week))}</h2>
                    <p className="tc-mono m-0 text-[11px] text-muted-foreground">
                      {w.start_date.slice(5)} – {w.end_date.slice(5)}
                    </p>
                    <p className="m-0 text-xs text-muted-foreground">
                      {copy.closing}{" "}
                      <span className={cn("tc-mono", closing < 0 ? "text-destructive" : "text-foreground")}>{fmt(closing / 100)}</span>
                    </p>
                  </div>
                  <ul className="flex flex-1 flex-col gap-2">
                    {here.length === 0 && <li className="text-xs text-muted-foreground">{copy.noPayables}</li>}
                    {here.map((item) => {
                      const name = item.name ?? weekCopy.weekDetailItem;
                      const moved = moves[item.id] !== undefined;
                      return (
                        <li
                          key={item.id}
                          draggable
                          onDragStart={(e) => e.dataTransfer.setData("text/plain", item.id)}
                          className={cn(
                            "cursor-grab rounded-lg border p-2 text-xs",
                            moved ? "border-[color:var(--tc-ember)]" : "border-border",
                          )}
                        >
                          <p className="m-0 truncate font-medium" title={name}>{name}</p>
                          <p className="m-0">
                            <BasisTag item={item.item} copy={weekCopy} fmt={(v) => fmt(v)} locale={locale} />
                            {item.item.basis_reason === "payment_plan_change_taken_as_date" && (
                              <span className="ml-1.5 text-[11px] text-muted-foreground">{copy.byPlan}</span>
                            )}
                          </p>
                          <p className="tc-mono m-0 text-muted-foreground">{fmt(item.amountCents / 100)}</p>
                          <div className="mt-1 flex gap-1">
                            <Button
                              variant="outline"
                              size="sm"
                              className="min-h-[44px] min-w-[44px]"
                              aria-label={copy.earlier.replace("{name}", name)}
                              disabled={w.week <= 1}
                              onClick={() => move(item.id, w.week - 1)}
                            >
                              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              className="min-h-[44px] min-w-[44px]"
                              aria-label={copy.later.replace("{name}", name)}
                              disabled={w.week >= radar.weeks.length}
                              onClick={() => move(item.id, w.week + 1)}
                            >
                              <ArrowRight className="h-4 w-4" aria-hidden="true" />
                            </Button>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </li>
              );
            })}
          </ol>

          {items.some((i) => moves[i.id] !== undefined) && (
            <section aria-label={copy.moved.replace("{n}", String(movedCount))} className="space-y-2">
              <ul className="space-y-2">
                {items
                  .filter((i) => moves[i.id] !== undefined)
                  .map((i) => {
                    const toDate = shiftDate(i.expectedDate, moves[i.id] - i.week);
                    const name = i.name ?? weekCopy.weekDetailItem;
                    return (
                      <li key={i.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card p-3">
                        <span className="text-sm">
                          <span className="font-medium">{name}</span>{" "}
                          <span className="tc-mono text-muted-foreground">{fmt(i.amountCents / 100)} · {copy.toDate.replace("{date}", toDate)}</span>
                        </span>
                        <Button
                          className="min-h-[44px]"
                          disabled={send.isPending}
                          onClick={() => send.mutate({ id: i.id, toDate })}
                          aria-label={`${name}: ${canDecide ? copy.apply : copy.send}`}
                        >
                          {canDecide ? copy.apply : copy.send}
                        </Button>
                      </li>
                    );
                  })}
              </ul>
            </section>
          )}
          {sentMessage && <p role="status" className="m-0 text-sm text-success">{sentMessage}</p>}
          {sendError && <p role="alert" className="m-0 text-sm text-destructive">{sendError}</p>}

          <Link href="/nakit-radari" className="inline-flex min-h-[44px] items-center text-sm font-medium text-primary underline-offset-4 hover:underline">
            {copy.toRoute}
          </Link>
        </>
      )}

      <OodaFooter current={1} />
    </div>
  );
}
