"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PageHead } from "@/components/brand-app/PageHead";
import { OodaFooter } from "@/components/brand-app/OodaFooter";
import { clampWeek, payables, runScenario, weekOf, WEEKS, type Moves } from "@/components/calendar/scenario";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { useI18n } from "@/hooks/useI18n";
import { getCashRadar } from "@/lib/api/ledger";
import { cn } from "@/lib/utils";

/**
 * Payment calendar: move a payment to another week and watch the route. A scenario only: the moves
 * live in this page, nothing is written, the base forecast and the real payment plan stay as they
 * are. It needs a proven balance, and says so when there is none.
 */
export default function TakvimPage() {
  const { t } = useI18n();
  const copy = t.takvim;
  const weekCopy = t.cashRadar;
  const fmt = useCurrencyFormat();
  const [moves, setMoves] = useState<Moves>({});
  const [over, setOver] = useState<number | null>(null);

  const { data: radar, isLoading, isError } = useQuery({ queryKey: ["cash-radar"], queryFn: getCashRadar });

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

      {radar && result && (
        <>
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

          <Link href="/nakit-radari" className="inline-flex min-h-[44px] items-center text-sm font-medium text-primary underline-offset-4 hover:underline">
            {copy.toRoute}
          </Link>
        </>
      )}

      <OodaFooter current={1} />
    </div>
  );
}
