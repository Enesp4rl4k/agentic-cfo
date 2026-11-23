"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { DecisionHistoryToggle } from "@/components/decisions/DecisionHistoryToggle";
import { useI18n } from "@/hooks/useI18n";
import type { DirectionMapping } from "@/lib/api/heldRows";

/**
 * The statement formats whose direction was answered once and is remembered (and the explicit standing
 * rules for files with no account named); each can be forgotten by whoever may decide it, and each says
 * when a verifying balance chain overrode it. Never a silent blank: loading, failed and "none remembered"
 * are each said. Each entry opens its own decision history (remembered, overridden, revoked).
 */
export function DirectionMappings({
  mappings,
  status = "ready",
  pending,
  canRevoke,
  onRevoke,
}: Readonly<{
  mappings: DirectionMapping[];
  status?: "loading" | "error" | "ready";
  pending: boolean;
  canRevoke: boolean;
  onRevoke: (id: string) => void;
}>) {
  const { t } = useI18n();
  const copy = t.heldRows;
  const options = copy.fileOptions as Record<string, string>;
  return (
    <Card id="hatirlanan-cevaplar" className="scroll-mt-20 space-y-2 p-4">
      <p className="text-sm font-semibold">{copy.mappingsTitle}</p>
      <p className="text-sm text-muted-foreground">{copy.mappingsBody}</p>
      {status === "loading" && <Skeleton aria-label={copy.mappingsLoading} className="h-10 w-full" />}
      {status === "error" && (
        <p role="alert" className="text-sm text-destructive">
          {copy.mappingsFailed}
        </p>
      )}
      {status === "ready" && mappings.length === 0 && <p className="text-sm text-muted-foreground">{copy.mappingsEmpty}</p>}
      <ul className="space-y-3">
        {mappings.map((m) => (
          <li key={m.id} className="space-y-2 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span id={`mapping-${m.id}`}>
                <span className="text-muted-foreground">{m.columns || m.signature}</span>
                {" — "}
                {options[m.answer] ?? m.answer}
                {m.account && <span className="text-muted-foreground">{` (${m.account})`}</span>}
                {m.standing && <span className="text-muted-foreground">{` · ${copy.mappingStanding}`}</span>}
                {m.flagged_at && <span className="block text-xs text-amber-500">{`${copy.mappingFlagged}: ${m.flagged_note ?? ""}`}</span>}
              </span>
              {canRevoke && (
                <Button
                  variant="outline"
                  disabled={pending}
                  aria-describedby={`mapping-${m.id}`}
                  onClick={() => onRevoke(m.id)}
                >
                  {copy.mappingRevoke}
                </Button>
              )}
            </div>
            <DecisionHistoryToggle targetType="direction_mapping" targetId={m.id} />
          </li>
        ))}
      </ul>
    </Card>
  );
}
