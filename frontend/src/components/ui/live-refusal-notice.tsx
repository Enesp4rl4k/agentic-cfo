"use client";

import { useI18n } from "@/hooks/useI18n";
import type { LiveRefusal } from "@/lib/liveRefusal";

/**
 * A live connection the server closed as "not allowed". Says so, says why when the server said (its own
 * sentence, which already names who can change the company's IP allow-list and how to get back in), and
 * otherwise gives the general sentence and the recovery steps. It does not reconnect by itself.
 */
export function LiveRefusalNotice({ refusal }: Readonly<{ refusal: LiveRefusal | null }>) {
  const { t } = useI18n();
  if (!refusal) return null;
  const m = t.liveRefusal;
  return (
    <div role="alert" className="space-y-1 rounded-md border border-destructive p-3 text-sm">
      <p className="m-0 font-semibold">{m.title}</p>
      <p className="m-0">{refusal.sentence ?? m.generic}</p>
      {refusal.sentence === null && <p className="m-0 text-xs text-muted-foreground">{m.recovery}</p>}
    </div>
  );
}
