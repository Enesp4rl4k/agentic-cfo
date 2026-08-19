"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

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

// ── Static plan data (matches backend PLANS) ──────────────────────────────────

const STATIC_PLANS: Plan[] = [
  {
    id: "starter",
    name: "Starter",
    price_monthly_try: 990,
    price_yearly_try: 9_900,
    yearly_savings_pct: 17,
    max_orgs: 1,
    max_uploads_per_month: 5,
    max_users: 2,
    features: [
      "CFO Pipeline (P&L, Nakit Akışı, Tahmin)",
      "Anomali Tespiti",
      "5 yükleme/ay",
      "PDF export",
      "E-posta desteği",
    ],
  },
  {
    id: "pro",
    name: "Pro",
    price_monthly_try: 2_990,
    price_yearly_try: 29_900,
    yearly_savings_pct: 17,
    max_orgs: 3,
    max_uploads_per_month: null,
    max_users: 10,
    features: [
      "Starter'ın tüm özellikleri",
      "C-Suite Kernels (CTO/CMO/CHRO/COO)",
      "CEO Sentezi & Board Deck",
      "Monte Carlo & İleri Analitik",
      "Open Banking Entegrasyonu",
      "Sınırsız yükleme",
      "Öncelikli destek",
    ],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price_monthly_try: 9_990,
    price_yearly_try: 99_900,
    yearly_savings_pct: 17,
    max_orgs: null,
    max_uploads_per_month: null,
    max_users: null,
    features: [
      "Pro'nun tüm özellikleri",
      "SSO (Microsoft Entra / Google Workspace)",
      "SOC2 Audit Trail",
      "KVKK/GDPR Uyumluluk",
      "IP Whitelist",
      "Özel Entegrasyonlar",
      "SLA garantisi",
      "Dedicated Customer Success",
    ],
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number): string {
  return n.toLocaleString("tr-TR");
}

// ── Check icon ────────────────────────────────────────────────────────────────

function CheckIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
      className="shrink-0 text-emerald-500"
    >
      <path
        d="M3 8l3.5 3.5L13 4"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// ── Plan card ─────────────────────────────────────────────────────────────────

function PlanCard({
  plan,
  interval,
  isPopular,
  currentPlan,
  onSelect,
  loading,
}: {
  plan: Plan;
  interval: "month" | "year";
  isPopular: boolean;
  currentPlan: string | null;
  onSelect: (planId: string) => void;
  loading: boolean;
}) {
  const price = interval === "month" ? plan.price_monthly_try : Math.round(plan.price_yearly_try / 12);
  const isCurrentPlan = currentPlan === plan.id;

  return (
    <div
      className={cn(
        "relative flex flex-col rounded-xl border bg-card p-6 shadow-sm transition-shadow hover:shadow-md",
        isPopular
          ? "border-primary ring-2 ring-primary/20"
          : "border-border",
      )}
    >
      {isPopular && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2">
          <span className="rounded-full bg-primary px-3 py-0.5 text-xs font-semibold text-primary-foreground">
            En Popüler
          </span>
        </div>
      )}

      <div className="mb-4">
        <h3 className="text-lg font-semibold">{plan.name}</h3>
        <div className="mt-2 flex items-baseline gap-1">
          <span className="text-3xl font-bold">{fmt(price)}</span>
          <span className="text-muted-foreground text-sm">₺/ay</span>
        </div>
        {interval === "year" && (
          <p className="mt-1 text-xs text-emerald-600 font-medium">
            Yıllık ödemede %{plan.yearly_savings_pct} tasarruf
          </p>
        )}
      </div>

      {/* Limits */}
      <div className="mb-4 space-y-1 text-sm text-muted-foreground border-t border-border pt-4">
        <p>
          <span className="text-foreground font-medium">
            {plan.max_users == null ? "Sınırsız" : plan.max_users}
          </span>{" "}
          kullanıcı
        </p>
        <p>
          <span className="text-foreground font-medium">
            {plan.max_uploads_per_month == null ? "Sınırsız" : plan.max_uploads_per_month}
          </span>{" "}
          yükleme/ay
        </p>
        <p>
          <span className="text-foreground font-medium">
            {plan.max_orgs == null ? "Sınırsız" : plan.max_orgs}
          </span>{" "}
          organizasyon
        </p>
      </div>

      {/* Features */}
      <ul className="mb-6 flex-1 space-y-2">
        {plan.features.map((f) => (
          <li key={f} className="flex items-start gap-2 text-sm">
            <CheckIcon />
            <span>{f}</span>
          </li>
        ))}
      </ul>

      {/* CTA */}
      <button
        onClick={() => onSelect(plan.id)}
        disabled={loading || isCurrentPlan}
        aria-busy={loading}
        className={cn(
          "w-full rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          isCurrentPlan
            ? "bg-muted text-muted-foreground cursor-default"
            : isPopular
            ? "bg-primary text-primary-foreground hover:bg-primary/90"
            : "border border-border bg-card hover:bg-muted",
          loading && "opacity-50 cursor-wait",
        )}
      >
        {isCurrentPlan ? "Mevcut Plan" : loading ? "Yönlendiriliyor…" : "Planı Seç"}
      </button>
    </div>
  );
}

