"use client";

import { useState } from "react";
import { Check, ChevronDown, ChevronUp, ChevronsUpDown, Upload, Loader2 } from "lucide-react";
import { useCorrectCategory } from "@/hooks/useCFO";
import { useI18n } from "@/hooks/useI18n";
import { codeLabel } from "@/lib/i18n/codes";
import { cn } from "@/lib/utils";

// ── Constants ─────────────────────────────────────────────────────────────────

export const CATEGORIES = [
  "revenue",
  "cogs",
  "salary",
  "rent",
  "utilities",
  "marketing",
  "technology",
  "tax",
  "loan",
  "other_expense",
  "other_income",
  "tax_payment",
  "transfer",
] as const;

type Category = (typeof CATEGORIES)[number];

export type SortKey = "transaction_date" | "description" | "vendor" | "category" | "amount_cents";
export type SortDir = "asc" | "desc";

const CATEGORY_COLORS: Record<string, string> = {
  revenue:       "bg-emerald-950/50 text-emerald-400 ring-emerald-500/20",
  cogs:          "bg-orange-950/50 text-orange-400 ring-orange-500/20",
  salary:        "bg-blue-950/50 text-blue-400 ring-blue-500/20",
  rent:          "bg-violet-950/50 text-violet-400 ring-violet-500/20",
  utilities:     "bg-cyan-950/50 text-cyan-400 ring-cyan-500/20",
  marketing:     "bg-pink-950/50 text-pink-400 ring-pink-500/20",
  technology:    "bg-indigo-950/50 text-indigo-400 ring-indigo-500/20",
  tax:           "bg-red-950/50 text-red-400 ring-red-500/20",
  loan:          "bg-amber-950/50 text-amber-400 ring-amber-500/20",
  other_expense: "bg-zinc-800 text-zinc-400 ring-zinc-600/20",
  other_income:  "bg-teal-950/50 text-teal-400 ring-teal-500/20",
  tax_payment:   "bg-zinc-800 text-zinc-300 ring-zinc-500/20",
  transfer:      "bg-zinc-800 text-zinc-500 ring-zinc-600/20",
};

// ── Category editor ───────────────────────────────────────────────────────────

export function CategoryEditor({
  txId,
  current,
  jobId,
  onAffected,
}: {
  txId: string;
  current: string;
  jobId: string;
  onAffected: (jobIds: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [applyAlways, setApplyAlways] = useState(false);
  const correct = useCorrectCategory(jobId);
  const { t } = useI18n();

  function select(cat: Category) {
    correct.mutate(
      { transactionId: txId, category: cat, applyAlways },
      {
        onSuccess: (res) => {
          setOpen(false);
          if (res?.affected_job_ids?.length) onAffected(res.affected_job_ids);
        },
      }
    );
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset",
          "transition-colors hover:ring-primary/50",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          CATEGORY_COLORS[current] ?? CATEGORY_COLORS.other_expense
        )}
        aria-haspopup="listbox"
        aria-expanded={open}
        data-testid="category-trigger"
        data-category={current}
      >
        {correct.isPending ? (
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
        ) : null}
        {codeLabel(t, "category", current)}
        <ChevronDown className="h-3 w-3 opacity-60" aria-hidden="true" />
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-10"
            aria-hidden="true"
            onClick={() => setOpen(false)}
          />
          <div
            role="listbox"
            data-testid="category-listbox"
            aria-label={t.categoryEditor.listLabel}
            className={cn(
              "absolute left-0 top-full z-20 mt-1 w-48 rounded-lg border border-border bg-card",
              "shadow-lg py-1"
            )}
          >
            <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted">
              <input
                type="checkbox"
                checked={applyAlways}
                onChange={(e) => setApplyAlways(e.target.checked)}
                className="h-3 w-3 rounded border-border"
              />
              {t.transactionsPage.applyToVendor}
            </label>
            <div className="my-1 border-t border-border/50" />
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                role="option"
                data-testid={`category-option-${cat}`}
                aria-selected={cat === current}
                onClick={() => select(cat)}
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors hover:bg-muted",
                  cat === current ? "text-primary" : "text-foreground"
                )}
              >
                {cat === current ? (
                  <Check className="h-3 w-3 shrink-0" aria-hidden="true" />
                ) : (
                  <span className="w-3" />
                )}
                {codeLabel(t, "category", cat)}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ── Sort header cell ──────────────────────────────────────────────────────────

export function SortTh({
  label,
  sortKey,
  current,
  dir,
  align = "left",
  onSort,
}: {
  label: string;
  sortKey: SortKey;
  current: SortKey;
  dir: SortDir;
  align?: "left" | "right";
  onSort: (key: SortKey) => void;
}) {
  const { t } = useI18n();
  const active = current === sortKey;
  const Icon = active ? (dir === "asc" ? ChevronUp : ChevronDown) : ChevronsUpDown;

  return (
    <th
      className={cn(
        "px-4 py-2.5 text-xs font-medium text-muted-foreground",
        align === "right" ? "text-right" : "text-left"
      )}
    >
      <button
        onClick={() => onSort(sortKey)}
        className={cn(
          "inline-flex items-center gap-1 rounded transition-colors hover:text-foreground",
          active && "text-foreground",
          align === "right" && "flex-row-reverse"
        )}
        aria-label={t.transactionsPage.sortBy.replace("{label}", label)}
      >
        {label}
        <Icon className="h-3 w-3 shrink-0 opacity-60" aria-hidden="true" />
      </button>
    </th>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

export function EmptyState() {
  const { t } = useI18n();
  const tp = t.transactionsPage;
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center px-6">
      <div className="mb-4 rounded-full bg-muted p-4">
        <Upload className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold">{tp.emptyTitle}</h2>
      <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
        {tp.emptyBody}
      </p>
      <a
        href="/upload"
        className={cn(
          "mt-5 inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground",
          "transition-opacity hover:opacity-90",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        )}
      >
        {tp.emptyCta}
      </a>
    </div>
  );
}

// ── CSV export helper ─────────────────────────────────────────────────────────

export function exportCsv(rows: ReturnType<typeof buildRows>, filename: string) {
  // The export carries the same provenance the table shows. A file taken to
  // an accountant that drops "this date was invented" is a different record.
  const header = [
    "Date", "Date estimated", "Description", "Vendor", "Category", "Type",
    "Amount", "KDV (stated)", "Stopaj (stated)", "Currency",
  ];
  const money = (c: number | null | undefined) => (c == null ? "" : (c / 100).toFixed(2));
  const lines = rows.map((tx) =>
    [
      tx.transaction_date?.slice(0, 10) ?? "",
      tx.date_is_estimated ? "yes" : "no",
      `"${(tx.description ?? "").replace(/"/g, '""')}"`,
      `"${(tx.vendor ?? "").replace(/"/g, '""')}"`,
      tx.category,
      tx.type,
      (tx.amount_cents / 100).toFixed(2),
      money(tx.kdv_cents),
      money(tx.stopaj_cents),
      tx.currency ?? "",
    ].join(",")
  );
  const blob = new Blob([header.join(",") + "\n" + lines.join("\n")], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// Typed helper so exportCsv knows the shape
export function buildRows<T>(arr: T[]) {
  return arr as (T & {
    id: string;
    transaction_date: string | null;
    description: string | null;
    vendor: string | null;
    category: string;
    type: string;
    amount_cents: number;
    date_is_estimated?: boolean;
    currency?: string | null;
    currency_assumed?: boolean;
    kdv_cents?: number | null;
    stopaj_cents?: number | null;
    raw_text?: string | null;
  })[];
}

