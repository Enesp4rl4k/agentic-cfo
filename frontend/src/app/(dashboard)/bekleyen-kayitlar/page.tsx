"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageHead } from "@/components/brand-app/PageHead";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { useI18n } from "@/hooks/useI18n";
import { DirectionMappings } from "@/components/held-rows/DirectionMappings";
import { FileDirectionCard } from "@/components/held-rows/FileDirectionCard";
import {
  answerFileDirection,
  confirmBaseCurrency,
  getBaseCurrency,
  listDirectionMappings,
  listFileQuestions,
  listHeldRows,
  rejectHeldRows,
  releaseHeldRows,
  revokeDirectionMapping,
  type HeldAction,
  type HeldCorrection,
  type HeldRow,
} from "@/lib/api/heldRows";

const HELD_KEY = ["held-rows"];

/** What a row still lacks to be accepted: the fields a person must supply. */
function lacking(row: HeldRow): Array<keyof HeldCorrection> {
  const out: Array<keyof HeldCorrection> = [];
  if (!row.currency) out.push("currency");
  if (!row.type) out.push("type");
  if (!row.amount_cents) out.push("amount_cents");
  if (row.reasons.includes("date_unreadable")) out.push("transaction_date");
  return out;
}

/**
 * Rows the system would not book alone. Each shows its source document, what was extracted and the
 * reason it waits; the person accepts it as it is, corrects what was the problem and accepts it, or
 * rejects it. These rows are in no total until accepted.
 */
