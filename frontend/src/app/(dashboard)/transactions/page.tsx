"use client";

import { useState, useMemo, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import {
  Check,
  ChevronDown,
  ChevronUp,
  ChevronsUpDown,
  Upload,
  Loader2,
  Search,
  X,
  Download,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useTransactions, useCorrectCategory } from "@/hooks/useCFO";
import { formatCurrency, cn } from "@/lib/utils";

// ── Constants ─────────────────────────────────────────────────────────────────

const PAGE_SIZE = 50;

const CATEGORIES = [
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
] as const;

type Category = (typeof CATEGORIES)[number];

type SortKey = "transaction_date" | "description" | "vendor" | "category" | "amount_cents";
type SortDir = "asc" | "desc";

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
};

// ── Category editor ───────────────────────────────────────────────────────────

function CategoryEditor({
  txId,
  current,
  jobId,
}: {
  txId: string;
  current: string;
  jobId: string;
}) {
  const [open, setOpen] = useState(false);
  const [applyAlways, setApplyAlways] = useState(false);
  const correct = useCorrectCategory(jobId);

  function select(cat: Category) {
    correct.mutate(
      { transactionId: txId, category: cat, applyAlways },
      { onSuccess: () => setOpen(false) }
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
      >
        {correct.isPending ? (
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
        ) : null}
        {current.replace(/_/g, " ")}
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
            aria-label="Select category"
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
              Apply to all from vendor
            </label>
            <div className="my-1 border-t border-border/50" />
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                role="option"
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
                {cat.replace(/_/g, " ")}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ── Sort header cell ──────────────────────────────────────────────────────────

function SortTh({
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
        aria-label={`Sort by ${label}`}
      >
        {label}
        <Icon className="h-3 w-3 shrink-0 opacity-60" aria-hidden="true" />
      </button>
    </th>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center px-6">
      <div className="mb-4 rounded-full bg-muted p-4">
        <Upload className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold">No transactions yet</h2>
      <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
        Upload a financial document and run an analysis to see and edit transactions.
      </p>
      <a
        href="/upload"
        className={cn(
          "mt-5 inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground",
          "transition-opacity hover:opacity-90",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        )}
      >
        Upload document
      </a>
    </div>
  );
}

// ── CSV export helper ─────────────────────────────────────────────────────────

function exportCsv(rows: ReturnType<typeof buildRows>, filename: string) {
  const header = ["Date", "Description", "Vendor", "Category", "Type", "Amount"];
  const lines = rows.map((tx) =>
    [
      tx.transaction_date?.slice(0, 10) ?? "",
      `"${(tx.description ?? "").replace(/"/g, '""')}"`,
      `"${(tx.vendor ?? "").replace(/"/g, '""')}"`,
      tx.category,
      tx.type,
      (tx.amount_cents / 100).toFixed(2),
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
function buildRows<T>(arr: T[]) {
  return arr as (T & {
    id: string;
    transaction_date: string | null;
    description: string | null;
    vendor: string | null;
    category: string;
    type: string;
    amount_cents: number;
  })[];
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function TransactionsPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");

  // Filters
  const [search, setSearch] = useState("");
  const [filterCat, setFilterCat] = useState<string>("all");
  const [filterType, setFilterType] = useState<string>("all");

  // Sorting
  const [sortKey, setSortKey] = useState<SortKey>("transaction_date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // Pagination
  const [page, setPage] = useState(1);

  // Fetch all transactions (up to 2000 — backend paginates beyond this)
  const { data, isLoading } = useTransactions(jobId, 2000, 0);

  const handleSort = useCallback((key: SortKey) => {
    setSortKey((prev) => {
      if (prev === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      else setSortDir("asc");
      return key;
    });
    setPage(1);
  }, []);

  if (!jobId || (!isLoading && !data)) return <EmptyState />;

  if (isLoading) {
    return (
      <div className="space-y-3 p-5">
        <div className="h-6 w-40 animate-pulse rounded bg-muted" />
        {[...Array(8)].map((_, i) => (
          <div key={i} className="h-10 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    );
  }

  const allTransactions = buildRows(data!.transactions);

  // Filter
  const filtered = allTransactions.filter((t) => {
    if (filterCat !== "all" && t.category !== filterCat) return false;
    if (filterType !== "all" && t.type !== filterType) return false;
    if (search) {
      const q = search.toLowerCase();
      if (
        !t.description?.toLowerCase().includes(q) &&
        !t.vendor?.toLowerCase().includes(q)
      )
        return false;
    }
    return true;
  });

  // Sort
  const sorted = [...filtered].sort((a, b) => {
    let cmp = 0;
    switch (sortKey) {
      case "transaction_date":
        cmp = (a.transaction_date ?? "").localeCompare(b.transaction_date ?? "");
        break;
      case "description":
        cmp = (a.description ?? "").localeCompare(b.description ?? "");
        break;
      case "vendor":
        cmp = (a.vendor ?? "").localeCompare(b.vendor ?? "");
        break;
      case "category":
        cmp = a.category.localeCompare(b.category);
        break;
      case "amount_cents":
        cmp = a.amount_cents - b.amount_cents;
        break;
    }
    return sortDir === "asc" ? cmp : -cmp;
  });

  // Pagination
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageRows = sorted.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  // Summary stats (always from full set)
  const income = allTransactions.filter((t) => t.type === "income");
  const expenses = allTransactions.filter((t) => t.type === "expense");
  const totalIn = income.reduce((s, t) => s + t.amount_cents / 100, 0);
  const totalOut = expenses.reduce((s, t) => s + t.amount_cents / 100, 0);

  const hasFilter = search || filterCat !== "all" || filterType !== "all";

  return (
    <div className="space-y-4 p-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Transactions</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {hasFilter
              ? `${filtered.length} of ${allTransactions.length}`
              : allTransactions.length}{" "}
            transactions
            {!hasFilter && " · click a category badge to correct it"}
          </p>
        </div>

        {/* Summary strip */}
        <div className="flex items-center gap-4 sm:gap-6">
          <div className="hidden text-right sm:block">
            <p className="text-xs text-muted-foreground">Total In</p>
            <p className="text-sm font-semibold tabular-nums text-emerald-400">
              {formatCurrency(totalIn)}
            </p>
          </div>
          <div className="hidden text-right sm:block">
            <p className="text-xs text-muted-foreground">Total Out</p>
            <p className="text-sm font-semibold tabular-nums text-destructive">
              {formatCurrency(totalOut)}
            </p>
          </div>
          <div className="hidden text-right sm:block">
            <p className="text-xs text-muted-foreground">Net</p>
            <p
              className={cn(
                "text-sm font-semibold tabular-nums",
                totalIn - totalOut >= 0 ? "text-emerald-400" : "text-destructive"
              )}
            >
              {formatCurrency(totalIn - totalOut)}
            </p>
          </div>

          {/* CSV export */}
          <button
            onClick={() =>
              exportCsv(
                sorted,
                `transactions-${jobId?.slice(0, 8) ?? "export"}.csv`
              )
            }
            className={cn(
              "flex h-8 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-xs font-medium",
              "text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            )}
            aria-label="Export transactions as CSV"
          >
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            Export CSV
          </button>
        </div>
      </div>

      {/* Filter toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[180px] flex-1">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="search"
            placeholder="Search description or vendor…"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            className={cn(
              "h-8 w-full rounded-md border border-border bg-card pl-8 pr-3 text-sm",
              "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            )}
            aria-label="Search transactions"
          />
        </div>

        <select
          value={filterType}
          onChange={(e) => { setFilterType(e.target.value); setPage(1); }}
          className={cn(
            "h-8 rounded-md border border-border bg-card px-2 text-xs text-foreground",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          )}
          aria-label="Filter by type"
        >
          <option value="all">All types</option>
          <option value="income">Income</option>
          <option value="expense">Expense</option>
        </select>

        <select
          value={filterCat}
          onChange={(e) => { setFilterCat(e.target.value); setPage(1); }}
          className={cn(
            "h-8 rounded-md border border-border bg-card px-2 text-xs text-foreground",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          )}
          aria-label="Filter by category"
        >
          <option value="all">All categories</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c.replace(/_/g, " ")}
            </option>
          ))}
        </select>

        {hasFilter && (
          <button
            onClick={() => {
              setSearch("");
              setFilterCat("all");
              setFilterType("all");
              setPage(1);
            }}
            className="flex h-8 items-center gap-1 rounded-md border border-border px-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
            aria-label="Clear filters"
          >
            <X className="h-3 w-3" aria-hidden="true" />
            Clear
          </button>
        )}
      </div>

      {/* Table */}
      <div className="rounded-lg border border-border bg-card">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" role="table" aria-label="Transaction list">
            <thead>
              <tr className="border-b border-border">
                <SortTh
                  label="Date"
                  sortKey="transaction_date"
                  current={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                />
                <SortTh
                  label="Description"
                  sortKey="description"
                  current={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                />
                <SortTh
                  label="Vendor"
                  sortKey="vendor"
                  current={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                />
                <SortTh
                  label="Category"
                  sortKey="category"
                  current={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                />
                <SortTh
                  label="Amount"
                  sortKey="amount_cents"
                  current={sortKey}
                  dir={sortDir}
                  align="right"
                  onSort={handleSort}
                />
              </tr>
            </thead>
            <tbody>
              {pageRows.map((tx) => (
                <tr
                  key={tx.id}
                  className="border-b border-border/40 last:border-0 transition-colors hover:bg-muted/20"
                >
                  <td className="whitespace-nowrap px-4 py-2.5 text-xs tabular-nums text-muted-foreground">
                    {tx.transaction_date?.slice(0, 10) ?? "—"}
                  </td>
                  <td className="max-w-[180px] truncate px-4 py-2.5 text-sm">
                    {tx.description || "—"}
                  </td>
                  <td className="max-w-[120px] truncate px-4 py-2.5 text-xs text-muted-foreground">
                    {tx.vendor ?? "—"}
                  </td>
                  <td className="px-4 py-2.5">
                    <CategoryEditor
                      txId={tx.id}
                      current={tx.category}
                      jobId={jobId!}
                    />
                  </td>
                  <td
                    className={cn(
                      "px-4 py-2.5 text-right tabular-nums text-sm font-medium",
                      tx.type === "income" ? "text-emerald-400" : "text-foreground"
                    )}
                  >
                    {tx.type === "income" ? "+" : "−"}
                    {formatCurrency(tx.amount_cents / 100)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {!sorted.length && (
            <div className="py-10 text-center text-sm text-muted-foreground">
              No transactions match the current filters.
            </div>
          )}
        </div>

        {/* Pagination footer */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between border-t border-border px-4 py-2.5">
            <p className="text-xs text-muted-foreground">
              Showing {(safePage - 1) * PAGE_SIZE + 1}–
              {Math.min(safePage * PAGE_SIZE, sorted.length)} of {sorted.length}
            </p>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={safePage === 1}
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded border border-border text-muted-foreground transition-colors",
                  "hover:border-primary/40 hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
                )}
                aria-label="Previous page"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>

              {/* Page number pills */}
              {Array.from({ length: totalPages }, (_, i) => i + 1)
                .filter(
                  (p) =>
                    p === 1 ||
                    p === totalPages ||
                    Math.abs(p - safePage) <= 1
                )
                .reduce<(number | "…")[]>((acc, p, idx, arr) => {
                  if (idx > 0 && (p as number) - (arr[idx - 1] as number) > 1)
                    acc.push("…");
                  acc.push(p);
                  return acc;
                }, [])
                .map((p, i) =>
                  p === "…" ? (
                    <span
                      key={`ellipsis-${i}`}
                      className="px-1 text-xs text-muted-foreground"
                    >
                      …
                    </span>
                  ) : (
                    <button
                      key={p}
                      onClick={() => setPage(p as number)}
                      className={cn(
                        "flex h-7 min-w-[1.75rem] items-center justify-center rounded border px-1.5 text-xs transition-colors",
                        p === safePage
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground"
                      )}
                      aria-label={`Page ${p}`}
                      aria-current={p === safePage ? "page" : undefined}
                    >
                      {p}
                    </button>
                  )
                )}

              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={safePage === totalPages}
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded border border-border text-muted-foreground transition-colors",
                  "hover:border-primary/40 hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
                )}
                aria-label="Next page"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
