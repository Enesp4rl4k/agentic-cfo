"use client";

import { useI18n } from "@/hooks/useI18n";
import type { ErasureRequestRow } from "./types";

type Props = {
  rows: ErasureRequestRow[];
  supportContact: string | null;
  day: (iso: string | null) => string;
  onCancel: (row: ErasureRequestRow) => void;
};

/**
 * One line per live erasure request, in plain words by state. The server's fixed codes (`failure_code`,
 * `blocked_reason`) are never shown; the person sees what is happening, whether it can still be stopped and, when
 * it did not go through, who to ask (the operator's `SUPPORT_CONTACT` when configured) with a short reference.
 */
export function ErasureStates({ rows, supportContact, day, onCancel }: Props) {
  const { t } = useI18n();
  const c = t.settingsPrivacy.company;
  const s = c.states;

  const sentence = (row: ErasureRequestRow): string => {
    switch (row.status) {
      case "pending":
        return s.pending;
      case "scheduled":
        return s.scheduled.replace("{date}", day(row.execute_after));
      case "executing":
        return s.executing;
      case "cleanup_pending":
        return s.cleanupPending;
      case "failed":
        return s.failed;
      default:
        return s.blocked;
    }
  };
  const needsHelp = (row: ErasureRequestRow) => row.status === "failed" || row.status === "blocked";

  return (
    <div>
      <h4 className="text-sm font-medium">{c.pendingTitle}</h4>
      <ul className="space-y-3 text-sm">
        {rows.map((row) => (
          <li key={row.request_id} className="space-y-1 rounded-md border border-border p-3" data-status={row.status}>
            <p className="font-medium">{row.scope === "org" ? c.kindOrg : c.kindMember}</p>
            <p>{sentence(row)}</p>
            {needsHelp(row) && (
              <p>{supportContact ? s.contactWith.replace("{contact}", supportContact) : s.contactNone}</p>
            )}
            <p className="text-xs text-muted-foreground">{s.reference.replace("{id}", row.request_id.slice(0, 8))}</p>
            {row.cancellable && (
              <button type="button" className="min-h-[44px] underline" onClick={() => onCancel(row)}>{c.eraseCancel}</button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
