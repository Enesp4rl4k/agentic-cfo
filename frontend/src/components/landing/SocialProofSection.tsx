"use client";

import { useEffect, useRef, useState } from "react";

// ── Animated stat counter ─────────────────────────────────────────────────────
function Counter({
  target,
  suffix = "",
  prefix = "",
}: {
  target: number;
  suffix?: string;
  prefix?: string;
}) {
  const [value, setValue] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        observer.disconnect();
        const start = performance.now();
        const duration = 1400;
        function tick(now: number) {
          const t = Math.min((now - start) / duration, 1);
          const ease = 1 - Math.pow(1 - t, 4);
          setValue(Math.round(ease * target));
          if (t < 1) requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
      },
      { threshold: 0.5 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [target]);

  return (
    <span ref={ref} className="tabular-nums">
      {prefix}
      {value.toLocaleString("tr-TR")}
      {suffix}
    </span>
  );
}

// ── Stats ─────────────────────────────────────────────────────────────────────
const STATS = [
  {
    value: 12,
    suffix: "+",
    label: "AI Ajan",
    sub: "CFO · CEO · CTO · CMO · COO · CHRO + daha fazlası",
  },
  {
    value: 5,
    suffix: " dk",
    label: "İlk Analize Kadar",
    sub: "CSV yükle → kurumsal rapor al",
  },
  {
    value: 941,
    suffix: "",
    label: "Test Geçiyor",
    sub: "%100 güvenilir CI/CD pipeline",
  },
  {
    value: 3,
    suffix: "+",
    label: "ERP Entegrasyonu",
    sub: "Logo Tiger · Paraşüt · GİB e-Fatura",
  },
];

// ── Trust logos placeholder ───────────────────────────────────────────────────
const INTEGRATIONS = [
  "Logo Tiger",
  "Paraşüt",
  "GİB e-Fatura",
  "Open Banking",
  "Shopify",
  "Trendyol",
];

export function SocialProofSection() {
  return (
    <section id="social-proof" className="border-y border-border py-16">
      {/* Subtle bg */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-0 right-0 h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent, oklch(0.62 0.26 262 / 0.3), transparent)",
        }}
      />

      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        {/* Stats grid */}
        <div className="grid grid-cols-2 gap-8 md:grid-cols-4">
          {STATS.map((stat) => (
            <div key={stat.label} className="group text-center">
              <p className="text-3xl font-bold tracking-tight text-foreground sm:text-4xl">
                <Counter target={stat.value} suffix={stat.suffix} />
              </p>
              <p className="mt-1 text-sm font-medium text-foreground/80">{stat.label}</p>
              <p className="mt-0.5 text-xs text-muted-foreground leading-snug">{stat.sub}</p>
            </div>
          ))}
        </div>

        {/* Divider */}
        <div className="my-10 border-t border-border/50" />

        {/* Integration logos */}
        <div className="flex flex-col items-center gap-4">
          <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            Desteklenen entegrasyonlar
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            {INTEGRATIONS.map((name) => (
              <span
                key={name}
                className="rounded-full border border-border bg-muted/30 px-4 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-primary/30 hover:text-foreground"
              >
                {name}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
