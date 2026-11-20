"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PageHead } from "@/components/brand-app/PageHead";
import { OodaFooter } from "@/components/brand-app/OodaFooter";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { useI18n } from "@/hooks/useI18n";
import {
  getPossibleDuplicates,
  getProposedSettlements,
  resolveDuplicate,
  resolveSettlement,
  type LedgerRow,
  type ProposedSettlement,
} from "@/lib/api/ledger";

const SETTLEMENTS_KEY = ["ledger-settlements"];
const DUPLICATES_KEY = ["ledger-duplicates"];
const SUMMARY_KEY = ["ledger-summary"];
const RADAR_KEY = ["cash-radar"];

const day = (iso: string) => iso.slice(0, 10);

/**
 * Pending approvals: what the system would not decide alone. A bank movement that may close an
 * invoice, and a record that looks like one already uploaded. Both are the ledger's own proposals
 * (the same ones the Command Center summarises); nothing here is invented, and nothing enters the
 * route until the person chooses.
 */
export default function OnayPage() {
  const { t } = useI18n();
  const copy = t.onay;
  const ledger = t.ledger;
  const fmt = useCurrencyFormat();
  const queryClient = useQueryClient();
  const [actionFailed, setActionFailed] = useState(false);

  const settlements = useQuery({ queryKey: SETTLEMENTS_KEY, queryFn: getProposedSettlements });
  const duplicates = useQuery({ queryKey: DUPLICATES_KEY, queryFn: getPossibleDuplicates });

  const refreshed = () => {
    setActionFailed(false);
    for (const key of [SETTLEMENTS_KEY, DUPLICATES_KEY, SUMMARY_KEY, RADAR_KEY]) {
      queryClient.invalidateQueries({ queryKey: key });
    }
  };
  const settle = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "confirm" | "reject" }) => resolveSettlement(id, action),
    onSuccess: refreshed,
    onError: () => setActionFailed(true),
  });
  const decide = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "keep" | "exclude" }) => resolveDuplicate(id, action),
    onSuccess: refreshed,
    onError: () => setActionFailed(true),
  });

  const loading = settlements.isLoading || duplicates.isLoading;
  const failed = settlements.isError || duplicates.isError;
  const settlementRows: ProposedSettlement[] = settlements.data ?? [];
  const duplicateRows: LedgerRow[] = duplicates.data ?? [];
  const nothing = !loading && !failed && settlementRows.length === 0 && duplicateRows.length === 0;
  const waiting = settlementRows.length + duplicateRows.length;

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-4 sm:p-8">
      <PageHead
        step={2}
        title={copy.title}
        subtitle={copy.subtitle}
        aside={
          waiting > 0 ? (
            <span className="tc-mono rounded-full border border-border px-3 py-1 text-sm" aria-label={String(waiting)}>
              {waiting}
            </span>
          ) : undefined
        }
      />

      {failed && <p role="alert" className="text-sm text-destructive">{copy.failed}</p>}
      {actionFailed && <p role="alert" className="text-sm text-destructive">{copy.actionFailed}</p>}
      {nothing && <p className="text-sm text-muted-foreground">{copy.empty}</p>}

      {settlementRows.length > 0 && (
        <section aria-label={ledger.settlementsTitle.replace("{n}", String(settlementRows.length))} className="space-y-3">
          <h2 className="tc-display m-0 text-[26px] leading-[1.1]">
            {ledger.settlementsTitle.replace("{n}", String(settlementRows.length))}
          </h2>
          <ul className="space-y-3">
            {settlementRows.map((s) => (
              <li key={s.id}>
                <Card className="grid gap-4 p-4 sm:grid-cols-2">
                  <div className="space-y-1">
                    <p className="tc-eyebrow text-[11px] text-muted-foreground">{copy.movement}</p>
                    <p className="text-sm font-medium">{s.row.description ?? copy.noCounterparty}</p>
                    <p className="tc-mono text-sm text-muted-foreground">
                      {day(s.row.transaction_date)} · {fmt(s.row.amount_cents / 100)}
                    </p>
                  </div>
                  <div className="space-y-1 rounded-lg border border-border p-3">
                    <p className="tc-eyebrow text-[11px] text-muted-foreground">{copy.candidate}</p>
                    <p className="text-sm font-medium">{s.item.counterparty ?? s.item.description ?? copy.noCounterparty}</p>
                    <p className="tc-mono text-sm text-muted-foreground">
                      {fmt(s.item.amount_cents / 100)}
                      {s.item.due_date ? ` · ${copy.dueOn.replace("{date}", day(s.item.due_date))}` : ""}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2 sm:col-span-2">
                    <Button
                      className="min-h-[44px]"
                      disabled={settle.isPending}
                      onClick={() => settle.mutate({ id: s.id, action: "confirm" })}
                    >
                      {ledger.settleYes}
                    </Button>
                    <Button
                      variant="outline"
                      className="min-h-[44px]"
                      disabled={settle.isPending}
                      onClick={() => settle.mutate({ id: s.id, action: "reject" })}
                    >
                      {ledger.settleNo}
                    </Button>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      )}

      {duplicateRows.length > 0 && (
        <section aria-label={ledger.duplicatesTitle.replace("{n}", String(duplicateRows.length))} className="space-y-3">
          <h2 className="tc-display m-0 text-[26px] leading-[1.1]">
            {ledger.duplicatesTitle.replace("{n}", String(duplicateRows.length))}
          </h2>
          <p className="m-0 text-sm text-muted-foreground">{copy.duplicateHint}</p>
          <ul className="space-y-3">
            {duplicateRows.map((row) => (
              <li key={row.id}>
                <Card className="space-y-3 p-4">
                  <div>
                    <p className="text-sm font-medium">{row.description ?? copy.noCounterparty}</p>
                    <p className="tc-mono text-sm text-muted-foreground">
                      {day(row.transaction_date)} · {fmt(row.amount_cents / 100)}
                    </p>
                    {row.matches?.map((m) => (
                      <p key={m.id} className="mt-1 text-xs text-muted-foreground">
                        {ledger.alreadyThere.replace("{description}", m.description ?? "")}
                      </p>
                    ))}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      className="min-h-[44px]"
                      disabled={decide.isPending}
                      onClick={() => decide.mutate({ id: row.id, action: "keep" })}
                    >
                      {ledger.keep}
                    </Button>
                    <Button
                      variant="outline"
                      className="min-h-[44px]"
                      disabled={decide.isPending}
                      onClick={() => decide.mutate({ id: row.id, action: "exclude" })}
                    >
                      {ledger.exclude}
                    </Button>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      )}

      <OodaFooter current={2} />
    </div>
  );
}
