"use client";

import { useSearchParams } from "next/navigation";
import { Upload, AlertCircle, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { useDashboard } from "@/hooks/useCFO";
import { useI18n } from "@/hooks/useI18n";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { cn } from "@/lib/utils";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from "recharts";

// ── Types ─────────────────────────────────────────────────────────────────────

interface BudgetItem {
  category: string;
  budgeted: number;
  actual: number;
  variance: number;
  variance_pct: number;
  status: "over" | "under" | "on_target";
}

interface BudgetData {
  items: BudgetItem[];
  total_budgeted: number;
  total_actual: number;
  total_variance: number;
  total_variance_pct: number;
  over_budget_categories: string[];
  period: string;
  narrative: string;
}

// ── Chart styles ──────────────────────────────────────────────────────────────

const tooltipStyle = {
  contentStyle: {
    background: "oklch(0.21 0.018 70)",
    border: "1px solid oklch(0.32 0.019 68)",
    borderRadius: "6px",
    fontSize: "12px",
    color: "oklch(0.94 0.012 85)",
    padding: "8px 12px",
  },
};

const axisStyle = {
  tick: { fontSize: 11, fill: "oklch(0.72 0.017 78)" },
  axisLine: { stroke: "oklch(0.32 0.019 68)" },
  tickLine: false as const,
};

// ── Summary KPI strip ─────────────────────────────────────────────────────────

function BudgetSummary({ budget }: { budget: BudgetData }) {
  const fmt = useCurrencyFormat();
  const { t } = useI18n();
  const { summary, thisPeriod } = t.budget;
  const overBudget = budget.total_variance > 0;

  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
      <div className="bg-card px-4 py-4">
        <p className="text-xs text-muted-foreground">{summary.budgeted}</p>
        <p className="mt-1 text-lg font-semibold tabular-nums">
          {fmt(budget.total_budgeted / 100)}
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">{budget.period || thisPeriod}</p>
      </div>
      <div className="bg-card px-4 py-4">
        <p className="text-xs text-muted-foreground">{summary.actual}</p>
        <p className="mt-1 text-lg font-semibold tabular-nums">
          {fmt(budget.total_actual / 100)}
        </p>
      </div>
      <div className="bg-card px-4 py-4">
        <p className="text-xs text-muted-foreground">{summary.variance}</p>
        <p className={cn(
          "mt-1 text-lg font-semibold tabular-nums",
          overBudget ? "text-destructive" : "text-emerald-400"
        )}>
          {overBudget ? "+" : ""}{fmt(budget.total_variance / 100)}
        </p>
      </div>
      <div className="bg-card px-4 py-4">
        <p className="text-xs text-muted-foreground">{summary.variancePct}</p>
        <p className={cn(
          "mt-1 text-lg font-semibold tabular-nums",
          overBudget ? "text-destructive" : "text-emerald-400"
        )}>
          {overBudget ? "+" : ""}{budget.total_variance_pct.toFixed(1)}%
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {summary.categoriesOver.replace("{count}", String(budget.over_budget_categories.length))}
        </p>
      </div>
    </div>
  );
}

// ── Variance bar chart ────────────────────────────────────────────────────────

