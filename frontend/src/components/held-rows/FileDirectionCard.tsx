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
  onAnswer,
}: Readonly<{
  file: FileQuestion;
  pending: boolean;
  onAnswer: (answer: FileAnswer, remember: boolean) => void;
}>) {
  const { t } = useI18n();
  const copy = t.heldRows;
  const [remember, setRemember] = useState(true);
  const roles = copy.fileRoles as Record<string, string>;
  const options = copy.fileOptions as Record<string, string>;
  const columns = file.question?.columns ?? [];
  const samples = file.question?.samples ?? [];
  const shown = SAMPLE_COLUMNS.filter((role) => samples.some((s) => role in s));

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap justify-between gap-2">
        <p className="text-sm font-semibold">{copy.fileTitle}</p>
        <p className="text-xs text-muted-foreground">{copy.fileRows.replace("{count}", String(file.rows))}</p>
      </div>
      <p className="text-sm text-muted-foreground">
        {file.reason === "balance_contradicts" ? copy.fileBodyBalance : copy.fileBodyNoSignal}
      </p>

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

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
        {copy.fileRemember}
      </label>
      <div className="flex flex-wrap gap-2">
        {file.options.map((answer) => (
          <Button
            key={answer}
            variant={answer === "mixed" ? "outline" : "default"}
            disabled={pending}
            onClick={() => onAnswer(answer, remember && answer !== "mixed")}
          >
            {options[answer] ?? answer}
          </Button>
        ))}
      </div>
    </Card>
  );
}
