"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api/client";
import { useI18n } from "@/hooks/useI18n";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import { formatCurrency } from "@/lib/dashboard-utils";

interface Plan {
  id: string;
  name: string;
  price_monthly_try: number;
  price_yearly_try: number;
  yearly_savings_pct: number;
  max_orgs: number | null;
  max_uploads_per_month: number | null;
  max_users: number | null;
  features: string[];
}

interface Subscription {
  plan?: string | null;
  status?: string | null;
  subscription_plan?: string | null;
  subscription_status?: string | null;
}

function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true" className="shrink-0 text-emerald-500">
      <path d="M3 8l3.5 3.5L13 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function BillingPage() {
  const { t } = useI18n();
  const { baseCurrency, locale } = useOrgSettings();
  const [interval, setInterval] = useState<"month" | "year">("month");
  const [plans, setPlans] = useState<Plan[]>([]);
  const [currentPlan, setCurrentPlan] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [portalLoading, setPortalLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [plansRes, subRes] = await Promise.all([
          apiClient.get("/billing/plans"),
          apiClient.get("/billing/subscription").catch(() => null),
        ]);
        if (cancelled) return;
        const planList = plansRes.data?.data?.plans ?? plansRes.data?.plans ?? [];
        setPlans(planList);
        const sub = (subRes?.data?.data ?? subRes?.data) as Subscription | undefined;
        setCurrentPlan(sub?.subscription_plan || sub?.plan || null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load billing");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSelectPlan(planId: string) {
    setLoading(planId);
    setError(null);
    try {
      const origin = typeof window !== "undefined" ? window.location.origin : "";
      const res = await apiClient.post("/billing/checkout", {
        plan: planId,
        interval,
        success_url: `${origin}/billing/success?plan=${planId}`,
        cancel_url: `${origin}/billing`,
      });
      const checkoutUrl = res.data?.data?.url ?? res.data?.url;
      if (!checkoutUrl) throw new Error("Stripe checkout URL missing");
      window.location.href = checkoutUrl;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Checkout failed");
      setLoading(null);
    }
  }

  async function openPortal() {
    setPortalLoading(true);
    setError(null);
    try {
      const origin = typeof window !== "undefined" ? window.location.origin : "";
      const res = await apiClient.post("/billing/portal", {});
      const url = res.data?.data?.url ?? res.data?.url;
      if (!url) throw new Error("Customer portal URL missing");
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Portal failed");
      setPortalLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-screen-xl space-y-10 p-4 sm:p-6 lg:p-8">
      <div className="text-center space-y-3">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">{t.billing.title}</h1>
        <p className="text-muted-foreground text-lg max-w-xl mx-auto">{t.billing.subtitle}</p>
        {currentPlan && (
          <button
            type="button"
            onClick={() => void openPortal()}
            disabled={portalLoading}
            className="text-sm text-primary underline-offset-4 hover:underline"
          >
            {portalLoading ? t.billing.redirecting : t.billing.managePortal}
          </button>
        )}
        <div className="inline-flex items-center gap-1 rounded-lg border border-border bg-muted p-1">
          <button
            type="button"
            onClick={() => setInterval("month")}
            className={cn(
              "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              interval === "month" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t.billing.monthly}
          </button>
          <button
            type="button"
            onClick={() => setInterval("year")}
            className={cn(
              "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              interval === "year" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t.billing.yearly}
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive text-center">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        {plans.map((plan) => {
          const price = interval === "month" ? plan.price_monthly_try : plan.price_yearly_try;
          const isCurrent = currentPlan === plan.id;
          const isPopular = plan.id === "pro";
          return (
            <div
              key={plan.id}
              className={cn(
                "relative flex flex-col rounded-2xl border p-6",
                isPopular ? "border-primary shadow-md" : "border-border",
              )}
            >
              {isPopular && (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-primary px-3 py-0.5 text-[10px] font-semibold text-primary-foreground">
                  Popular
                </span>
              )}
              <h2 className="text-xl font-bold">{plan.name}</h2>
              <p className="mt-2 text-3xl font-bold">
                {formatCurrency(price, baseCurrency, locale)}
                <span className="text-sm font-normal text-muted-foreground">
                  /{interval === "month" ? "mo" : "yr"}
                </span>
              </p>
              <ul className="mt-4 flex-1 space-y-2 text-sm text-muted-foreground">
                {plan.features.map((f) => (
                  <li key={f} className="flex gap-2">
                    <CheckIcon />
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
              <button
                type="button"
                disabled={isCurrent || loading === plan.id}
                onClick={() => void handleSelectPlan(plan.id)}
                className={cn(
                  "mt-6 w-full rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors",
                  isCurrent
                    ? "bg-muted text-muted-foreground cursor-default"
                    : isPopular
                      ? "bg-primary text-primary-foreground hover:bg-primary/90"
                      : "border border-border bg-card hover:bg-muted",
                )}
              >
                {isCurrent
                  ? t.billing.currentPlan
                  : loading === plan.id
                    ? t.billing.redirecting
                    : t.billing.selectPlan}
              </button>
            </div>
          );
        })}
      </div>
    </main>
  );
}
