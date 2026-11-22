"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import type { FileAnswer, FileQuestion } from "@/lib/api/heldRows";

const SAMPLE_COLUMNS = ["date", "description", "amount", "debit", "credit", "direction", "balance"];

/**
 * ONE question for a whole statement file whose direction nobody could place: what was detected, a few
 * sample rows, and the options. The answer is applied to every row of the file by the server, so the
 * person answers once instead of once per row.
 */
export function FileDirectionCard({
  file,
  pending,
  canRemember,
  onAnswer,
}: Readonly<{
  file: FileQuestion;
  pending: boolean;
  canRemember: boolean;
  onAnswer: (answer: FileAnswer, remember: boolean, standing?: boolean) => void;
}>) {
  const { t } = useI18n();
  const copy = t.heldRows;
  const [remember, setRemember] = useState(true);
  const [standing, setStanding] = useState(false);
  const roles = copy.fileRoles as Record<string, string>;
  const options = copy.fileOptions as Record<string, string>;
  const columns = file.question?.columns ?? [];
  const samples = file.question?.samples ?? [];
  const shown = SAMPLE_COLUMNS.filter((role) => samples.some((s) => role in s));
  // Only a convention (or a balance that contradicts the columns) is a property of the statement FORMAT;
  // "this file holds only one kind" is a statement about one file and is never remembered.
  const rememberable =
    file.reason === "convention_unverified" || file.reason === "balance_contradicts" || file.reason === "sign_unconfirmed";
  // A convention is only worth remembering for a known account; without one it could never be checked. The sign of
  // an export is a fact about the export's format, so a sign answer does not need the account.
  const needsAccount = file.reason === "convention_unverified";
  const storable = rememberable && canRemember && (file.identity || !needsAccount);
  const mapping = file.question?.mapping ?? [];
  // The earlier answer for the same header words, not evidenced as the same source: asked again with it pre-selected.
  const previous = file.reason === "sign_unconfirmed" ? (file.previous ?? file.question?.previous ?? null) : null;
  const previousOption = previous ? (copy.fileOptions as Record<string, string>)[previous.answer] : null;
  // An identity-less file may become a standing rule, only by this explicit choice.
  const canStand = file.reason === "sign_unconfirmed" && !file.identity && storable;
  const outLabel = mapping.find((m) => m.means === "expense")?.label;
  const body = {
    no_signal: copy.fileBodyNoSignal,
    balance_contradicts: copy.fileBodyBalance,
    convention_unverified: copy.fileBodyConvention,
    balance_inconclusive: copy.fileBodyInconclusive,
    sign_unconfirmed: file.question?.uniform ? copy.fileBodySignUniform : copy.fileBodySign,
  }[file.reason];
  const totals = file.question?.totals;
  const money = (kurus: number) => (kurus / 100).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const meaning = (m: { label: string; means: string }) =>
    `${m.label} → ${m.means === "expense" ? copy.expense : copy.income}`;

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap justify-between gap-2">
        <p className="text-sm font-semibold">{copy.fileTitle}</p>
        <p className="text-xs text-muted-foreground">{copy.fileRows.replace("{count}", String(file.rows))}</p>
      </div>
      {file.reason === "convention_unverified" && outLabel && (
        <p className="text-sm font-medium">{copy.fileConventionQuestion.replace("{label}", outLabel)}</p>
      )}
      {file.reason === "sign_unconfirmed" && <p className="text-sm font-medium">{copy.fileSignQuestion}</p>}
      {previous && (
        <p className="rounded-md border p-2 text-sm" data-testid="previous-answer">
          {copy.filePreviousAnswer
            .replace("{answer}", previousOption ?? previous.answer)
            .replace("{source}", previous.account ?? previous.columns)}
        </p>
      )}
      <p className="text-sm text-muted-foreground">{body}</p>
      {file.reason === "sign_unconfirmed" && totals && (
        <p className="text-xs text-muted-foreground">
          {copy.fileSignReading
            .replace("{inIncome}", money(totals.as_read.income))
            .replace("{inExpense}", money(totals.as_read.expense))
            .replace("{outIncome}", money(totals.inverted.income))
            .replace("{outExpense}", money(totals.inverted.expense))}
        </p>
      )}
      {mapping.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {copy.fileConventionMapping.replace("{mapping}", mapping.map(meaning).join(" · "))}
        </p>
      )}
      {file.question?.note && file.reason === "balance_inconclusive" && (
        <p className="text-xs text-muted-foreground">{file.question.note}</p>
      )}

      {columns.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {copy.fileColumns}:{" "}
          {columns.map((c) => (c.role ? `${c.name} (${roles[c.role] ?? c.role})` : c.name)).join(" · ")}
        </p>
      )}
      {samples.length > 0 && (
        <div className="overflow-x-auto">
          <p className="mb-1 text-xs font-medium text-muted-foreground">{copy.fileSamples}</p>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-muted-foreground">
                {shown.map((role) => (
                  <th key={role} className="pr-3 font-medium">{roles[role] ?? role}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {samples.map((sample, i) => (
                <tr key={`${file.file_key}-${i}`}>
                  {shown.map((role) => (
                    <td key={role} className="pr-3 tabular-nums">{sample[role] ?? ""}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {storable && (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          {copy.fileRemember}
        </label>
      )}
      {canStand && remember && (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={standing} onChange={(e) => setStanding(e.target.checked)} />
          {copy.fileStanding}
        </label>
      )}
      {rememberable && !canRemember && <p className="text-xs text-muted-foreground">{copy.fileRememberDenied}</p>}
      {rememberable && canRemember && !storable && (
        <p className="text-xs text-muted-foreground">{copy.fileNoAccount}</p>
      )}
      <div className="flex flex-wrap gap-2">
        {[...file.options]
          .sort((a, b) => Number(b === previous?.answer) - Number(a === previous?.answer))
          .map((answer) => (
            <Button
              key={answer}
              variant={answer === "mixed" || answer === "only_income" || answer === "only_expense" ? "outline" : "default"}
              disabled={pending}
              aria-pressed={answer === previous?.answer}
              onClick={() => onAnswer(answer, storable && remember && answer !== "mixed", canStand && standing && answer !== "mixed")}
            >
              {answer === previous?.answer ? `${copy.fileConfirm}: ` : ""}
              {options[answer] ?? answer}
            </Button>
          ))}
      </div>
    </Card>
  );
}
