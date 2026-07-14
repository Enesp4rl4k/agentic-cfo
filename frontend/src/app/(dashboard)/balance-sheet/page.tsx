"use client";

import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/hooks/useCFO";
import { formatCurrency, cn } from "@/lib/utils";
import type { BalanceSheetData } from "@/types";

function BSRow({
  label,
  value,
  indent = 0,
  bold = false,
  positive,
}: {
  label: string;
  value: number;
  indent?: number;
  bold?: boolean;
  positive?: boolean;
}) {
  return (
    <tr className="border-b border-border/30 last:border-0 hover:bg-muted/10">
      <td
        className={cn("py-2 text-sm", bold ? "font-semibold" : "text-muted-foreground")}
        style={{ paddingLeft: `${16 + indent * 16}px` }}
      >
        {label}
      </td>
      <td
        className={cn(
          "py-2 pr-4 text-right tabular text-sm",
          bold ? "font-semibold" : "",
          positive === true ? "text-success" : positive === false ? "text-destructive" : ""
        )}
      >
        {formatCurrency(value / 100)}
      </td>
    </tr>
  );
}

function BSSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <tr>
        <td
          colSpan={2}
          className="pt-4 pb-1 px-4 text-xs font-semibold uppercase tracking-wide text-primary"
        >
          {title}
        </td>
      </tr>
      {children}
    </>
  );
}

function BalanceSheetTable({ bs }: { bs: BalanceSheetData }) {
  const { assets, liabilities, equity } = bs;

  return (
    <div className="rounded-lg border border-border bg-card overflow-x-auto">
      <table className="w-full" role="table">
        <thead>
          <tr className="border-b border-border">
            <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground">Item</th>
            <th className="px-4 py-3 text-right text-xs font-medium text-muted-foreground">Amount (₺)</th>
          </tr>
        </thead>
        <tbody>
          {/* ASSETS */}
          <BSSection title="ASSETS">
            <BSRow label="Current Assets" value={assets.current.total} bold />
            <BSRow label="Cash & Equivalents" value={assets.current.cash} indent={1} />
            <BSRow label="Accounts Receivable" value={assets.current.accounts_receivable} indent={1} />
            <BSRow label="Inventory" value={assets.current.inventory} indent={1} />
            <BSRow label="Prepaid & Other" value={assets.current.prepaid_other} indent={1} />
            <BSRow label="Non-Current Assets" value={assets.non_current.total} bold />
            <BSRow label="PP&E" value={assets.non_current.ppe} indent={1} />
            <BSRow label="Intangibles" value={assets.non_current.intangibles} indent={1} />
            <BSRow label="TOTAL ASSETS" value={assets.total} bold positive={assets.total > 0} />
          </BSSection>

          {/* LIABILITIES */}
          <BSSection title="LIABILITIES">
            <BSRow label="Current Liabilities" value={liabilities.current.total} bold />
            <BSRow label="Accounts Payable" value={liabilities.current.accounts_payable} indent={1} />
            <BSRow label="Short-term Debt" value={liabilities.current.short_term_debt} indent={1} />
            <BSRow label="Accrued Expenses" value={liabilities.current.accrued_expenses} indent={1} />
            <BSRow label="Non-Current Liabilities" value={liabilities.non_current.total} bold />
            <BSRow label="Long-term Debt" value={liabilities.non_current.long_term_debt} indent={1} />
            <BSRow label="TOTAL LIABILITIES" value={liabilities.total} bold positive={false} />
          </BSSection>

          {/* EQUITY */}
          <BSSection title="EQUITY">
            <BSRow label="Retained Earnings" value={equity.retained_earnings} indent={1} positive={equity.retained_earnings >= 0} />
            <BSRow label="Paid-in Capital" value={equity.paid_in_capital} indent={1} />
            <BSRow label="TOTAL EQUITY" value={equity.total} bold positive={equity.total >= 0} />
          </BSSection>

          {/* TOTAL CHECK */}
          <tr className="border-t-2 border-border">
            <td className="px-4 py-3 text-sm font-bold">TOTAL LIABILITIES + EQUITY</td>
            <td className="px-4 py-3 text-right tabular text-sm font-bold">
              {formatCurrency((liabilities.total + equity.total) / 100)}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export default function BalanceSheetPage() {
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
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-16 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    );
  }

  const bs = dashboard.balance_sheet;
  if (!bs) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center px-6">
        <p className="text-sm text-muted-foreground">Balance sheet not available for this job.</p>
      </div>
    );
  }

  const debtRatio = bs.assets.total > 0
    ? round(bs.liabilities.total / bs.assets.total * 100, 1)
    : 0;

  return (
    <div className="space-y-5 p-5">
      <div>
        <h2 className="text-base font-semibold">Balance Sheet</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Pro-forma estimate derived from transaction data ·{" "}
          <span className={cn("font-medium", bs.is_balanced ? "text-success" : "text-warning")}>
            {bs.is_balanced ? "Balanced ✓" : "Not balanced — manual review recommended"}
          </span>
        </p>
      </div>

      {/* Summary KPIs */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-lg border border-border bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">Total Assets</p>
          <p className="mt-1 text-lg font-semibold tabular">{formatCurrency(bs.assets.total / 100)}</p>
        </div>
        <div className="rounded-lg border border-border bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">Total Liabilities</p>
          <p className="mt-1 text-lg font-semibold tabular text-destructive">{formatCurrency(bs.liabilities.total / 100)}</p>
        </div>
        <div className="rounded-lg border border-border bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">Total Equity</p>
          <p className={cn("mt-1 text-lg font-semibold tabular", bs.equity.total >= 0 ? "text-success" : "text-destructive")}>
            {formatCurrency(bs.equity.total / 100)}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">Debt Ratio</p>
          <p className={cn("mt-1 text-lg font-semibold tabular", debtRatio > 60 ? "text-warning" : "text-foreground")}>
            {debtRatio}%
          </p>
        </div>
      </div>

      <BalanceSheetTable bs={bs} />

      {/* Assumptions */}
      <div className="rounded-lg border border-border/50 bg-muted/20 px-4 py-3">
        <p className="text-xs font-medium text-muted-foreground mb-1">Assumptions</p>
        <p className="text-xs text-muted-foreground leading-relaxed">{bs.assumptions.note}</p>
        <div className="mt-2 flex gap-4 text-xs text-muted-foreground">
          <span>DSO: {bs.assumptions.dso_days} days</span>
          <span>DIO: {bs.assumptions.dio_days} days</span>
          <span>DPO: {bs.assumptions.dpo_days} days</span>
        </div>
      </div>

      {/* Narrative */}
      {bs.narrative && (
        <div className="rounded-lg border border-border bg-card px-4 py-3.5">
          <p className="mb-1 text-xs font-medium text-primary">CFO Balance Sheet Analysis</p>
          <p className="text-sm leading-relaxed text-muted-foreground max-w-prose">{bs.narrative}</p>
        </div>
      )}
    </div>
  );
}

function round(n: number, decimals: number) {
  return Math.round(n * 10 ** decimals) / 10 ** decimals;
}
