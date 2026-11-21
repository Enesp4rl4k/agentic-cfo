"use client";

import { useState } from "react";
import Link from "next/link";
import { useI18n } from "@/hooks/useI18n";
import { cn } from "@/lib/utils";

export interface OneTapOption {
  label: string;
  hint?: string;
  /** Sends the choice. It must reject when the server refuses, so the card stays. */
  run: () => Promise<unknown>;
}

export interface OneTapDecision {
  key: string;
  kind: string;
  title: string;
  amount: string;
  meta?: string;
  options: OneTapOption[];
}

/**
 * The approvals one at a time, for a phone: a card, its options as large buttons, and a way to leave
 * a decision for the desk. A tap sends the choice at once and the next card opens only once the
 * server has accepted it; a refusal keeps the card and says so. There is no undo, because the server
 * keeps no undo for these decisions; the person is told what they are about to do by the option
 * itself. The queue is the one the person opened: lists refreshing underneath do not move it.
 */
export function OneTapQueue({ decisions, onClose }: { decisions: OneTapDecision[]; onClose: () => void }) {
  const { t } = useI18n();
  const copy = t.onay;
  const [queue] = useState(decisions);
  const [index, setIndex] = useState(0);
  const [skipped, setSkipped] = useState(0);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const done = index >= queue.length;
  const card = queue[index];

  async function choose(option: OneTapOption) {
    setBusy(true);
    setFailed(false);
    try {
      await option.run();
      setIndex((i) => i + 1);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  function skip() {
    setFailed(false);
    setSkipped((n) => n + 1);
    setIndex((i) => i + 1);
  }

  if (done) {
    return (
      <section aria-label={copy.oneTapDoneLabel} className="mx-auto flex max-w-md flex-col gap-4 py-6 text-center">
        {skipped === 0 ? (
          <>
            <h2 className="tc-display m-0 text-[30px] leading-tight">{copy.oneTapDoneTitle}</h2>
            <p className="m-0 text-sm text-muted-foreground">{copy.oneTapDoneBody}</p>
          </>
        ) : (
          <>
            <h2 className="tc-display m-0 text-[30px] leading-tight">{copy.oneTapSkippedTitle.replace("{n}", String(skipped))}</h2>
            <p className="m-0 text-sm text-muted-foreground">{copy.oneTapSkippedBody}</p>
          </>
        )}
        <Link
          href="/nakit-radari"
          className="inline-flex min-h-[48px] items-center justify-center rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground"
        >
          {copy.oneTapRoute}
        </Link>
        <button type="button" onClick={onClose} className="min-h-[44px] text-sm font-medium text-muted-foreground underline-offset-4 hover:underline">
          {copy.oneTapBack}
        </button>
      </section>
    );
  }

  return (
    <section aria-label={copy.oneTapLabel} className="mx-auto flex max-w-md flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <button type="button" onClick={onClose} className="min-h-[44px] text-sm font-medium text-muted-foreground underline-offset-4 hover:underline">
          {copy.oneTapBack}
        </button>
        <span className="tc-eyebrow text-[11px] text-muted-foreground">
          {copy.oneTapCounter.replace("{i}", String(index + 1)).replace("{n}", String(queue.length))}
        </span>
        <span className="flex gap-1" aria-hidden="true">
          {queue.map((d, i) => (
            <span key={d.key} className={cn("h-1.5 w-4 rounded-full", i < index ? "bg-foreground" : i === index ? "bg-primary" : "bg-border")} />
          ))}
        </span>
      </div>

      <div className="space-y-1 rounded-xl border border-border bg-card p-4">
        <p className="tc-eyebrow m-0 text-[11px] text-muted-foreground">{card.kind}</p>
        <p className="m-0 text-base font-medium">{card.title}</p>
        <p className="tc-mono m-0 text-[26px]">{card.amount}</p>
        {card.meta && <p className="m-0 text-xs text-muted-foreground">{card.meta}</p>}
      </div>

      <p className="m-0 text-sm text-muted-foreground">{copy.oneTapPrompt}</p>
      <div className="flex flex-col gap-2">
        {card.options.map((option) => (
          <button
            key={option.label}
            type="button"
            disabled={busy}
            onClick={() => void choose(option)}
            className="flex min-h-[56px] flex-col items-start justify-center rounded-xl border border-border bg-card px-4 py-3 text-left transition-colors hover:border-[color:var(--tc-ember)] disabled:opacity-60"
          >
            <span className="text-base font-semibold">{option.label}</span>
            {option.hint && <span className="text-xs text-muted-foreground">{option.hint}</span>}
          </button>
        ))}
      </div>
      {failed && <p role="alert" className="m-0 text-sm text-destructive">{copy.actionFailed}</p>}
      <button type="button" onClick={skip} disabled={busy} className="min-h-[44px] text-sm font-medium text-muted-foreground underline-offset-4 hover:underline">
        {copy.oneTapSkip}
      </button>
    </section>
  );
}
