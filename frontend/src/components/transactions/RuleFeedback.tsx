"use client";

import { useState } from "react";
import { Loader2, RefreshCw, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useI18n } from "@/hooks/useI18n";
import { rerunAnalysis } from "@/lib/api/cfo";
import type { Transaction } from "@/types";

/**
 * Plan v5 §F0 — the user sees that their corrections stick.
 *
 * `UserRuleBadge` marks a row whose category came from the org's own rule (or
 * a hand edit). `RuleRerunBanner` appears after a standing rule is saved: the
 * analyses it matches were derived from the old categories, and a rerun
 * recomputes them from their files with the rule applied.
 */
export function UserRuleBadge({ source }: { source: Transaction["category_source"] }) {
  const { t } = useI18n();
  const r = t.ruleFeedback;
  if (source !== "user_rule" && source !== "user_edit") return null;
  const isRule = source === "user_rule";
  return (
    <span
      title={isRule ? r.badgeRuleHint : r.badgeEditHint}
      className="ml-1.5 rounded border border-brass-400/30 bg-brass-950/60 px-1 py-px text-[10px] font-medium text-brass-300"
    >
      {isRule ? r.badgeRule : r.badgeEdit}
    </span>
  );
}

export function RuleRerunBanner({
  jobIds,
  onDismiss,
}: {
  jobIds: string[];
  onDismiss: () => void;
}) {
  const { t } = useI18n();
  const r = t.ruleFeedback;
  const queryClient = useQueryClient();
  const [state, setState] = useState<"idle" | "running" | "done">("idle");
  const [started, setStarted] = useState(0);

  if (jobIds.length === 0) return null;
  const n = String(jobIds.length);

  async function rerunAll() {
    setState("running");
    // Each rerun is its own atomic reopen + enqueue; a sealed or in-review
    // analysis answers 409 and is counted as skipped, not as a failure.
    const results = await Promise.allSettled(jobIds.map((id) => rerunAnalysis(id)));
    const ok = results.filter((res) => res.status === "fulfilled").length;
    setStarted(ok);
    setState("done");
    for (const id of jobIds) {
      void queryClient.invalidateQueries({ queryKey: ["dashboard", id] });
      void queryClient.invalidateQueries({ queryKey: ["transactions", id] });
    }
  }

  return (
    <output className="mb-4 flex items-start justify-between gap-4 rounded-lg border border-brass-400/30 bg-brass-950/40 px-4 py-3 text-sm">
      <div className="space-y-1">
        <p className="font-medium text-foreground">{r.bannerTitle.replace("{n}", n)}</p>
        {state === "done" ? (
          <p className="text-xs text-muted-foreground">
            {started === jobIds.length
              ? r.queued.replace("{n}", String(started))
              : r.partial.replace("{ok}", String(started)).replace("{n}", n)}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">{r.bannerBody}</p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {state !== "done" && (
          <button
            type="button"
            onClick={() => void rerunAll()}
            disabled={state === "running"}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
          >
            {state === "running" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {state === "running" ? r.rerunning : r.rerun}
          </button>
        )}
        <button
          type="button"
          onClick={onDismiss}
          aria-label={r.dismiss}
          className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>
    </output>
  );
}
