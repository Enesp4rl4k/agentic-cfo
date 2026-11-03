"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { useI18n } from "@/hooks/useI18n";
import { getLedgerSummary, getPossibleDuplicates, resolveDuplicate } from "@/lib/api/ledger";

const SUMMARY_KEY = ["ledger-summary"];
const DUPLICATES_KEY = ["ledger-duplicates"];

/** The company's one record of its money, and the rows waiting for a person. */
export function LedgerCard() {
  const { t } = useI18n();
  const copy = t.ledger;
  const fmt = useCurrencyFormat();
  const queryClient = useQueryClient();
  const { data: summary } = useQuery({ queryKey: SUMMARY_KEY, queryFn: getLedgerSummary });
  const { data: duplicates } = useQuery({ queryKey: DUPLICATES_KEY, queryFn: getPossibleDuplicates });

  const decide = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "keep" | "exclude" }) => resolveDuplicate(id, action),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SUMMARY_KEY });
      queryClient.invalidateQueries({ queryKey: DUPLICATES_KEY });
    },
  });

  if (!summary?.rows && !duplicates?.length) return null;

  return (
    <Card className="space-y-3 p-4">
      <div>
        <p className="flex items-center gap-2 text-sm font-semibold">
          <BookOpen className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          {copy.title}
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">{copy.body}</p>
      </div>
      {summary && (
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs text-muted-foreground">{copy.period}</dt>
            <dd className="font-medium tabular-nums">{summary.period.start} – {summary.period.end}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">{copy.rows}</dt>
            <dd className="font-medium tabular-nums">{summary.rows}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">{copy.revenue}</dt>
            <dd className="font-medium tabular-nums">{fmt(summary.revenue_cents / 100)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">{copy.expense}</dt>
            <dd className="font-medium tabular-nums">{fmt(summary.expense_cents / 100)}</dd>
          </div>
        </dl>
      )}
      {summary && summary.open_items.receivable_cents + summary.open_items.payable_cents > 0 && (
        <p className="text-xs">
          {copy.openItems
            .replace("{receivable}", fmt(summary.open_items.receivable_cents / 100))
            .replace("{payable}", fmt(summary.open_items.payable_cents / 100))
            .replace("{noDue}", String(summary.open_items.no_due_date))}
        </p>
      )}
      {summary?.last_upload && (
        <p className="text-xs text-muted-foreground">
          {copy.lastUpload
            .replace("{file}", summary.last_upload.filename)
            .replace("{new}", String(summary.last_upload.new))
            .replace("{already}", String(summary.last_upload.already))
            .replace("{possible}", String(summary.last_upload.possible_duplicate))}
        </p>
      )}
      {!!duplicates?.length && (
        <div className="space-y-2">
          <p className="text-xs font-medium">{copy.duplicatesTitle.replace("{n}", String(duplicates.length))}</p>
          <ul className="space-y-2">
            {duplicates.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3">
                <div className="min-w-0 text-xs">
                  <p className="font-medium tabular-nums">
                    {row.transaction_date} · {fmt(row.amount_cents / 100)}
                  </p>
                  <p>{row.description}</p>
                  {row.matches?.map((match) => (
                    <p key={match.id} className="text-muted-foreground">
                      {copy.alreadyThere.replace("{description}", match.description ?? "")}
                    </p>
                  ))}
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ id: row.id, action: "keep" })}
                  >
                    {copy.keep}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ id: row.id, action: "exclude" })}
                  >
                    {copy.exclude}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
