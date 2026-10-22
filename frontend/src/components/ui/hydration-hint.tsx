"use client";

import { Loader2 } from "lucide-react";
import { useI18n } from "@/hooks/useI18n";

/**
 * Shown while the stored analysis is being fetched from CompanyContext
 * (DEVELOPMENT_PLAN 1.5 / U2). The form opens immediately and is never
 * delayed by this — the hint only replaces the *empty* look during the
 * fetch, so the page does not flash "no analysis" and then fill in: with
 * Redis down the context call may take up to its 2s bound, and without a
 * signal the flash reads as data loss.
 */
export function HydrationHint() {
  const { t } = useI18n();
  return (
    <p
      role="status"
      className="flex items-center gap-2 text-sm text-muted-foreground"
    >
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      {t.empty.hydration}
    </p>
  );
}
