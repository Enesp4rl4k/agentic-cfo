"use client";

import { cn } from "@/lib/utils";
import { useI18n } from "@/hooks/useI18n";

export type ProvenanceClass = "real" | "estimated" | "benchmark";

/**
 * 1.3 (U7) — the one place that turns a wire `data_source` into the three
 * honesty classes of DESIGN.md ("distinguish real, estimated and benchmark
 * data close to the metric"). Mirrors backend
 * `app/platform/provenance.py` (SYNTHETIC_SOURCES): real / manual /
 * rule_based are measured or deterministic (non-synthetic), estimated /
 * derived are extrapolations, benchmark is a sector assumption. Unknown or
 * missing values return null — the card stays unbadged rather than inventing
 * a calm "Gerçek" label for something nobody described.
 */
export function classifyDataSource(
  dataSource?: string | null,
): ProvenanceClass | null {
  switch ((dataSource ?? "").toLowerCase().trim()) {
    case "real":
    case "manual":
    case "rule_based":
      return "real";
    case "estimated":
    case "derived":
      return "estimated";
    case "benchmark":
      return "benchmark";
    default:
      return null;
  }
}

const CHIP: Record<ProvenanceClass, string> = {
  real: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
  estimated: "border-amber-500/30 bg-amber-500/10 text-amber-400",
  benchmark: "border-blue-500/30 bg-blue-500/10 text-blue-400",
};

const HINT_KEY: Record<
  ProvenanceClass,
  "realHint" | "estimatedHint" | "benchmarkHint"
> = {
  real: "realHint",
  estimated: "estimatedHint",
  benchmark: "benchmarkHint",
};

/**
 * Attaches next to a metric (DESIGN.md: provenance stays close to the
 * number). Renders nothing when the wire carries no recognisable source —
 * a wrong badge is worse than no badge.
 */
export function ProvenanceBadge({
  dataSource,
  basis,
  className,
}: {
  dataSource?: string | null;
  /** The backend's `basis` sentence — appended to the hint when present. */
  basis?: string | null;
  className?: string;
}) {
  const { t } = useI18n();
  const cls = classifyDataSource(dataSource);
  if (!cls) return null;

  const hint = basis
    ? `${t.provenance[HINT_KEY[cls]]} — ${basis}`
    : t.provenance[HINT_KEY[cls]];

  return (
    <span
      title={hint}
      aria-label={`${t.provenance[cls]} — ${hint}`}
      className={cn(
        "inline-flex shrink-0 items-center rounded border px-1.5 py-0.5 text-[10px] font-medium",
        CHIP[cls],
        className,
      )}
    >
      {t.provenance[cls]}
    </span>
  );
}
