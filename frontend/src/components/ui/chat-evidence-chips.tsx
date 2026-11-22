"use client";

import { useI18n } from "@/hooks/useI18n";
import { cn } from "@/lib/utils";

export interface ChatEvidenceMeta {
  evidence_found?: boolean;
  evidence_tx_count?: number;
  evidence_semantic_count?: number;
  evidence_retriever_version?: string;
  grounding_validated?: boolean;
}

export function ChatEvidenceChips({
  meta,
  className,
}: {
  meta: ChatEvidenceMeta | null | undefined;
  className?: string;
}) {
  const { t } = useI18n();
  if (!meta) return null;

  const tx = meta.evidence_tx_count ?? 0;
  const semantic = meta.evidence_semantic_count ?? 0;
  const total = tx + semantic;

  if (total === 0 && meta.evidence_found === false) {
    return (
      <div className={cn("flex flex-wrap gap-1.5 mt-2", className)}>
        <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-400">
          {t.evidenceUi.noEvidence}
        </span>
      </div>
    );
  }

  if (total === 0) return null;

  return (
    <div className={cn("flex flex-wrap items-center gap-1.5 mt-2", className)}>
      {tx > 0 && (
        <span className="rounded-md bg-emerald-500/10 px-2 py-0.5 text-[10px] font-mono text-emerald-400">
          {t.evidenceUi.tx.replace("{n}", String(tx))}
        </span>
      )}
      {semantic > 0 && (
        <span className="rounded-md bg-primary/10 px-2 py-0.5 text-[10px] font-mono text-primary">
          {t.evidenceUi.semantic.replace("{n}", String(semantic))}
        </span>
      )}
      {meta.evidence_retriever_version && (
        <span className="text-[10px] text-muted-foreground">
          {meta.evidence_retriever_version}
        </span>
      )}
      {meta.grounding_validated === false && (
        <span className="rounded-md border border-amber-500/30 px-2 py-0.5 text-[10px] text-amber-400">
          {t.evidenceUi.disclaimer}
        </span>
      )}
    </div>
  );
}
