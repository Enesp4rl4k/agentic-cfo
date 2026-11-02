"use client";

import { ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useI18n } from "@/hooks/useI18n";
import type { GateDecision } from "@/lib/api/agentReview";

/** Says a result on screen is not yet the company's: it awaits the owner's approval. */
export function HeldResultNotice({ gate }: { gate?: GateDecision | null }) {
  const { t } = useI18n();
  if (!gate?.awaiting_review) return null;
  return (
    <div role="status" className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/5 p-3 text-xs">
      <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
      <div>
        <p>{t.reviewQueue.heldNotice}</p>
        {gate.reasons.map((reason) => (
          <p key={reason} className="mt-0.5 text-muted-foreground">{reason}</p>
        ))}
        <Link href="/command-center" className="mt-1 inline-block font-medium underline underline-offset-2">
          {t.reviewQueue.goToQueue}
        </Link>
      </div>
    </div>
  );
}
