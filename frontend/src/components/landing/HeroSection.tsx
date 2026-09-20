"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, Zap, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { brand } from "@/lib/branding";

// ── Animated number counter ───────────────────────────────────────────────────
function AnimatedNumber({ target, suffix = "" }: { target: number; suffix?: string }) {
  const [current, setCurrent] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        observer.disconnect();

        let start = 0;
        const duration = 1200;
        const startTime = performance.now();

        function tick(now: number) {
          const progress = Math.min((now - startTime) / duration, 1);
          const ease = 1 - Math.pow(1 - progress, 3); // ease-out cubic
          setCurrent(Math.round(ease * target));
          if (progress < 1) requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
      },
      { threshold: 0.5 }
    );
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, [target]);

  return (
    <span ref={ref}>
      {current.toLocaleString("tr-TR")}
      {suffix}
    </span>
  );
}

// ── Mock dashboard KPI card ───────────────────────────────────────────────────
function KpiCard({
  label,
  value,
  change,
  color,
  delay,
}: {
  label: string;
  value: string;
  change: string;
  color: string;
  delay: string;
}) {
  return (
    <div
      className="rounded-lg border border-white/8 bg-white/4 p-3 backdrop-blur-sm"
      style={{ animationDelay: delay, animation: "slide-up 500ms var(--ease-out-expo) both" }}
    >
      <p className="text-[10px] font-medium text-white/50 uppercase tracking-wider">{label}</p>
      <p className={`mt-1 text-lg font-bold tabular-nums ${color}`}>{value}</p>
      <p className="mt-0.5 text-[10px] text-emerald-400">{change}</p>
    </div>
  );
}

// ── Typing animation for hero tagline ────────────────────────────────────────
const TAGLINES = [
  "CFO analizinizi 5 dakikada alın",
  "CEO board sunumunu otomatik üretin",
  "Tüm C-Suite kararları, tek platformda",
];

function TypingTagline() {
  const [lineIndex, setLineIndex] = useState(0);
  const [displayed, setDisplayed] = useState("");
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    const current = TAGLINES[lineIndex];
    const speed = isDeleting ? 30 : 55;

    const timer = setTimeout(() => {
      if (!isDeleting && displayed === current) {
        setTimeout(() => setIsDeleting(true), 2000);
        return;
      }
      if (isDeleting && displayed === "") {
        setIsDeleting(false);
        setLineIndex((i) => (i + 1) % TAGLINES.length);
        return;
      }
      setDisplayed((prev) =>
        isDeleting ? prev.slice(0, -1) : current.slice(0, prev.length + 1)
      );
    }, speed);

    return () => clearTimeout(timer);
  }, [displayed, isDeleting, lineIndex]);

  return (
    <span className="brand-gradient-text">
      {displayed}
      <span className="animate-pulse">|</span>
    </span>
  );
}

// ── Mini bar chart sparkline ──────────────────────────────────────────────────
const CHART_DATA = [42, 58, 51, 67, 61, 74, 68, 82, 75, 89, 84, 96];

function MiniBarChart() {
  return (
    <div className="flex h-16 items-end gap-0.5" aria-hidden="true">
      {CHART_DATA.map((h, i) => (
        <div
          key={i}
          className="flex-1 rounded-t-sm"
          style={{
            height: `${h}%`,
            background: `oklch(${0.55 + i * 0.012} 0.22 ${255 + i * 0.5})`,
            opacity: 0.7 + (i / CHART_DATA.length) * 0.3,
            animation: `slide-up 400ms var(--ease-out-expo) both`,
            animationDelay: `${i * 40}ms`,
          }}
        />
      ))}
    </div>
  );
}

