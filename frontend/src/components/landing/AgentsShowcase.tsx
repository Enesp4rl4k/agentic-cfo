"use client";

import { useState } from "react";
import { ArrowRight } from "lucide-react";
import Link from "next/link";

// ── Agent definitions ─────────────────────────────────────────────────────────

const AGENTS = [
  {
    role: "CFO",
    title: "Chief Financial Officer",
    color: "from-emerald-500 to-teal-600",
    ring: "ring-emerald-500/30",
    border: "border-emerald-500/20",
    bg: "bg-emerald-500/8",
    text: "text-emerald-400",
    metrics: ["P&L Analizi", "Nakit Akışı", "12 Aylık Tahmin", "Bütçe Sapması"],
    desc: "Finansal tablolarınızı anlık analiz eder. Gelir, gider, marj ve nakit akışını otomatik raporlar.",
    kpi: { label: "Net Marj", value: "28.4%", trend: "+3.2%" },
  },
  {
    role: "CEO",
    title: "Chief Executive Officer",
    color: "from-violet-500 to-purple-600",
    ring: "ring-violet-500/30",
    border: "border-violet-500/20",
    bg: "bg-violet-500/8",
    text: "text-violet-400",
    metrics: ["OKR Takibi", "Stratejik Öncelikler", "SWOT Analizi", "Board Deck"],
    desc: "Tüm C-Suite verilerini birleştirerek CEO perspektifinde özet ve yönetim kurulu sunumu üretir.",
    kpi: { label: "Şirket Skoru", value: "87/100", trend: "+5 puan" },
  },
  {
    role: "CTO",
    title: "Chief Technology Officer",
    color: "from-blue-500 to-indigo-600",
    ring: "ring-blue-500/30",
    border: "border-blue-500/20",
    bg: "bg-blue-500/8",
    text: "text-blue-400",
    metrics: ["Teknik Borç", "Sprint Hızı", "Sistem Sağlığı", "Bulut Maliyeti"],
    desc: "Teknik altyapı sağlığını ölçer, borç skorunu hesaplar ve optimizasyon önerilerini listeler.",
    kpi: { label: "Tech Sağlık", value: "7.8/10", trend: "+0.4" },
  },
  {
    role: "COO",
    title: "Chief Operating Officer",
    color: "from-orange-500 to-amber-600",
    ring: "ring-orange-500/30",
    border: "border-orange-500/20",
    bg: "bg-orange-500/8",
    text: "text-orange-400",
    metrics: ["Operasyon Verimliliği", "SLA İzleme", "Kaynak Kullanımı", "Süreç Analizi"],
    desc: "Operasyonel darboğazları tespit eder, SLA ihlallerini tahmin eder ve kaynak optimizasyonu önerir.",
    kpi: { label: "SLA Uyum", value: "94.2%", trend: "+1.8%" },
  },
  {
    role: "CMO",
    title: "Chief Marketing Officer",
    color: "from-pink-500 to-rose-600",
    ring: "ring-pink-500/30",
    border: "border-pink-500/20",
    bg: "bg-pink-500/8",
    text: "text-pink-400",
    metrics: ["CAC Analizi", "LTV Hesaplama", "Kampanya ROI", "Churn Oranı"],
    desc: "Pazarlama harcamalarının verimliliğini ölçer, müşteri yaşam boyu değerini hesaplar.",
    kpi: { label: "LTV/CAC", value: "4.2x", trend: "+0.6x" },
  },
  {
    role: "CHRO",
    title: "Chief HR Officer",
    color: "from-cyan-500 to-sky-600",
    ring: "ring-cyan-500/30",
    border: "border-cyan-500/20",
    bg: "bg-cyan-500/8",
    text: "text-cyan-400",
    metrics: ["İşten Ayrılma", "Ücret Analizi", "Departman Sağlığı", "İşe Alım Verimliliği"],
    desc: "İnsan kaynakları metriklerini analiz eder, attrition riskini önceden tespit eder.",
    kpi: { label: "Attrition", value: "8.3%", trend: "-1.2%" },
  },
];

