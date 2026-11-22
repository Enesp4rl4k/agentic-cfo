"use client";

import { useI18n } from "@/hooks/useI18n";
import { mapLabel } from "@/lib/i18n/codes";
import { cn } from "@/lib/utils";

export function BaselineSourceBadge({
  source,
  className,
}: {
  source: string | null | undefined;
  className?: string;
}) {
  const { t } = useI18n();
  const key = (source || "none").toLowerCase();
  const label = mapLabel(t, t.evidenceUi.baselineSources, key);
  const isSemantic = key === "semantic";

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
        isSemantic
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
          : "border-border bg-muted/30 text-muted-foreground",
        className
      )}
      title={t.evidenceUi.baselineTitle.replace("{label}", label)}
    >
      {t.evidenceUi.baselinePrefix.replace("{label}", label)}
    </span>
  );
}
