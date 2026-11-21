"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen } from "lucide-react";
import { CanButton } from "@/components/ui/can-button";
import { Card } from "@/components/ui/card";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { useI18n } from "@/hooks/useI18n";
import { BaseCurrencyNotice, OtherCurrencyLines, shownCode } from "@/components/ui/other-currency-lines";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import { formatCurrency } from "@/lib/utils";
import { failureMessage } from "@/lib/forbidden";
import {
  getLedgerSummary,
  getPossibleDuplicates,
  getProposedSettlements,
  resolveDuplicate,
  resolveSettlement,
} from "@/lib/api/ledger";

const SUMMARY_KEY = ["ledger-summary"];
const DUPLICATES_KEY = ["ledger-duplicates"];
const SETTLEMENTS_KEY = ["ledger-settlements"];

/** The company's one record of its money, and the rows waiting for a person. */
export function LedgerCard() {
  const { t } = useI18n();
  const copy = t.ledger;
  const fmt = useCurrencyFormat();
  const { org } = useOrgSettings();
  // A row in another currency is shown in its own, never in the base currency's symbol.
  const fmtIn = (value: number, currency?: string) =>
    currency !== undefined && currency !== (org?.base_currency || currency)
      ? formatCurrency(value, currency, org?.locale || "en-US", t.otherCurrency.unknown)
      : fmt(value);
  const queryClient = useQueryClient();
  const { data: summary } = useQuery({ queryKey: SUMMARY_KEY, queryFn: getLedgerSummary });
  const { data: duplicates } = useQuery({ queryKey: DUPLICATES_KEY, queryFn: getPossibleDuplicates });
  const { data: settlements } = useQuery({ queryKey: SETTLEMENTS_KEY, queryFn: getProposedSettlements });

  const settle = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "confirm" | "reject" }) => resolveSettlement(id, action),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SUMMARY_KEY });
      queryClient.invalidateQueries({ queryKey: SETTLEMENTS_KEY });
    },
  });

  const decide = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "keep" | "exclude" }) => resolveDuplicate(id, action),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SUMMARY_KEY });
      queryClient.invalidateQueries({ queryKey: DUPLICATES_KEY });
    },
  });

  const failure = settle.error ?? decide.error;

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
      {failure && (
        <p role="alert" className="text-xs text-red-400">
          {failureMessage(failure, copy.actionError, t.roleGate.forbidden)}
        </p>
      )}
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
          {summary.currency && (
            <>
              <div>
                <dt className="text-xs text-muted-foreground">{copy.revenue}</dt>
                <dd className="font-medium tabular-nums">{fmtIn(summary.revenue_cents / 100, summary.currency)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{copy.expense}</dt>
                <dd className="font-medium tabular-nums">{fmtIn(summary.expense_cents / 100, summary.currency)}</dd>
              </div>
            </>
          )}
        </dl>
      )}
      {summary && !summary.currency && summary.currency_totals.length > 0 && (
        /* No single headline: every currency on its own, side by side. */
        <dl className="grid gap-2 text-sm sm:grid-cols-2" data-testid="per-currency-totals">
          {summary.currency_totals.map((c) => (
            <div key={c.currency} className="rounded-md border border-border p-2">
              <dt className="text-xs font-medium text-muted-foreground">{shownCode(c.currency, t.otherCurrency.unknown)}</dt>
              <dd className="tabular-nums">
                {copy.revenue}: {fmtIn((c.revenue_cents ?? 0) / 100, c.currency)} · {copy.expense}:{" "}
                {fmtIn((c.expense_cents ?? 0) / 100, c.currency)}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {summary && (
        <BaseCurrencyNotice state={summary.base_state} base={summary.currency} confirmPath={summary.confirm_path} />
      )}
      {summary && summary.currency && (
        <OtherCurrencyLines items={summary.other_currencies} base={summary.currency} ratios />
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
      {!!settlements?.length && (
        <div className="space-y-2">
          <p className="text-xs font-medium">{copy.settlementsTitle.replace("{n}", String(settlements.length))}</p>
          <ul className="space-y-2">
            {settlements.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3">
                <div className="min-w-0 text-xs">
                  <p className="font-medium tabular-nums">
                    {s.row.transaction_date} · {fmtIn(s.amount_cents / 100, s.row.currency)}
                  </p>
                  <p>{s.row.description}</p>
                  {(s.items?.length ? s.items : [s.item]).map((it, k) => (
                    <p key={k} className="text-muted-foreground">
                      {copy.settlesInvoice
                        .replace("{invoice}", it.description ?? "")
                        .replace("{amount}", fmt(it.amount_cents / 100))}
                    </p>
                  ))}
                </div>
                <div className="flex shrink-0 gap-2">
                  <CanButton action="edit" size="sm" variant="outline" disabled={settle.isPending}
                    onClick={() => settle.mutate({ id: s.id, action: "confirm" })}>
                    {copy.settleYes}
                  </CanButton>
                  <CanButton action="edit" size="sm" variant="outline" disabled={settle.isPending}
                    onClick={() => settle.mutate({ id: s.id, action: "reject" })}>
                    {copy.settleNo}
                  </CanButton>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {!!duplicates?.length && (
        <div className="space-y-2">
          <p className="text-xs font-medium">{copy.duplicatesTitle.replace("{n}", String(duplicates.length))}</p>
          <ul className="space-y-2">
            {duplicates.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3">
                <div className="min-w-0 text-xs">
                  <p className="font-medium tabular-nums">
                    {row.transaction_date} · {fmtIn(row.amount_cents / 100, row.currency)}
                  </p>
                  <p>{row.description}</p>
                  {row.matches?.map((match) => (
                    <p key={match.id} className="text-muted-foreground">
                      {copy.alreadyThere.replace("{description}", match.description ?? "")}
                    </p>
                  ))}
                </div>
                <div className="flex shrink-0 gap-2">
                  <CanButton action="edit"
                    size="sm"
                    variant="outline"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ id: row.id, action: "keep" })}
                  >
                    {copy.keep}
                  </CanButton>
                  <CanButton action="edit"
                    size="sm"
                    variant="outline"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ id: row.id, action: "exclude" })}
                  >
                    {copy.exclude}
                  </CanButton>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
