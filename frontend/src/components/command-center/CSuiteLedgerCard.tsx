"use client";

import { useQuery } from "@tanstack/react-query";
import { Users, Layers, Cpu, Sparkles } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useI18n } from "@/hooks/useI18n";
import { getCHROMetrics, getCOOMetrics, getCTOMetrics } from "@/lib/api/csuite";

const CHRO_KEY = ["csuite-chro"];
const COO_KEY = ["csuite-coo"];
const CTO_KEY = ["csuite-cto"];

export function CSuiteLedgerCard() {
  const { t } = useI18n();
  const copy = t.csuiteLedger;

  const { data: chro } = useQuery({ queryKey: CHRO_KEY, queryFn: () => getCHROMetrics(6) });
  const { data: coo } = useQuery({ queryKey: COO_KEY, queryFn: () => getCOOMetrics(90) });
  const { data: cto } = useQuery({ queryKey: CTO_KEY, queryFn: () => getCTOMetrics(6) });

  const hasData =
    (chro && (chro.revenue_cents > 0 || chro.payroll_cents > 0)) ||
    (coo && coo.total_expense_cents > 0) ||
    (cto && cto.total_tech_spend_cents > 0);

  if (!hasData) return null;

  return (
    <Card className="space-y-4 p-4">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />
        <div>
          <h2 className="text-sm font-semibold">{copy.title}</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">{copy.subtitle}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* CHRO Card */}
        {chro && (
          <div className="rounded-lg border border-border/70 bg-muted/15 p-3 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="flex items-center gap-1.5 text-xs font-medium">
                  <Users className="h-3.5 w-3.5 text-pink-400" aria-hidden="true" />
                  {copy.chroTitle}
                </span>
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[10px] font-medium",
                    chro.trend_direction === "increasing"
                      ? "bg-red-400/10 text-red-400"
                      : chro.trend_direction === "decreasing"
                      ? "bg-emerald-400/10 text-emerald-400"
                      : "bg-muted text-muted-foreground"
                  )}
                >
                  {chro.trend_direction === "increasing"
                    ? copy.trendUp
                    : chro.trend_direction === "decreasing"
                    ? copy.trendDown
                    : copy.trendStable}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">{copy.chroRatio}</p>
              <p className="text-xl font-semibold tabular-nums mt-0.5">
                {chro.payroll_ratio_pct !== null ? `${chro.payroll_ratio_pct.toFixed(1)}%` : "—"}
              </p>
            </div>
            {chro.summary && (
              <p className="mt-3 text-xs text-muted-foreground border-t border-border/40 pt-2 line-clamp-2">
                {chro.summary}
              </p>
            )}
          </div>
        )}

        {/* COO Card */}
        {coo && (
          <div className="rounded-lg border border-border/70 bg-muted/15 p-3 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="flex items-center gap-1.5 text-xs font-medium">
                  <Layers className="h-3.5 w-3.5 text-blue-400" aria-hidden="true" />
                  {copy.cooTitle}
                </span>
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[10px] font-medium",
                    coo.concentration_risk === "HIGH"
                      ? "bg-red-400/10 text-red-400"
                      : coo.concentration_risk === "MEDIUM"
                      ? "bg-yellow-400/10 text-yellow-400"
                      : "bg-emerald-400/10 text-emerald-400"
                  )}
                >
                  {coo.concentration_risk === "HIGH"
                    ? copy.riskHigh
                    : coo.concentration_risk === "MEDIUM"
                    ? copy.riskMedium
                    : copy.riskLow}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 mt-1">
                <div>
                  <p className="text-[10px] text-muted-foreground">{copy.cooTop1}</p>
                  <p className="text-base font-semibold tabular-nums">
                    {coo.top1_share_pct.toFixed(1)}%
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-muted-foreground">{copy.cooTop3}</p>
                  <p className="text-base font-semibold tabular-nums">
                    {coo.top3_share_pct.toFixed(1)}%
                  </p>
                </div>
              </div>
            </div>
            {coo.summary && (
              <p className="mt-3 text-xs text-muted-foreground border-t border-border/40 pt-2 line-clamp-2">
                {coo.summary}
              </p>
            )}
          </div>
        )}

        {/* CTO Card */}
        {cto && (
          <div className="rounded-lg border border-border/70 bg-muted/15 p-3 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="flex items-center gap-1.5 text-xs font-medium">
                  <Cpu className="h-3.5 w-3.5 text-purple-400" aria-hidden="true" />
                  {copy.ctoTitle}
                </span>
                <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                  {cto.recurring_tech_vendors.length}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">{copy.ctoShare}</p>
              <p className="text-xl font-semibold tabular-nums mt-0.5">
                {cto.tech_share_pct.toFixed(1)}%
              </p>
            </div>
            {cto.summary && (
              <p className="mt-3 text-xs text-muted-foreground border-t border-border/40 pt-2 line-clamp-2">
                {cto.summary}
              </p>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