export function AgentsShowcase() {
  const [active, setActive] = useState(0);
  const agent = AGENTS[active];

  return (
    <section id="ajanlar" className="relative overflow-hidden py-24">
      {/* Background */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 70% 50% at 50% 100%, oklch(0.55 0.22 220 / 0.08) 0%, transparent 70%)",
        }}
      />
      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">

        {/* Section header */}
        <div className="mb-14 text-center">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Her yönetici rolü için özel AI ajan
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Verilerinizi yükleyin — her ajan kendi uzmanlık alanında paralel çalışır.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-8 lg:grid-cols-2 lg:items-start">

          {/* ── Left: agent selector tabs ──────────────────────────────────── */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {AGENTS.map((a, i) => (
              <button
                key={a.role}
                onClick={() => setActive(i)}
                aria-pressed={active === i}
                className={`group flex flex-col items-center gap-2 rounded-xl border p-4 text-center transition-all duration-200 press-feedback focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  active === i
                    ? `${a.border} ${a.bg} ring-1 ${a.ring} shadow-lg`
                    : "border-border bg-card hover:border-primary/20 hover:bg-muted/40"
                }`}
              >
                {/* Avatar */}
                <div
                  className={`flex h-11 w-11 items-center justify-center rounded-full bg-gradient-to-br ${a.color} shadow-lg`}
                  aria-hidden="true"
                >
                  <span className="text-xs font-bold text-white">{a.role}</span>
                </div>
                {/* Label */}
                <div>
                  <p className={`text-xs font-semibold ${active === i ? a.text : "text-foreground"}`}>
                    {a.role}
                  </p>
                  <p className="text-[10px] text-muted-foreground leading-tight">{a.title}</p>
                </div>
                {/* Active indicator */}
                {active === i && (
                  <span className={`h-1 w-6 rounded-full bg-gradient-to-r ${a.color}`} aria-hidden="true" />
                )}
              </button>
            ))}
          </div>

          {/* ── Right: agent detail panel ───────────────────────────────────── */}
          <div
            key={agent.role}  // re-mount for enter animation
            className={`rounded-2xl border ${agent.border} ${agent.bg} p-6`}
            style={{ animation: "slide-up 300ms var(--ease-out-expo) both" }}
          >
            {/* Header */}
            <div className="mb-5 flex items-center gap-3">
              <div
                className={`flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br ${agent.color} shadow-lg`}
                aria-hidden="true"
              >
                <span className="text-sm font-bold text-white">{agent.role}</span>
              </div>
              <div>
                <h3 className="font-bold text-foreground">{agent.role} Ajanı</h3>
                <p className="text-xs text-muted-foreground">{agent.title}</p>
              </div>

              {/* KPI badge */}
              <div className="ml-auto text-right">
                <p className={`text-lg font-bold tabular-nums ${agent.text}`}>
                  {agent.kpi.value}
                </p>
                <p className="text-xs text-emerald-400">{agent.kpi.trend}</p>
                <p className="text-[10px] text-muted-foreground">{agent.kpi.label}</p>
              </div>
            </div>

            {/* Description */}
            <p className="mb-5 text-sm leading-relaxed text-muted-foreground">
              {agent.desc}
            </p>

            {/* Capability chips */}
            <div className="mb-5 flex flex-wrap gap-2">
              {agent.metrics.map((m) => (
                <span
                  key={m}
                  className={`rounded-full border ${agent.border} ${agent.bg} px-2.5 py-1 text-xs font-medium ${agent.text}`}
                >
                  {m}
                </span>
              ))}
            </div>

            {/* Activity simulation */}
            <div className={`rounded-lg border ${agent.border} bg-background/40 p-3`}>
              <div className="mb-2 flex items-center justify-between">
                <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Son Analiz
                </p>
                <span className="flex items-center gap-1 text-[10px] text-emerald-400">
                  <span className="relative flex h-1.5 w-1.5">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                    <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
                  </span>
                  Hazır
                </span>
              </div>
              <div className="space-y-1.5">
                {agent.metrics.slice(0, 3).map((m, idx) => (
                  <div key={m} className="flex items-center gap-2">
                    <div
                      className={`h-1 rounded-full ${agent.text.replace("text-", "bg-")}`}
                      style={{
                        width: `${60 + idx * 12}%`,
                        opacity: 0.4 + idx * 0.2,
                      }}
                      aria-hidden="true"
                    />
                    <span className="text-[10px] text-muted-foreground">{m}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Command center callout */}
        <div className="mt-10 overflow-hidden rounded-2xl border border-primary/20 bg-primary/5">
          <div className="flex flex-col items-center gap-4 p-6 text-center sm:flex-row sm:text-left">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/20">
              <span className="text-lg font-bold text-primary" aria-hidden="true">✦</span>
            </div>
            <div className="flex-1">
              <p className="font-semibold text-foreground">
                Command Center — Tüm ajanlar, tek ekranda
              </p>
              <p className="mt-0.5 text-sm text-muted-foreground">
                Çapraz-domain risk analizi, hızlı kazanımlar, şirket sağlık skoru.
                Tüm C-Suite ajanlarının sonuçları otomatik birleştirilir.
              </p>
            </div>
            <Link
              href="/auth/register"
              className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 press-feedback"
            >
              Dene <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