// ── Pricing page ──────────────────────────────────────────────────────────────

export default function BillingPage() {
  const [interval, setInterval] = useState<"month" | "year">("month");
  const [loading, setLoading] = useState<string | null>(null); // planId being processed
  const [error, setError] = useState<string | null>(null);

  // In production this would come from useQuery → GET /billing/subscription
  const currentPlan: string | null = null;

  const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  async function handleSelectPlan(planId: string) {
    setLoading(planId);
    setError(null);

    try {
      const token =
        typeof window !== "undefined"
          ? localStorage.getItem("access_token") ?? ""
          : "";

      const origin = typeof window !== "undefined" ? window.location.origin : "";

      const res = await fetch(`${API_BASE}/api/v1/billing/checkout`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          plan: planId,
          interval,
          success_url: `${origin}/billing/success?plan=${planId}`,
          cancel_url: `${origin}/billing`,
        }),
      });

      const json = await res.json();

      if (!res.ok || json.error) {
        throw new Error(json.detail ?? json.error ?? "Checkout başlatılamadı");
      }

      const checkoutUrl = json.data?.url;
      if (checkoutUrl) {
        window.location.href = checkoutUrl;
      } else {
        throw new Error("Stripe checkout URL alınamadı");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Bir hata oluştu");
      setLoading(null);
    }
  }

  return (
    <main className="mx-auto max-w-screen-xl space-y-10 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="text-center space-y-3">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
          Planınızı Seçin
        </h1>
        <p className="text-muted-foreground text-lg max-w-xl mx-auto">
          KOBİ'den kurumsal ölçeğe kadar her büyüklük için tasarlanmış
          AI-CFO çözümleri.
        </p>

        {/* Interval toggle */}
        <div className="inline-flex items-center gap-1 rounded-lg border border-border bg-muted p-1">
          <button
            onClick={() => setInterval("month")}
            className={cn(
              "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              interval === "month"
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            Aylık
          </button>
          <button
            onClick={() => setInterval("year")}
            className={cn(
              "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              interval === "year"
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            Yıllık
            <span className="ml-1.5 rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">
              %17 indirim
            </span>
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive text-center"
        >
          {error}
        </div>
      )}

      {/* Plan cards */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        {STATIC_PLANS.map((plan) => (
          <PlanCard
            key={plan.id}
            plan={plan}
            interval={interval}
            isPopular={plan.id === "pro"}
            currentPlan={currentPlan}
            onSelect={handleSelectPlan}
            loading={loading === plan.id}
          />
        ))}
      </div>

      {/* Trust badges */}
      <div className="border-t border-border pt-8 text-center space-y-3">
        <p className="text-sm text-muted-foreground">
          Tüm planlar 14 günlük ücretsiz deneme içerir. Kredi kartı gerekmez.
        </p>
        <div className="flex flex-wrap justify-center gap-6 text-xs text-muted-foreground">
          {[
            "🔒 SSL şifreleme",
            "🇹🇷 KVKK uyumlu",
            "💳 Güvenli ödeme (Stripe)",
            "📞 7/24 destek (Enterprise)",
          ].map((badge) => (
            <span key={badge}>{badge}</span>
          ))}
        </div>
      </div>
    </main>
  );
}