export default function BekleyenKayitlarPage() {
  const { t } = useI18n();
  const copy = t.heldRows;
  const fmt = useCurrencyFormat();
  const queryClient = useQueryClient();
  const jobId = useSearchParams()?.get("job") ?? undefined;
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<HeldCorrection>({});
  const [currency, setCurrency] = useState("");

  const rows = useQuery({ queryKey: [...HELD_KEY, jobId ?? "all"], queryFn: () => listHeldRows(jobId) });
  const base = useQuery({ queryKey: ["base-currency"], queryFn: getBaseCurrency });
  const files = useQuery({ queryKey: [...HELD_KEY, "files"], queryFn: listFileQuestions });
  const mappings = useQuery({ queryKey: [...HELD_KEY, "mappings"], queryFn: listDirectionMappings });

  const refreshed = () => {
    setFailed(false);
    setEditing(null);
    setDraft({});
    for (const key of [HELD_KEY, ["base-currency"], ["cash-radar"], ["ledger-summary"]]) {
      queryClient.invalidateQueries({ queryKey: key });
    }
  };
  const answer = useMutation({
    mutationFn: ({ release, action }: { release: boolean; action: HeldAction }) =>
      release ? releaseHeldRows(action) : rejectHeldRows(action),
    onSuccess: refreshed,
    onError: () => setFailed(true),
  });
  const fileAnswer = useMutation({
    mutationFn: (v: Parameters<typeof answerFileDirection>[0]) => answerFileDirection(v),
    onSuccess: refreshed,
    onError: () => setFailed(true),
  });
  const forget = useMutation({
    mutationFn: (id: string) => revokeDirectionMapping(id),
    onSuccess: refreshed,
    onError: () => setFailed(true),
  });
  const confirm = useMutation({
    mutationFn: () => confirmBaseCurrency(currency.trim().toUpperCase()),
    onSuccess: refreshed,
    onError: () => setFailed(true),
  });

  // Rows of a file waiting on its one question are answered through that question, not one by one.
  const list = (rows.data ?? []).filter((r) => !r.direction_file);
  const fileList = files.data ?? [];
  const waitingForCurrency = list.some((r) => r.reasons.includes("currency_unknown"));
  const reasonText = (code: string) => (copy.reasons as Record<string, string>)[code] ?? code;
  const sameDocument = (row: HeldRow) =>
    row.document_id ? list.filter((o) => o.job_id === row.job_id && o.document_id === row.document_id) : [];

  return (
    <div className="space-y-4 p-5">
      <PageHead title={copy.title} subtitle={copy.subtitle} />
      {failed && <p role="alert" className="text-sm text-destructive">{copy.actionFailed}</p>}
      {rows.isError && <p role="alert" className="text-sm text-destructive">{copy.failed}</p>}

      {waitingForCurrency && !base.data?.confirmed && (
        <Card className="space-y-2 p-4">
          <p className="text-sm font-semibold">{copy.currencyTitle}</p>
          <p className="text-sm text-muted-foreground">{copy.currencyBody}</p>
          <div className="flex gap-2">
            <Input
              aria-label={copy.currency}
              value={currency}
              maxLength={3}
              placeholder="TRY"
              onChange={(e) => setCurrency(e.target.value)}
              className="w-24"
            />
            <Button disabled={currency.trim().length !== 3 || confirm.isPending} onClick={() => confirm.mutate()}>
              {copy.currencyConfirm}
            </Button>
          </div>
        </Card>
      )}

      {fileList.map((file) => (
        <FileDirectionCard
          key={`${file.job_id}-${file.file_key}`}
          file={file}
          pending={fileAnswer.isPending}
          onAnswer={(answer, remember) =>
            fileAnswer.mutate({ job_id: file.job_id, file_key: file.file_key, answer, remember })
          }
        />
      ))}

      {!rows.isLoading && !rows.isError && list.length === 0 && fileList.length === 0 && (
        <p className="text-sm text-muted-foreground">{copy.empty}</p>
      )}

      <DirectionMappings mappings={mappings.data ?? []} pending={forget.isPending} onRevoke={(id) => forget.mutate(id)} />

      <ul className="space-y-3">
        {list.map((row) => {
          const missing = lacking(row);
          const mates = sameDocument(row);
          return (
            <li key={row.id}>
              <Card className="space-y-2 p-4">
                <div className="flex flex-wrap justify-between gap-2">
                  <div>
                    <p className="text-sm font-medium">{row.description ?? row.vendor ?? "—"}</p>
                    <p className="text-xs text-muted-foreground">
                      {copy.from}: {row.source.filename ?? row.source.job_id}
                    </p>
                  </div>
                  <div className="text-right text-sm tabular-nums">
                    {row.amount_cents ? `${fmt(row.amount_cents / 100)} ${row.currency ?? copy.unknownCurrency}` : copy.unknownAmount}
                    {row.currency_assumed && <span className="ml-1 text-xs text-muted-foreground">({copy.assumedCurrency})</span>}
                    <p className="text-xs text-muted-foreground">
                      {row.transaction_date?.slice(0, 10) ?? copy.unknownDate} ·{" "}
                      {row.type ? (row.type === "income" ? copy.income : copy.expense) : copy.unknownDirection}
                    </p>
                  </div>
                </div>
                <p className="text-xs text-amber-500">{row.reasons.map(reasonText).join(" · ")}</p>

                {editing === row.id && (
                  <div className="flex flex-wrap items-end gap-2">
                    {missing.includes("type") && (
                      <select
                        aria-label={copy.direction}
                        className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                        value={draft.type ?? ""}
                        onChange={(e) => setDraft({ ...draft, type: (e.target.value || undefined) as HeldCorrection["type"] })}
                      >
                        <option value="">{copy.direction}</option>
                        <option value="income">{copy.income}</option>
                        <option value="expense">{copy.expense}</option>
                      </select>
                    )}
                    {missing.includes("currency") && (
                      <Input aria-label={copy.currency} maxLength={3} className="w-24" placeholder="TRY"
                        onChange={(e) => setDraft({ ...draft, currency: e.target.value })} />
                    )}
                    {missing.includes("transaction_date") && (
                      <Input aria-label={copy.date} type="date" className="w-40"
                        onChange={(e) => setDraft({ ...draft, transaction_date: e.target.value })} />
                    )}
                    {missing.includes("amount_cents") && (
                      <Input aria-label={copy.amount} type="number" className="w-36"
                        onChange={(e) => setDraft({ ...draft, amount_cents: e.target.value ? Number(e.target.value) : undefined })} />
                    )}
                    <Button
                      onClick={() => answer.mutate({ release: true, action: { ids: [row.id], corrections: { [row.id]: draft } } })}
                    >
                      {copy.save}
                    </Button>
                    <Button variant="ghost" onClick={() => setEditing(null)}>{copy.cancel}</Button>
                  </div>
                )}

                <div className="flex flex-wrap gap-2">
                  <Button
                    disabled={missing.length > 0}
                    title={missing.length > 0 ? copy.blocked : undefined}
                    onClick={() => answer.mutate({ release: true, action: { ids: [row.id] } })}
                  >
                    {copy.release}
                  </Button>
                  {missing.length > 0 && (
                    <Button variant="outline" onClick={() => { setEditing(row.id); setDraft({}); }}>
                      {copy.correct}
                    </Button>
                  )}
                  <Button variant="outline" onClick={() => answer.mutate({ release: false, action: { ids: [row.id] } })}>
                    {copy.reject}
                  </Button>
                  {mates.length > 1 && (
                    <Button
                      variant="ghost"
                      onClick={() => answer.mutate({ release: true, action: { document_id: row.document_id ?? undefined, job_id: row.job_id } })}
                    >
                      {copy.releaseGroup} ({mates.length})
                    </Button>
                  )}
                </div>
              </Card>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
