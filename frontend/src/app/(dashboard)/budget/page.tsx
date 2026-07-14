"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard, useRerunBudget } from "@/hooks/useCFO";
import { formatCurrency, cn } from "@/lib/utils";
import type { BudgetStatus } from "@/types";

const STATUS_STYLES: Record<BudgetStatus, string> = {
  over_budget: "text-destructive",
  under_budget: "text-warning",
  on_track: "text-success",
  under_spend: "text-primary",
  ahead_of_target: "text-success",
};

const STATUS_LABELS: Record<BudgetStatus, string> = {
  over_budget: "Bütçe Aşımı",
  under_budget: "Hedef Altı",
  on_track: "Hedefte",
  under_spend: "Az Harcama",
  ahead_of_target: "Hedef Üstü",
};

function VarianceBar({ pct }: { pct: number }) {
  const abs = Math.min(Math.abs(pct), 100);
  const isOver = pct > 0;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 rounded-full bg-muted overflow-hidden">
        <div
          className={cn("h-full rounded-full", isOver ? "bg-destructive" : "bg-primary")}
          style={{ width: `${abs}%` }}
        />
      </div>
      <span
        className={cn(
          "text-xs tabular font-medium",
          isOver ? "text-destructive" : pct < 0 ? "text-primary" : "text-success"
        )}
      >
        {pct > 0 ? "+" : ""}{pct.toFixed(1)}%
      </span>
    </div>
  );
}

// Categories with friendly Turkish labels
const CAT_LABELS: Record<string, string> = {
  revenue: "Gelir",
  cogs: "Satılan Mal Maliyeti",
  salary: "Maaş & Bordro",
  rent: "Kira",
  utilities: "Faturalar",
  marketing: "Pazarlama",
  technology: "Teknoloji",
  tax: "Vergi",
  loan: "Kredi Ödemeleri",
  other_expense: "Diğer Gider",
  other_income: "Diğer Gelir",
};

