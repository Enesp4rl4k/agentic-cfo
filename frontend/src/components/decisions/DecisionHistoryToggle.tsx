"use client";

import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { DecisionHistory } from "@/components/decisions/DecisionHistory";
import { useI18n } from "@/hooks/useI18n";

/**
 * "Karar geçmişi" under one object of a list: closed until asked for, so a page of forty rows does not
 * ask the server forty questions. Read-only; opening it only reads.
 */
export function DecisionHistoryToggle({
  targetType,
  targetId,
  kind,
}: {
  targetType: string;
  targetId: string;
  kind?: string;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const panel = useId();
  return (
    <div className="space-y-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-expanded={open}
        aria-controls={panel}
        onClick={() => setOpen((v) => !v)}
      >
        {t.decisionLog.historyTitle}
      </Button>
      <div id={panel} hidden={!open}>
        {open && <DecisionHistory targetType={targetType} targetId={targetId} kind={kind} />}
      </div>
    </div>
  );
}