// ── Agent status pills ────────────────────────────────────────────────────────
const AGENTS = [
  { name: "CFO", status: "✓", color: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" },
  { name: "CEO", status: "✓", color: "bg-violet-500/20 text-violet-400 border-violet-500/30" },
  { name: "CTO", status: "⟳", color: "bg-blue-500/20 text-blue-400 border-blue-500/30" },
  { name: "CMO", status: "○", color: "bg-white/5 text-white/30 border-white/10" },
];

// ── Main HeroSection ──────────────────────────────────────────────────────────
export function HeroSection() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <section className="relative min-h-screen overflow-hidden pb-24 pt-28 flex flex-col justify-center">

      {/* ── Background layers ─────────────────────────────────────────────── */}
      {/* Primary radial glow */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 80% 60% at 50% 0%, oklch(0.62 0.26 262 / 0.20) 0%, transparent 70%)",
        }}
      />
      {/* Secondary glow — offset bottom-right */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 50% 40% at 80% 90%, oklch(0.55 0.22 220 / 0.12) 0%, transparent 70%)",
        }}
      />
      {/* Subtle grid pattern */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage:
            "linear-gradient(oklch(0.8 0.1 262) 1px, transparent 1px), linear-gradient(90deg, oklch(0.8 0.1 262) 1px, transparent 1px)",
          backgroundSize: "60px 60px",
        }}
      />

      <div className="relative mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 items-center gap-16 lg:grid-cols-2">

          {/* ── Left: copy ──────────────────────────────────────────────── */}
          <div className="text-center lg:text-left">

            {/* Pill badge */}
            <div className="mb-6 flex justify-center lg:justify-start">
              <span className="inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/8 px-3.5 py-1.5 text-xs font-medium text-primary">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
                </span>
                <Zap className="h-3 w-3" aria-hidden="true" />
                Yapay Zeka Destekli C-Suite Platform
              </span>
            </div>

            {/* Main headline */}
            <h1 className="text-4xl font-bold tracking-tight text-foreground sm:text-5xl lg:text-6xl">
              <span className="block">Tüm C-Suite,</span>
              <span
                className="block mt-1"
                style={{
                  background: "linear-gradient(135deg, oklch(0.78 0.22 262), oklch(0.65 0.20 220))",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  backgroundClip: "text",
                }}
              >
                yapay zeka ile
              </span>
              <span className="block">güçlendirildi</span>
            </h1>

            {/* Typing tagline */}
            {mounted && (
              <p className="mt-4 h-8 text-base font-medium sm:text-lg">
                <TypingTagline />
              </p>
            )}

            {/* Description */}
            <p className="mt-5 text-base leading-relaxed text-muted-foreground sm:text-lg">
              CFO, CEO, CTO, COO, CMO, CHRO — her yönetici rolü için gerçek zamanlı
              AI analizi. Muhasebe verilerinizi yükleyin,{" "}
              <span className="text-foreground font-medium">5 dakikada</span>{" "}
              kurumsal içgörüler alın.
            </p>

            {/* CTA group */}
            <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row lg:justify-start">
              <Button size="lg" asChild className="h-12 px-7 text-base press-feedback">
                <Link href="/auth/register">
                  Ücretsiz Başla
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Link>
              </Button>
              <Button
                size="lg"
                variant="outline"
                asChild
                className="h-12 px-7 text-base border-white/15 hover:border-white/30 press-feedback"
              >
                <Link href="/auth/login">
                  Demo İzle
                </Link>
              </Button>
            </div>

            {/* Trust row */}
            <p className="mt-4 text-xs text-muted-foreground">
              Kredi kartı gerekmez · 14 gün ücretsiz · 2 dakikada kurulum
            </p>

            {/* Stats row */}
            <div className="mt-8 flex flex-wrap items-center gap-6 justify-center lg:justify-start">
              {[
                { label: "AI Ajan", value: 12, suffix: "+" },
                { label: "Test geçiyor", value: 941, suffix: "" },
                { label: "Dakikada analiz", value: 5, suffix: "" },
              ].map((stat) => (
                <div key={stat.label} className="text-center lg:text-left">
                  <p className="text-xl font-bold tabular-nums text-foreground">
                    <AnimatedNumber target={stat.value} suffix={stat.suffix} />
                  </p>
                  <p className="text-xs text-muted-foreground">{stat.label}</p>
                </div>
              ))}
            </div>
          </div>

          {/* ── Right: dashboard mockup ──────────────────────────────────── */}
          <div className="relative hidden lg:block">

            {/* Glow behind mockup */}
            <div
              aria-hidden="true"
              className="absolute -inset-10 rounded-3xl blur-3xl"
              style={{
                background: "radial-gradient(ellipse at center, oklch(0.62 0.26 262 / 0.15) 0%, transparent 70%)",
              }}
            />

            {/* Browser frame */}
            <div
              className="relative overflow-hidden rounded-2xl border border-white/10 shadow-2xl"
              style={{
                background: "oklch(0.13 0.028 262)",
                boxShadow: "0 0 60px oklch(0.62 0.26 262 / 0.20), 0 40px 80px rgba(0,0,0,0.5)",
              }}
            >
              {/* Chrome bar */}
              <div className="flex items-center gap-3 border-b border-white/8 bg-white/3 px-4 py-3">
                <div className="flex gap-1.5" aria-hidden="true">
                  <div className="h-2.5 w-2.5 rounded-full bg-red-500/60" />
                  <div className="h-2.5 w-2.5 rounded-full bg-yellow-500/60" />
                  <div className="h-2.5 w-2.5 rounded-full bg-green-500/60" />
                </div>
                <div className="flex-1 rounded-md border border-white/8 bg-white/4 px-3 py-1 text-center text-xs text-white/40">
                  {brand.domain ? `app.${brand.domain}/dashboard` : "/dashboard"}
                </div>
                <div className="h-4 w-4 rounded-full bg-white/10" aria-hidden="true" />
              </div>

              {/* Dashboard content */}
              <div className="p-4 space-y-3">
                {/* KPI row */}
                <div className="grid grid-cols-2 gap-2">
                  <KpiCard label="Gelir"       value="₺4.8M"  change="+18% geçen aya göre" color="text-emerald-400" delay="100ms" />
                  <KpiCard label="Net Kâr"     value="₺892K"  change="+24% geçen aya göre" color="text-emerald-400" delay="150ms" />
                  <KpiCard label="Nakit Akışı" value="₺1.2M"  change="+11% geçen aya göre" color="text-blue-400"    delay="200ms" />
                  <KpiCard label="Risk Skoru"  value="87/100" change="Son 7 günde +3 puan"  color="text-violet-400"  delay="250ms" />
                </div>

                {/* Chart card */}
                <div className="rounded-lg border border-white/8 bg-white/3 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-medium text-white/70">12 Aylık Tahmin — 3 Senaryo</p>
                    <div className="flex gap-2 text-[10px] text-white/40">
                      <span className="flex items-center gap-1">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
                        Optimist
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="h-1.5 w-1.5 rounded-full bg-blue-400" aria-hidden="true" />
                        Baz
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="h-1.5 w-1.5 rounded-full bg-red-400" aria-hidden="true" />
                        Pesimist
                      </span>
                    </div>
                  </div>
                  <MiniBarChart />
                </div>

                {/* Agent status row */}
                <div className="flex items-center justify-between rounded-lg border border-white/8 bg-white/3 px-3 py-2">
                  <p className="text-[10px] text-white/40 font-medium">AI Ajanlar</p>
                  <div className="flex gap-1.5">
                    {AGENTS.map((a) => (
                      <span
                        key={a.name}
                        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${a.color}`}
                      >
                        <span>{a.status}</span>
                        {a.name}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Floating alert card */}
            <div
              className="absolute -bottom-4 -left-8 glass rounded-xl px-3 py-2.5 shadow-xl"
              style={{ animation: "slide-up 600ms 400ms var(--ease-out-expo) both" }}
              aria-hidden="true"
            >
              <div className="flex items-center gap-2">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-orange-500/20">
                  <span className="text-[10px]">⚠</span>
                </div>
                <div>
                  <p className="text-[11px] font-medium text-orange-300">Anomali Tespit Edildi</p>
                  <p className="text-[10px] text-white/40">Tedarikçi yoğunlaşması %67</p>
                </div>
              </div>
            </div>

            {/* Floating CEO card */}
            <div
              className="absolute -top-4 -right-6 glass rounded-xl px-3 py-2.5 shadow-xl"
              style={{ animation: "slide-up 600ms 300ms var(--ease-out-expo) both" }}
              aria-hidden="true"
            >
              <p className="text-[10px] font-medium text-violet-300">CEO Board Deck</p>
              <p className="text-[10px] text-white/40">Hazır — PDF indir</p>
            </div>
          </div>
        </div>

        {/* ── Scroll indicator ──────────────────────────────────────────── */}
        <div className="mt-16 flex justify-center" aria-hidden="true">
          <a
            href="#social-proof"
            className="flex flex-col items-center gap-1 text-muted-foreground transition-colors hover:text-foreground"
          >
            <span className="text-xs">Keşfet</span>
            <ChevronDown className="h-4 w-4 animate-bounce" />
          </a>
        </div>
      </div>
    </section>
  );
}
