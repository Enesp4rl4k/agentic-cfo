"use client";

import Link from "next/link";
import { useState } from "react";
import { Check, ArrowRight, Zap } from "lucide-react";
import { contactHref } from "@/lib/branding";

const PLANS = [
  {
    id: "starter",
    name: "Starter",
    monthly: "Ücretsiz",
    yearly: "Ücretsiz",
    period: "",
    desc: "Küçük işletmeler ve deneme için",
    highlight: false,
    badge: null,
    features: [
      "5 analiz / ay",
      "CFO & CEO ajanları",
      "PDF & Excel raporlar",
      "1 kullanıcı",
      "E-posta destek",
    ],
    cta: "Ücretsiz Başla",
    href: "/auth/register",
    variant: "outline" as const,
  },
  {
    id: "pro",
    name: "Growth",
    monthly: "₺2.990",
    yearly: "₺2.490",
    period: "/ ay",
    desc: "Büyüyen şirketler için tam paket",
    highlight: true,
    badge: "En Popüler",
    features: [
      "Sınırsız analiz",
      "Tüm 12 C-Suite ajanı",
      "Anomali & risk modülleri",
      "Monte Carlo simülasyonu",
      "5 kullanıcı",
      "API erişimi",
      "Öncelikli destek",
    ],
    cta: "14 Gün Deneyin",
    href: "/auth/register",
    variant: "default" as const,
  },
  {
    id: "enterprise",
    name: "Enterprise",
    monthly: "Özel",
    yearly: "Özel",
    period: "",
    desc: "Kurumsal müşteriler için özel çözüm",
    highlight: false,
    badge: null,
    features: [
      "Sınırsız kullanıcı",
      "SSO / SAML entegrasyonu",
      "SOC2 & KVKK uyumluluk",
      "White-label seçeneği",
      "On-premise kurulum",
      "SLA garantisi",
      "Dedicated müşteri başarı",
    ],
    cta: "Teklif Alın",
    href: contactHref() ?? "#",
    variant: "outline" as const,
  },
];

export function PricingTable() {
  const [yearly, setYearly] = useState(false);

  return (
    <section id="fiyatlandırma" className="relative py-24">
      {/* Subtle glow */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 50% 40% at 50% 0%, oklch(0.62 0.26 262 / 0.07) 0%, transparent 70%)",
        }}
      />

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        {/* Section header */}
        <div className="mb-12 text-center">
          <div className="mb-3 flex justify-center">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/6 px-3 py-1 text-xs font-medium text-primary">
              <Zap className="h-3 w-3" aria-hidden="true" />
              Fiyatlandırma
            </span>
          </div>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Şeffaf fiyatlandırma
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Kredi kartı olmadan deneyin. İstediğiniz zaman iptal edin.
          </p>

          {/* Billing toggle */}
          <div className="mt-6 inline-flex items-center gap-1 rounded-lg border border-border bg-muted p-1">
            <button
              onClick={() => setYearly(false)}
              className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
                !yearly
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Aylık
            </button>
            <button
              onClick={() => setYearly(true)}
              className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
                yearly
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Yıllık
              <span className="ml-1.5 rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-400">
                %17 indirim
              </span>
            </button>
          </div>
        </div>

        {/* Plans grid */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3 lg:items-stretch">
          {PLANS.map((plan) => (
            <div
              key={plan.name}
              className={`relative flex flex-col rounded-2xl border p-6 transition-all duration-200 ${
                plan.highlight
                  ? "border-primary bg-primary/5 shadow-xl shadow-primary/10 ring-1 ring-primary/20"
                  : "border-border bg-card hover:border-primary/20"
              }`}
            >
              {/* Popular badge */}
              {plan.badge && (
                <div className="absolute -top-3.5 left-1/2 -translate-x-1/2">
                  <span className="inline-flex items-center gap-1 rounded-full bg-primary px-3 py-1 text-xs font-semibold text-primary-foreground shadow-lg">
                    <span className="h-1.5 w-1.5 rounded-full bg-primary-foreground/70" aria-hidden="true" />
                    {plan.badge}
                  </span>
                </div>
              )}

              {/* Plan info */}
              <div className="mb-5">
                <h3 className="text-lg font-bold">{plan.name}</h3>
                <p className="mt-0.5 text-sm text-muted-foreground">{plan.desc}</p>
              </div>

              {/* Price */}
              <div className="mb-5 flex items-baseline gap-1">
                <span className="text-3xl font-bold tracking-tight">
                  {yearly ? plan.yearly : plan.monthly}
                </span>
                {plan.period && (
                  <span className="text-sm text-muted-foreground">{plan.period}</span>
                )}
              </div>
              {yearly && plan.id === "pro" && (
                <p className="mb-3 -mt-3 text-xs text-muted-foreground">
                  (₺29.880 / yıl olarak faturalandırılır)
                </p>
              )}

              {/* Divider */}
              <div className="mb-5 h-px bg-border" />

              {/* Features */}
              <ul className="mb-8 flex-1 space-y-3">
                {plan.features.map((f) => (
                  <li key={f} className="flex items-start gap-2.5 text-sm">
                    <Check
                      className={`mt-0.5 h-4 w-4 shrink-0 ${
                        plan.highlight ? "text-primary" : "text-emerald-400"
                      }`}
                      aria-hidden="true"
                    />
                    <span className="text-muted-foreground">{f}</span>
                  </li>
                ))}
              </ul>

              {/* CTA */}
              <Link
                href={plan.href}
                className={`flex h-10 w-full items-center justify-center gap-2 rounded-lg text-sm font-semibold transition-all press-feedback focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  plan.highlight
                    ? "bg-primary text-primary-foreground hover:opacity-90 shadow-lg shadow-primary/20"
                    : "border border-border bg-transparent hover:bg-muted"
                }`}
              >
                {plan.cta}
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            </div>
          ))}
        </div>

        {/* Trust footnote */}
        <p className="mt-8 text-center text-sm text-muted-foreground">
          Tüm planlar 14 günlük ücretsiz deneme içerir · Kredi kartı gerekmez · İstediğiniz zaman iptal edin
        </p>
      </div>
    </section>
  );
}
