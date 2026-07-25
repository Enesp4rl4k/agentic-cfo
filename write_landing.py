import pathlib, textwrap

# ── Landing page ──────────────────────────────────────────────────────────────
landing = r'''\
"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight, BarChart3, Brain, Shield, TrendingUp,
  Users, Zap, ChevronDown, Crown,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Scroll-reveal hook ────────────────────────────────────────────────────────
function useInView(threshold = 0.15) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { setVisible(true); obs.disconnect(); } },
      { threshold },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [threshold]);
  return { ref, visible };
}

// ── Nav ───────────────────────────────────────────────────────────────────────
function Nav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const fn = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", fn, { passive: true });
    return () => window.removeEventListener("scroll", fn);
  }, []);
  return (
    <header className={cn(
      "fixed top-0 z-50 w-full transition-all duration-300",
      scrolled
        ? "border-b border-white/8 bg-[oklch(0.13_0.025_255/0.85)] backdrop-blur-xl"
        : "bg-transparent",
    )}>
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
        <div className="flex items-center gap-2.5">
          <Crown className="h-5 w-5 text-[oklch(0.60_0.19_255)]" aria-hidden="true" />
          <span className="text-sm font-semibold tracking-tight text-white">Agentic CFO</span>
        </div>
        <nav className="hidden items-center gap-8 md:flex" aria-label="Primary">
          {["Product", "Features", "Agents", "Pricing"].map(l => (
            <a key={l} href={`#${l.toLowerCase()}`}
              className="text-sm text-white/60 transition-colors hover:text-white">
              {l}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          <Link href="/"
            className="rounded-md px-4 py-2 text-sm font-medium text-white/70 transition-colors hover:text-white">
            Sign in
          </Link>
          <Link href="/"
            className="rounded-md bg-[oklch(0.60_0.19_255)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90">
            Get started
          </Link>
        </div>
      </div>
    </header>
  );
}

// ── Hero ──────────────────────────────────────────────────────────────────────
function Hero() {
  return (
    <section className="relative flex min-h-screen items-center justify-center overflow-hidden" id="product">
      {/* Video background */}
      <div className="absolute inset-0 z-0">
        <video
          autoPlay muted loop playsInline
          className="h-full w-full object-cover opacity-25"
          aria-hidden="true"
        >
          {/* Fallback: abstract financial data visualization */}
          <source
            src="https://assets.mixkit.co/videos/preview/mixkit-abstract-technology-network-connections-background-38439-large.mp4"
            type="video/mp4"
          />
        </video>
        {/* Gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-b from-[oklch(0.13_0.025_255/0.6)] via-[oklch(0.13_0.025_255/0.4)] to-[oklch(0.13_0.025_255)]" />
        {/* Radial glow */}
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_50%_at_50%_-10%,oklch(0.60_0.19_255/0.15),transparent)]" />
      </div>

      {/* Content */}
      <div className="relative z-10 mx-auto max-w-5xl px-6 text-center">
        <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-1.5 text-xs font-medium text-white/70 backdrop-blur-sm">
          <span className="h-1.5 w-1.5 rounded-full bg-[oklch(0.60_0.19_255)] animate-pulse" />
          Powered by LangGraph + DeepSeek
        </div>

        <h1 className="mb-6 text-5xl font-bold leading-[1.08] tracking-tight text-white sm:text-6xl lg:text-7xl">
          Your entire C-suite,{" "}
          <span className="bg-gradient-to-r from-[oklch(0.60_0.19_255)] to-[oklch(0.72_0.18_200)] bg-clip-text text-transparent">
            on autopilot
          </span>
        </h1>

        <p className="mx-auto mb-10 max-w-2xl text-lg leading-relaxed text-white/60">
          Upload your financial data. Get CFO-grade P&amp;L analysis, CTO reliability insights,
          CMO unit economics, compliance risk scores — synthesized by AI agents that think across domains.
        </p>

        <div className="flex flex-wrap items-center justify-center gap-4">
          <Link href="/"
            className="group flex items-center gap-2 rounded-lg bg-[oklch(0.60_0.19_255)] px-6 py-3 text-sm font-semibold text-white shadow-[0_0_40px_oklch(0.60_0.19_255/0.35)] transition-all hover:shadow-[0_0_60px_oklch(0.60_0.19_255/0.50)] hover:scale-[1.02]">
            Start for free
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
          </Link>
          <a href="#features"
            className="flex items-center gap-2 rounded-lg border border-white/15 px-6 py-3 text-sm font-medium text-white/70 transition-colors hover:border-white/30 hover:text-white">
            See how it works
          </a>
        </div>

        {/* Scroll cue */}
        <div className="mt-20 flex justify-center">
          <a href="#features" aria-label="Scroll down" className="animate-bounce text-white/30 hover:text-white/60 transition-colors">
            <ChevronDown className="h-6 w-6" />
          </a>
        </div>
      </div>
    </section>
  );
}

// ── Feature card ──────────────────────────────────────────────────────────────
function FeatureCard({
  icon: Icon, title, description, tag, delay = 0,
}: {
  icon: React.ElementType; title: string; description: string; tag: string; delay?: number;
}) {
  const { ref, visible } = useInView();
  return (
    <div
      ref={ref}
      style={{ transitionDelay: `${delay}ms` }}
      className={cn(
        "group rounded-2xl border border-white/8 bg-white/3 p-6 backdrop-blur-sm transition-all duration-700",
        "hover:border-white/15 hover:bg-white/5",
        visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-8",
      )}
    >
      <div className="mb-4 inline-flex rounded-xl bg-[oklch(0.60_0.19_255/0.12)] p-3 ring-1 ring-[oklch(0.60_0.19_255/0.20)]">
        <Icon className="h-5 w-5 text-[oklch(0.60_0.19_255)]" aria-hidden="true" />
      </div>
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-[oklch(0.60_0.19_255/0.80)]">{tag}</p>
      <h3 className="mb-2 text-base font-semibold text-white">{title}</h3>
      <p className="text-sm leading-relaxed text-white/50">{description}</p>
    </div>
  );
}

// ── Features grid ─────────────────────────────────────────────────────────────
const FEATURES = [
  { icon: TrendingUp,  tag: "CFO Agent",        title: "P&L, Cash Flow & Forecast",    description: "Upload a bank export. Get instant P&L breakdown, runway analysis, 12-month forecast with bear/base/bull scenarios." },
  { icon: Brain,       tag: "CEO Agent",         title: "Cross-Domain Synthesis",        description: "Identifies risks neither finance nor tech can see alone — infra waste vs cash runway, tech debt vs revenue trajectory." },
  { icon: BarChart3,   tag: "CTO Agent",         title: "Tech Health Score",             description: "Cloud cost waste, incident MTTR, sprint velocity, tech debt hotspots. All in one 0–10 reliability score." },
  { icon: Users,       tag: "CMO / CHRO",        title: "Marketing & People Analytics",  description: "LTV:CAC ratio, ROAS, churn rate, compensation benchmarks, attrition risk — synthesized with financial impact." },
  { icon: Shield,      tag: "Compliance Agent",  title: "SOC2, GDPR, ISO 27001",        description: "Violation tracking, remediation SLAs, regulatory coverage scores. Critical gaps surface automatically with fix recommendations." },
  { icon: Zap,         tag: "COO Agent",         title: "Operational Efficiency",        description: "Process bottlenecks, resource utilization, SLA breach rates. Identifies where operational drag is costing you margin." },
];

function FeaturesSection() {
  const { ref, visible } = useInView();
  return (
    <section id="features" className="relative py-32">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_60%_40%_at_50%_50%,oklch(0.60_0.19_255/0.05),transparent)]" />
      <div className="relative mx-auto max-w-7xl px-6">
        <div ref={ref} className={cn(
          "mb-16 text-center transition-all duration-700",
          visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-8",
        )}>
          <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-[oklch(0.60_0.19_255)]">
            What it does
          </p>
          <h2 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Six agents. One intelligence layer.
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-base text-white/50">
            Each agent is a specialist. The CEO orchestrator connects the dots across all of them.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => (
            <FeatureCard key={f.tag} {...f} delay={i * 80} />
          ))}
        </div>
      </div>
    </section>
  );
}

// ── How it works ──────────────────────────────────────────────────────────────
const STEPS = [
  { n: "01", title: "Upload your data",        body: "Drop a CSV bank export, P&L sheet, or paste raw data. No formatting required — parsers handle Akbank, Garanti, Ziraat, generic formats." },
  { n: "02", title: "Agents run in parallel",  body: "LangGraph orchestrates all skill agents simultaneously. Each analyzes its domain, generates metrics, alerts, and narratives in seconds." },
  { n: "03", title: "Get actionable insights", body: "A synthesized dashboard shows your health score, top risks ranked by urgency, and specific actions — not just charts." },
];

function HowItWorks() {
  return (
    <section id="agents" className="py-32 border-t border-white/6">
      <div className="mx-auto max-w-7xl px-6">
        <div className="grid grid-cols-1 gap-16 lg:grid-cols-2 lg:gap-24 items-center">
          <div>
            <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-[oklch(0.60_0.19_255)]">
              How it works
            </p>
            <h2 className="mb-6 text-3xl font-bold tracking-tight text-white sm:text-4xl">
              From raw data to<br />board-ready insights
            </h2>
            <p className="mb-10 text-base leading-relaxed text-white/50">
              No integrations to set up. No dashboards to configure. Just upload what you have
              and the pipeline does the rest.
            </p>
            <div className="space-y-8">
              {STEPS.map(({ n, title, body }, i) => {
                const { ref, visible } = useInView();
                return (
                  <div
                    key={n}
                    ref={ref}
                    style={{ transitionDelay: `${i * 120}ms` }}
                    className={cn(
                      "flex gap-5 transition-all duration-700",
                      visible ? "opacity-100 translate-x-0" : "opacity-0 -translate-x-6",
                    )}
                  >
                    <div className="shrink-0 w-10 h-10 rounded-full border border-white/10 bg-white/5 flex items-center justify-center text-xs font-bold text-[oklch(0.60_0.19_255)]">
                      {n}
                    </div>
                    <div>
                      <h3 className="mb-1 text-sm font-semibold text-white">{title}</h3>
                      <p className="text-sm leading-relaxed text-white/50">{body}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Right: animated terminal-style card */}
          <div className="relative rounded-2xl border border-white/10 bg-white/3 p-6 backdrop-blur-sm">
            <div className="flex items-center gap-2 mb-4">
              <div className="h-3 w-3 rounded-full bg-red-500/70" />
              <div className="h-3 w-3 rounded-full bg-yellow-500/70" />
              <div className="h-3 w-3 rounded-full bg-green-500/70" />
              <span className="ml-2 text-xs text-white/30 font-mono">agentic-cfo pipeline</span>
            </div>
            <div className="space-y-2 font-mono text-xs">
              {[
                { t: "200ms", c: "text-green-400",  m: "✓ PoliciesAgent     — 7 policies analyzed" },
                { t: "340ms", c: "text-green-400",  m: "✓ ViolationsAgent   — 6 violations, 3 critical" },
                { t: "480ms", c: "text-green-400",  m: "✓ RegulationsAgent  — SOC2 72%, GDPR 50%" },
                { t: "510ms", c: "text-blue-400",   m: "→ ComplianceSummary — health 58/100 [poor]" },
                { t: "620ms", c: "text-green-400",  m: "✓ InfraAgent        — $4,200/mo waste detected" },
                { t: "740ms", c: "text-green-400",  m: "✓ IncidentAgent     — MTTR 6.2h, 40% SLA breach" },
                { t: "810ms", c: "text-yellow-400", m: "⚠ VelocityAgent    — trend: degrading" },
                { t: "920ms", c: "text-blue-400",   m: "→ CTO Summary       — health 7.1/10" },
                { t: "1.1s",  c: "text-purple-400", m: "★ CEO Synthesis     — 4 cross-domain risks" },
                { t: "1.2s",  c: "text-red-400",    m: "! CRITICAL: Compliance + cash runway clash" },
              ].map(({ t, c, m }, i) => (
                <div key={i} className="flex gap-3">
                  <span className="w-12 shrink-0 text-white/25">{t}</span>
                  <span className={c}>{m}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── Stats bar ─────────────────────────────────────────────────────────────────
const STATS = [
  { v: "6",     l: "AI Agents" },
  { v: "30+",   l: "Test coverage" },
  { v: "<2s",   l: "Full pipeline" },
  { v: "100%",  l: "Deterministic" },
];

function StatsBar() {
  const { ref, visible } = useInView();
  return (
    <section className="border-y border-white/6 py-14">
      <div ref={ref} className="mx-auto max-w-5xl px-6">
        <div className="grid grid-cols-2 gap-8 sm:grid-cols-4">
          {STATS.map(({ v, l }, i) => (
            <div
              key={l}
              style={{ transitionDelay: `${i * 80}ms` }}
              className={cn(
                "text-center transition-all duration-700",
                visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4",
              )}
            >
              <p className="text-3xl font-bold tracking-tight text-white">{v}</p>
              <p className="mt-1 text-xs text-white/40">{l}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── CTA section ───────────────────────────────────────────────────────────────
function CTASection() {
  const { ref, visible } = useInView();
  return (
    <section id="pricing" className="py-32">
      <div ref={ref} className={cn(
        "mx-auto max-w-3xl px-6 text-center transition-all duration-700",
        visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-8",
      )}>
        <div className="mb-8 inline-flex rounded-full border border-[oklch(0.60_0.19_255/0.30)] bg-[oklch(0.60_0.19_255/0.08)] px-5 py-2 text-sm font-medium text-[oklch(0.60_0.19_255)]">
          Free to use · No credit card
        </div>
        <h2 className="mb-5 text-4xl font-bold tracking-tight text-white sm:text-5xl">
          Your data. Your insights.<br />
          <span className="text-white/40">In under two seconds.</span>
        </h2>
        <p className="mb-10 text-base leading-relaxed text-white/50">
          Upload a CSV and get instant CFO-grade analysis. No setup, no integrations,
          no waiting for a consultant's slide deck.
        </p>
        <Link href="/"
          className="inline-flex items-center gap-2.5 rounded-xl bg-[oklch(0.60_0.19_255)] px-8 py-4 text-base font-semibold text-white shadow-[0_0_60px_oklch(0.60_0.19_255/0.40)] transition-all hover:scale-[1.02] hover:shadow-[0_0_80px_oklch(0.60_0.19_255/0.55)]">
          Open dashboard
          <ArrowRight className="h-5 w-5" aria-hidden="true" />
        </Link>
      </div>
    </section>
  );
}

// ── Footer ────────────────────────────────────────────────────────────────────
function Footer() {
  return (
    <footer className="border-t border-white/6 py-10">
      <div className="mx-auto max-w-7xl px-6">
        <div className="flex flex-col items-center justify-between gap-4 sm:flex-row">
          <div className="flex items-center gap-2">
            <Crown className="h-4 w-4 text-[oklch(0.60_0.19_255)]" aria-hidden="true" />
            <span className="text-sm font-medium text-white/50">Agentic CFO</span>
          </div>
          <p className="text-xs text-white/30">
            Built with LangGraph · Next.js · FastAPI · TypeScript
          </p>
        </div>
      </div>
    </footer>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function LandingPage() {
  return (
    <div className="min-h-screen bg-[oklch(0.13_0.025_255)] text-white">
      <Nav />
      <Hero />
      <StatsBar />
      <FeaturesSection />
      <HowItWorks />
      <CTASection />
      <Footer />
    </div>
  );
}
'''

out = pathlib.Path("frontend/src/app/(landing)/page.tsx")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(landing, encoding="utf-8")
print(f"Written landing page: {out} ({len(landing)} chars)")
