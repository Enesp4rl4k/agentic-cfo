"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import type { DirectionMapping } from "@/lib/api/heldRows";

/** The statement formats whose direction was answered once and is remembered; each can be forgotten. */
export function DirectionMappings({
  mappings,
  pending,
  onRevoke,
}: Readonly<{ mappings: DirectionMapping[]; pending: boolean; onRevoke: (id: string) => void }>) {
  const { t } = useI18n();
  const copy = t.heldRows;
  const options = copy.fileOptions as Record<string, string>;
  if (mappings.length === 0) return null;
  return (
    <Card className="space-y-2 p-4">
      <p className="text-sm font-semibold">{copy.mappingsTitle}</p>
      <p className="text-sm text-muted-foreground">{copy.mappingsBody}</p>
      <ul className="space-y-2">
        {mappings.map((m) => (
          <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span>
              <span className="text-muted-foreground">{m.columns || m.signature}</span>
              {" — "}
              {options[m.answer] ?? m.answer}
            </span>
            <Button variant="outline" disabled={pending} onClick={() => onRevoke(m.id)}>
              {copy.mappingRevoke}
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