function VarianceChart({ items }: { items: BudgetItem[] }) {
  const { t } = useI18n();
  const { chart } = t.budget;

  const data = items.slice(0, 10).map((item) => ({
    name: item.category.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    variance_pct: item.variance_pct,
    status: item.status,
  }));

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-0.5 text-sm font-medium">{chart.heading}</h2>
      <p className="mb-4 text-xs text-muted-foreground">
        {chart.hint}
      </p>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.27 0.017 70)" horizontal={false} />
          <XAxis
            type="number"
            {...axisStyle}
            tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v.toFixed(0)}%`}
          />
          <YAxis dataKey="name" type="category" {...axisStyle} width={100} />
          <Tooltip
            {...tooltipStyle}
            formatter={(v: number) => [`${v > 0 ? "+" : ""}${v.toFixed(1)}%`, chart.tooltip]}
          />
          <ReferenceLine x={0} stroke="oklch(0.47 0.025 74)" strokeWidth={1} />
          <Bar dataKey="variance_pct" radius={[0, 3, 3, 0]} maxBarSize={18}>
            {data.map((entry, i) => (
              <Cell
                key={i}
                fill={
                  entry.status === "over"
                    ? "oklch(0.58 0.22 25)"
                    : entry.status === "under"
                    ? "oklch(0.58 0.18 145)"
                    : "oklch(0.72 0.017 78)"
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Budget detail table ───────────────────────────────────────────────────────

function BudgetTable({ items }: { items: BudgetItem[] }) {
  const fmt = useCurrencyFormat();
  const { t } = useI18n();
  const { table } = t.budget;

  function StatusIcon({ status }: { status: BudgetItem["status"] }) {
    if (status === "over") return <TrendingUp className="h-3.5 w-3.5 text-destructive" aria-hidden="true" />;
    if (status === "under") return <TrendingDown className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />;
    return <Minus className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />;
  }

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">{table.heading}</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" role="table">
          <thead>
            <tr className="border-b border-border">
              <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">{table.colCategory}</th>
              <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">{table.colBudget}</th>
              <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">{table.colActual}</th>
              <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">{table.colVariance}</th>
              <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">%</th>
              <th className="px-4 py-2.5 text-center text-xs font-medium text-muted-foreground">{table.colStatus}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, i) => (
              <tr key={i} className="border-b border-border/40 last:border-0 hover:bg-muted/10 transition-colors">
                <td className="px-4 py-2.5 text-sm font-medium">
                  {item.category.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-sm text-muted-foreground">
                  {fmt(item.budgeted / 100)}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-sm">
                  {fmt(item.actual / 100)}
                </td>
                <td className={cn(
                  "px-4 py-2.5 text-right tabular-nums text-sm font-medium",
                  item.status === "over" ? "text-destructive" : item.status === "under" ? "text-emerald-400" : "text-muted-foreground"
                )}>
                  {item.variance > 0 ? "+" : ""}{fmt(item.variance / 100)}
                </td>
                <td className={cn(
                  "px-4 py-2.5 text-right tabular-nums text-sm",
                  item.status === "over" ? "text-destructive" : item.status === "under" ? "text-emerald-400" : "text-muted-foreground"
                )}>
                  {item.variance_pct > 0 ? "+" : ""}{item.variance_pct.toFixed(1)}%
                </td>
                <td className="px-4 py-2.5 text-center">
                  <StatusIcon status={item.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  const { t } = useI18n();
  const { empty } = t.budget;

  return (
    <div className="flex flex-col items-center justify-center py-20 text-center px-6">
      <div className="mb-4 rounded-full bg-muted p-4">
        <Upload className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold">{empty.heading}</h2>
      <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
        {empty.body}
      </p>
      <a href="/upload" className={cn(
        "mt-5 inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground",
        "transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      )}>
        {empty.cta}
      </a>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function BudgetPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const { data: dashboard, isLoading } = useDashboard(jobId);
  const { t } = useI18n();
  const { noBudget, cfoCommentary, thisPeriod } = t.budget;

  if (!jobId || (!isLoading && !dashboard)) return <EmptyState />;

  if (isLoading) {
    return (
      <div className="space-y-4 p-5">
        <div className="h-6 w-40 animate-pulse rounded bg-muted" />
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-card px-4 py-4">
              <div className="h-3 w-16 animate-pulse rounded bg-muted" />
              <div className="mt-2 h-5 w-24 animate-pulse rounded bg-muted" />
            </div>
          ))}
        </div>
        <div className="h-64 animate-pulse rounded-lg bg-muted" />
      </div>
    );
  }

  const budget = (dashboard as { budget?: BudgetData })?.budget;

  if (!budget) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center px-6">
        <div className="mb-4 rounded-full bg-muted p-4">
          <AlertCircle className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
        </div>
        <h2 className="text-base font-semibold">{noBudget.heading}</h2>
        <p className="mt-1.5 max-w-xs text-sm text-muted-foreground">
          {noBudget.body}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-5">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{t.budget.title}</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          {t.budget.subtitle.replace("{period}", budget.period || thisPeriod)}
        </p>
      </div>

      <BudgetSummary budget={budget} />

      {budget.narrative && (
        <div className="rounded-lg border border-border bg-card px-4 py-3.5">
          <p className="mb-1 text-xs font-medium text-primary">{cfoCommentary}</p>
          <p className="text-sm leading-relaxed text-muted-foreground max-w-prose">{budget.narrative}</p>
        </div>
      )}

      <VarianceChart items={budget.items} />
      <BudgetTable items={budget.items} />
    </div>
  );
}
