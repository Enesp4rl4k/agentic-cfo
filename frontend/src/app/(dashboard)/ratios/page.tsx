"use client";

import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/hooks/useCFO";
import { cn } from "@/lib/utils";
import type { FinancialRatiosData, RatioValue } from "@/types";

const STATUS_COLOR: Record<string, string> = {
  good: "text-success",
  warning: "text-warning",
  critical: "text-destructive",
  "n/a": "text-muted-foreground",
};

const STATUS_BG: Record<string, string> = {
  good: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  critical: "bg-destructive/10 text-destructive",
  "n/a": "bg-muted text-muted-foreground",
};

function formatRatioValue(ratio: RatioValue): string {
  const val = ratio.value;
  if (val == null) return "—";
  if (ratio.unit === "%") return `${(val * 100).toFixed(1)}%`;
  if (ratio.unit === "days") return `${val.toFixed(0)} days`;
  return `${val.toFixed(2)}x`;
}

function formatBenchmark(ratio: RatioValue): string {
  const bm = ratio.benchmark;
  if (bm == null) return "—";
  if (ratio.unit === "%") return `${(bm * 100).toFixed(0)}%`;
  if (ratio.unit === "days") return `${bm} days`;
  return `${bm}x`;
}

function RatioRow({ label, ratio }: { label: string; ratio: RatioValue }) {
  const status = ratio.status;
  return (
    <tr className="border-b border-border/30 last:border-0 hover:bg-muted/10">
      <td className="px-4 py-2.5 text-sm text-muted-foreground">{label}</td>
      <td className={cn("px-4 py-2.5 text-right tabular text-sm font-medium", STATUS_COLOR[status] ?? "")}>
        {formatRatioValue(ratio)}
      </td>
      <td className="px-4 py-2.5 text-right tabular text-xs text-muted-foreground">
        {formatBenchmark(ratio)}
      </td>
      <td className="px-4 py-2.5 text-right">
        <span className={cn("rounded px-1.5 py-0.5 text-xs font-medium", STATUS_BG[status] ?? "bg-muted text-muted-foreground")}>
          {status.toUpperCase()}
        </span>
      </td>
    </tr>
  );
}

