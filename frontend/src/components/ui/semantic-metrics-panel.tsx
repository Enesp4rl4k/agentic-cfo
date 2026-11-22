"use client";

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { useI18n } from "@/hooks/useI18n";
import { cn } from "@/lib/utils";
import {
  formatMetricValue,
  metricSimulationHref,
  type MetricPoint,
} from "@/lib/api/semantic";

interface SemanticMetricsPanelProps {
  metrics: MetricPoint[];
  periodKey?: string;
  className?: string;
  maxItems?: number;
}

function metricLabel(metricId: string): string {
  const tail = metricId.split(".").pop() ?? metricId;
  return tail.replace(/_/g, " ");
}

export function SemanticMetricsPanel({
  metrics,
  periodKey,
  className,
  maxItems = 12,
}: SemanticMetricsPanelProps) {
  const { t } = useI18n();
  const numeric = metrics.filter((m) => m.value != null);
  if (numeric.length === 0) return null;

  const shown = numeric.slice(0, maxItems);

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">{t.evidenceUi.metricsTitle}</h3>
          {periodKey && (
            <p className="text-xs text-muted-foreground">{t.evidenceUi.period.replace("{period}", periodKey)}</p>
          )}
        </div>
        <Link
          href="/command-center"
          className="text-xs text-primary hover:underline"
        >
          {t.evidenceUi.decisionBrief}
        </Link>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {shown.map((m) => (
          <Link
            key={m.metric_id}
            href={metricSimulationHref(m.metric_id)}
            className={cn(
              "group rounded-lg border border-border bg-card p-3",
              "transition-colors hover:border-primary/40 hover:bg-primary/5"
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-xs text-muted-foreground capitalize">
                {metricLabel(m.metric_id)}
              </p>
              <ArrowUpRight
                className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
                aria-hidden="true"
              />
            </div>
            <p className="mt-1 text-lg font-semibold tabular-nums">
              {formatMetricValue(m)}
            </p>
            <p className="mt-1 font-mono text-[10px] text-primary/80">
              {m.metric_id}
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}
