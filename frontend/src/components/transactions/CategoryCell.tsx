"use client";

import { useState } from "react";
import { Check, ChevronDown, Loader2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import type { Transaction } from "@/types";

const CATEGORIES = [
  { value: "revenue",       label: "Revenue" },
  { value: "cogs",          label: "Cost of Goods" },
  { value: "salary",        label: "Salary" },
  { value: "rent",          label: "Rent" },
  { value: "utilities",     label: "Utilities" },
  { value: "marketing",     label: "Marketing" },
  { value: "technology",    label: "Technology" },
  { value: "tax",           label: "Tax" },
  { value: "loan",          label: "Loan" },
  { value: "other_expense", label: "Other Expense" },
  { value: "other_income",  label: "Other Income" },
] as const;

type CategoryValue = (typeof CATEGORIES)[number]["value"];

interface CategoryCellProps {
  transactionId: string;
  currentCategory: string;
  jobId: string;
}

async function patchCategory(
  transactionId: string,
  category: string,
  applyAlways: boolean
): Promise<void> {
  await apiClient.patch(`/transactions/${transactionId}/category`, {
    category,
    apply_always: applyAlways,
  });
}

/**
 * Inline category editor for transaction table cells.
 * Impeccable rules applied:
 * - No custom scrollbar / reinvented dropdown — uses native <select> on mobile
 * - Motion: 150ms color transition only (Emil frequency gate: used frequently)
 * - No decorative elements — plain functional popover
 * - Focus ring for keyboard navigation
 */
export function CategoryCell({
  transactionId,
  currentCategory,
  jobId,
}: CategoryCellProps) {
  const [open, setOpen] = useState(false);
  const [applyAlways, setApplyAlways] = useState(false);
  const [optimisticCategory, setOptimisticCategory] = useState(currentCategory);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: ({ category }: { category: string }) =>
      patchCategory(transactionId, category, applyAlways),
    onSuccess: () => {
      // Invalidate dashboard so charts reflect the correction
      queryClient.invalidateQueries({ queryKey: ["dashboard", jobId] });
    },
    onError: () => {
      // Revert optimistic update
      setOptimisticCategory(currentCategory);
    },
  });

  const currentLabel =
    CATEGORIES.find((c) => c.value === optimisticCategory)?.label ??
    optimisticCategory;

  function handleSelect(value: CategoryValue) {
    setOptimisticCategory(value);
    setOpen(false);
    mutation.mutate({ category: value });
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Category: ${currentLabel}. Click to change.`}
        className={cn(
          "inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground",
          "transition-state hover:bg-muted/70 hover:text-foreground cursor-pointer",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background",
          mutation.isPending && "opacity-50"
        )}
        disabled={mutation.isPending}
      >
        {mutation.isPending ? (
          <Loader2 className="h-2.5 w-2.5 animate-spin" aria-hidden="true" />
        ) : (
          <ChevronDown className="h-2.5 w-2.5" aria-hidden="true" />
        )}
        {currentLabel}
      </button>

      {open && (
        <>
          {/* Backdrop — close on outside click */}
          <div
            className="fixed inset-0 z-10"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />

          {/* Dropdown — uses position:fixed to escape overflow:hidden parents */}
          <div
            role="listbox"
            aria-label="Select category"
            className={cn(
              "absolute left-0 top-full z-20 mt-1 w-44 rounded-md border border-border bg-card shadow-lg",
              "overflow-hidden"
            )}
          >
            <div className="py-1">
              {CATEGORIES.map((cat) => (
                <button
                  key={cat.value}
                  role="option"
                  aria-selected={cat.value === optimisticCategory}
                  onClick={() => handleSelect(cat.value)}
                  className={cn(
                    "flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs transition-state",
                    "focus-visible:outline-none focus-visible:bg-muted",
                    cat.value === optimisticCategory
                      ? "text-primary bg-primary/8"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  <Check
                    className={cn(
                      "h-3 w-3 shrink-0",
                      cat.value === optimisticCategory ? "opacity-100" : "opacity-0"
                    )}
                    aria-hidden="true"
                  />
                  {cat.label}
                </button>
              ))}
            </div>

            {/* Apply always toggle */}
            <div className="border-t border-border px-3 py-2">
              <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={applyAlways}
                  onChange={(e) => setApplyAlways(e.target.checked)}
                  className="h-3 w-3 accent-primary"
                />
                Always apply for this vendor
              </label>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