function RatioSection({
  title,
  ratios,
  labelMap,
}: {
  title: string;
  ratios: Record<string, RatioValue>;
  labelMap: Record<string, string>;
}) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-medium">{title}</h3>
      </div>
      <table className="w-full" role="table">
        <thead>
          <tr className="border-b border-border">
            <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">Ratio</th>
            <th className="px-4 py-2 text-right text-xs font-medium text-muted-foreground">Value</th>
            <th className="px-4 py-2 text-right text-xs font-medium text-muted-foreground">Benchmark</th>
            <th className="px-4 py-2 text-right text-xs font-medium text-muted-foreground">Status</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(ratios).map(([key, r]) => (
            <RatioRow
              key={key}
              label={labelMap[key] ?? key.replace(/_/g, " ")}
              ratio={r}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

const LABEL_MAPS: Record<string, Record<string, string>> = {
  liquidity: {
    current_ratio: "Current Ratio",
    quick_ratio: "Quick Ratio (Acid Test)",
    cash_ratio: "Cash Ratio",
  },
  profitability: {
    gross_margin: "Gross Margin",
    net_margin: "Net Margin",
    ebitda_margin: "EBITDA Margin",
    roa: "Return on Assets (ROA)",
    roe: "Return on Equity (ROE)",
    roce: "Return on Capital Employed (ROCE)",
  },
  leverage: {
    debt_to_equity: "Debt-to-Equity",
    debt_ratio: "Debt Ratio",
    interest_coverage: "Interest Coverage",
  },
  efficiency: {
    asset_turnover: "Asset Turnover",
    receivables_turnover: "Receivables Turnover",
    inventory_turnover: "Inventory Turnover",
    payables_turnover: "Payables Turnover",
    dso_days: "Days Sales Outstanding (DSO)",
    dio_days: "Days Inventory Outstanding (DIO)",
    dpo_days: "Days Payable Outstanding (DPO)",
    cash_conversion_cycle: "Cash Conversion Cycle (CCC)",
  },
  cash_flow: {
    operating_cf_ratio: "Operating CF / Revenue",
    cash_flow_coverage: "Cash Flow Coverage",
  },
};

export default function RatiosPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const { data: dashboard, isLoading } = useDashboard(jobId);

  if (!jobId) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center px-6">
        <p className="text-sm text-muted-foreground">No job selected. Upload a document first.</p>
      </div>
    );
  }

  if (isLoading || !dashboard) {
    return (
      <div className="space-y-4 p-5">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-32 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    );
  }

  const ratios = dashboard.financial_ratios;
  if (!ratios) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center px-6">
        <p className="text-sm text-muted-foreground">Financial ratios not available for this job.</p>
      </div>
    );
  }

  const { scorecard } = ratios;
  const total = scorecard.good + scorecard.warning + scorecard.critical;

  return (
    <div className="space-y-5 p-5">
      <div>
        <h2 className="text-base font-semibold">Financial Ratios</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Liquidity · Profitability · Leverage · Efficiency · Cash Flow
        </p>
      </div>

      {/* Scorecard */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-lg border border-success/20 bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">Good</p>
          <p className="mt-1 text-2xl font-bold tabular text-success">{scorecard.good}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">of {total}</p>
        </div>
        <div className="rounded-lg border border-warning/20 bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">Warning</p>
          <p className="mt-1 text-2xl font-bold tabular text-warning">{scorecard.warning}</p>
        </div>
        <div className="rounded-lg border border-destructive/20 bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">Critical</p>
          <p className="mt-1 text-2xl font-bold tabular text-destructive">{scorecard.critical}</p>
        </div>
        <div className="rounded-lg border border-border bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">Overall Health</p>
          <p className={cn(
            "mt-1 text-sm font-bold",
            scorecard.critical >= 3 ? "text-destructive" :
            scorecard.critical >= 1 ? "text-warning" : "text-success"
          )}>
            {scorecard.critical >= 3 ? "Critical" : scorecard.critical >= 1 ? "At Risk" : scorecard.warning > 3 ? "Caution" : "Healthy"}
          </p>
        </div>
      </div>

      {scorecard.critical > 0 && (
        <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/8 px-3.5 py-2.5 text-sm text-destructive">
          {scorecard.critical} ratio{scorecard.critical > 1 ? "s" : ""} in critical range — immediate management attention required.
        </div>
      )}

      <RatioSection title="Liquidity Ratios" ratios={ratios.liquidity} labelMap={LABEL_MAPS.liquidity} />
      <RatioSection title="Profitability Ratios" ratios={ratios.profitability} labelMap={LABEL_MAPS.profitability} />
      <RatioSection title="Leverage Ratios" ratios={ratios.leverage} labelMap={LABEL_MAPS.leverage} />
      <RatioSection title="Efficiency Ratios" ratios={ratios.efficiency} labelMap={LABEL_MAPS.efficiency} />
      <RatioSection title="Cash Flow Ratios" ratios={ratios.cash_flow} labelMap={LABEL_MAPS.cash_flow} />

      {ratios.narrative && (
        <div className="rounded-lg border border-border bg-card px-4 py-3.5">
          <p className="mb-1 text-xs font-medium text-primary">
            CFO Ratio Analysis
            {ratios.narrative_lang && (
              <span className="ml-2 text-muted-foreground font-normal">({ratios.narrative_lang.toUpperCase()})</span>
            )}
          </p>
          <p className="text-sm leading-relaxed text-muted-foreground max-w-prose">{ratios.narrative}</p>
        </div>
      )}
    </div>
  );
}
