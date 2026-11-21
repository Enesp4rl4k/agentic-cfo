"use client";

import { useI18n } from "@/hooks/useI18n";
import type { MessageTree } from "@/lib/i18n";

type Reason = Record<string, unknown>;
type Copy = MessageTree["heldAnalysis"]["reasons"];

const text = (v: unknown) => (typeof v === "string" ? v : "");
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const fill = (template: string, values: Record<string, string>) =>
  Object.entries(values).reduce((s, [k, v]) => s.replaceAll(`{${k}}`, v), template).replace(/\s+$/, "");

/** One reason code, in words. The backend sends facts (app/services/held_analysis.py); wording lives here. */
export function reasonText(copy: Copy, reason: Reason): string {
  switch (reason.code) {
    case "confidence_low": {
      const min = num(reason.min_confidence);
      const threshold = num(reason.threshold);
      if (min === null || threshold === null) return copy.unspecified;
      return fill(copy.confidence, { pct: String(Math.round(min * 100)), threshold: String(Math.round(threshold * 100)) });
    }
    case "weakest_step": {
      const pct = num(reason.confidence);
      const values = { step: text(reason.step), detail: text(reason.detail), pct: pct === null ? "" : String(Math.round(pct * 100)) };
      return fill(pct === null ? copy.weakestNoPct : copy.weakest, values);
    }
    case "step_flagged":
      return fill(copy.step, { step: text(reason.step), detail: text(reason.detail) });
    case "rows_waiting": {
      const count = String(num(reason.count) ?? 0);
      return reason.all_rows === true
        ? fill(copy.rowsAll, { count, summary: text(reason.summary) })
        : fill(copy.rows, { count });
    }
    default:
      return copy.unspecified;
  }
}

/** Why an analysis is waiting, one sentence per reason. */
export function HeldReasons({ reasons, className }: Readonly<{ reasons: Reason[]; className?: string }>) {
  const { t } = useI18n();
  const copy = t.heldAnalysis.reasons;
  const shown = reasons.length > 0 ? reasons : [{ code: "unspecified" }];
  return (
    <ul className={className ?? "m-0 list-none space-y-1 p-0"}>
      {shown.map((reason, i) => (
        <li key={`${text(reason.code)}-${i}`} className="text-sm text-muted-foreground">
          {reasonText(copy, reason)}
        </li>
      ))}
    </ul>
  );
}