export default function BudgetPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const { data: dashboard, isLoading } = useDashboard(jobId);
  const rerunBudget = useRerunBudget();
  const [showForm, setShowForm] = useState(false);
  const [budgetInputs, setBudgetInputs] = useState<Record<string, string>>({});

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
          <div key={i} className="h-14 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    );
  }

  const budget = dashboard.budget_comparison;
  if (!budget) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center px-6">
        <p className="text-sm text-muted-foreground">Bütçe karşılaştırması mevcut değil.</p>
      </div>
    );
  }

  const categories = Object.entries(budget.categories);
  const overBudget = categories.filter(([, d]) => d.status === "over_budget");

  const handleRerun = async () => {
    if (!jobId) return;
    // Convert ₺ input to cents
    const budgetCents: Record<string, number> = {};
    for (const [cat, val] of Object.entries(budgetInputs)) {
      const parsed = parseFloat(val.replace(/[^0-9.]/g, ""));
      if (!isNaN(parsed)) {
        budgetCents[cat] = Math.round(parsed * 100);
      }
    }
    if (Object.keys(budgetCents).length === 0) return;
    await rerunBudget.mutateAsync({ jobId, budget: budgetCents });
    setShowForm(false);
  };

  return (
    <div className="space-y-5 p-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">Bütçe vs Gerçekleşme</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {budget.auto_budget
              ? "Otomatik bütçe (gerçekleşmelerden oluşturuldu)"
              : "Manuel bütçe tabanı"}
          </p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className={cn(
            "rounded-md border border-border px-3 py-1.5 text-xs font-medium",
            "transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          )}
        >
          {showForm ? "İptal" : "Bütçe Güncelle"}
        </button>
      </div>

      {/* Alerts */}
      {budget.alerts?.map((a, i) => (
        <div
          key={i}
          role="alert"
          className={cn(
            "flex items-start gap-2.5 rounded-md border px-3.5 py-2.5 text-sm",
            a.level === "critical"
              ? "border-destructive/30 bg-destructive/8 text-destructive"
              : a.level === "warning"
              ? "border-warning/25 bg-warning/6 text-warning"
              : "border-border bg-muted/30 text-muted-foreground"
          )}
        >
          {a.message}
        </div>
      ))}

      {/* Summary row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-border bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">Toplam Varyans</p>
          <p className={cn(
            "mt-1 text-lg font-bold tabular",
            budget.total_variance >= 0 ? "text-success" : "text-destructive"
          )}>
            {budget.total_variance >= 0 ? "+" : ""}{formatCurrency(budget.total_variance)}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            %{Math.abs(budget.variance_pct).toFixed(1)} {budget.variance_pct >= 0 ? "iyi" : "kötü"}
          </p>
        </div>
        <div className="rounded-lg border border-destructive/20 bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">Bütçe Aşan Kategoriler</p>
          <p className="mt-1 text-lg font-bold tabular text-destructive">{budget.over_budget_count}</p>
        </div>
        <div className="rounded-lg border border-border bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">Hedefte Kategoriler</p>
          <p className="mt-1 text-lg font-bold tabular text-success">
            {categories.filter(([, d]) => d.status === "on_track" || d.status === "ahead_of_target").length}
          </p>
        </div>
      </div>

      {/* Budget update form */}
      {showForm && (
        <div className="rounded-lg border border-border bg-card p-4 space-y-3">
          <p className="text-sm font-medium">Manuel Bütçe Tabanı Girin (₺)</p>
          <p className="text-xs text-muted-foreground">
            Değer girilen kategoriler için yeniden hesaplama yapılır.
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {categories.map(([cat]) => (
              <div key={cat}>
                <label className="text-xs text-muted-foreground block mb-1">
                  {CAT_LABELS[cat] ?? cat}
                </label>
                <input
                  type="number"
                  min="0"
                  step="100"
                  placeholder={formatCurrency(
                    (budget.categories[cat]?.budget ?? 0)
                  )}
                  value={budgetInputs[cat] ?? ""}
                  onChange={(e) =>
                    setBudgetInputs((prev) => ({ ...prev, [cat]: e.target.value }))
                  }
                  className={cn(
                    "w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs",
                    "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  )}
                />
              </div>
            ))}
          </div>
          <button
            onClick={handleRerun}
            disabled={rerunBudget.isPending}
            className={cn(
              "rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-foreground",
              "transition-colors hover:bg-primary/90 disabled:opacity-50",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            )}
          >
            {rerunBudget.isPending ? "Hesaplanıyor…" : "Yeniden Hesapla"}
          </button>
        </div>
      )}

      {/* Categories table */}
      <div className="rounded-lg border border-border bg-card">
        <div className="border-b border-border px-4 py-3">
          <h3 className="text-sm font-medium">Kategori Karşılaştırması</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" role="table">
            <thead>
              <tr className="border-b border-border">
                <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Kategori</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">Bütçe</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">Gerçekleşen</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Sapma</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Durum</th>
              </tr>
            </thead>
            <tbody>
              {categories
                .filter(([, d]) => d.budget > 0 || d.actual > 0)
                .sort(([, a], [, b]) => Math.abs(b.variance_pct) - Math.abs(a.variance_pct))
                .map(([cat, d]) => (
                  <tr
                    key={cat}
                    className={cn(
                      "border-b border-border/40 last:border-0 hover:bg-muted/20",
                      d.status === "over_budget" ? "bg-destructive/3" : ""
                    )}
                  >
                    <td className="px-4 py-2.5 text-sm font-medium">
                      {CAT_LABELS[cat] ?? cat}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular text-sm text-muted-foreground">
                      {formatCurrency(d.budget)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular text-sm">
                      {formatCurrency(d.actual)}
                    </td>
                    <td className="px-4 py-2.5">
                      <VarianceBar pct={d.variance_pct} />
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={cn(
                        "rounded px-1.5 py-0.5 text-xs font-medium",
                        STATUS_STYLES[d.status as BudgetStatus] ?? "text-muted-foreground"
                      )}>
                        {STATUS_LABELS[d.status as BudgetStatus] ?? d.status}
                      </span>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Narrative */}
      {budget.narrative && (
        <div className="rounded-lg border border-border bg-card px-4 py-3.5">
          <p className="mb-1 text-xs font-medium text-primary">CFO Bütçe Değerlendirmesi</p>
          <p className="text-sm leading-relaxed text-muted-foreground max-w-prose">
            {budget.narrative}
          </p>
        </div>
      )}
    </div>
  );
}
