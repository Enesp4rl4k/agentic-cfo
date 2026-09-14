"use client";

export const dynamic = "force-dynamic";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  AlertTriangle, Zap, TrendingDown, Users, Cpu, Megaphone,
  Layers, DollarSign, Shield, ChevronRight, RefreshCw,
  Play, BarChart3, Clock, ArrowRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api/client";
import { useFullContext } from "@/hooks/useCompanyContext";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DomainImpact {
  domain: string;
  impact_level: "none" | "low" | "medium" | "high" | "critical";
  impact_score: number;
  primary_effect: string;
  secondary_effects: string[];
  recommended_actions: string[];
  time_to_impact_weeks: number;
}

interface CascadeResult {
  simulation_id: string;
  trigger_type: string;
  trigger_description: string;
  severity: string;
  overall_risk_score: number;
  overall_risk_level: string;
  executive_summary: string;
  domain_impacts: DomainImpact[];
  cascade_sequence: string[];
  recommended_priorities: string[];
  estimated_recovery_weeks: number;
}

interface CascadeRequest {
  trigger_type: string;
  trigger_description: string;
  severity: string;
  monthly_burn_rate?: number;
  monthly_revenue?: number;
  cash_runway_months?: number;
  headcount?: number;
  company_name?: string;
  reporting_period?: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const TRIGGER_TYPES = [
  {
    key: "cash_crisis",
    label: "Nakit Krizi",
    icon: DollarSign,
    color: "text-red-400",
    bg: "bg-red-950/20 border-red-800/40",
    desc: "Nakit rezervleri kritik seviyeye düşerse ne olur?",
  },
  {
    key: "revenue_drop",
    label: "Gelir Düşüşü",
    icon: TrendingDown,
    color: "text-orange-400",
    bg: "bg-orange-950/20 border-orange-800/40",
    desc: "Gelirde ani düşüş yaşanırsa tüm departmanlar nasıl etkilenir?",
  },
  {
    key: "key_person_loss",
    label: "Kilit Kişi Kaybı",
    icon: Users,
    color: "text-amber-400",
    bg: "bg-amber-950/20 border-amber-800/40",
    desc: "CTO, CPO veya kritik bir yönetici ayrılırsa?",
  },
  {
    key: "cyber_incident",
    label: "Siber Saldırı",
    icon: Shield,
    color: "text-purple-400",
    bg: "bg-purple-950/20 border-purple-800/40",
    desc: "Veri ihlali veya ransomware saldırısı yaşanırsa?",
  },
  {
    key: "custom",
    label: "Özel Senaryo",
    icon: Zap,
    color: "text-blue-400",
    bg: "bg-blue-950/20 border-blue-800/40",
    desc: "Kendi senaryonuzu tanımlayın",
  },
];

const SEVERITY_LEVELS = [
  { key: "low",      label: "Düşük",     color: "text-blue-400",   ring: "ring-blue-500/40" },
  { key: "medium",   label: "Orta",      color: "text-yellow-400", ring: "ring-yellow-500/40" },
  { key: "high",     label: "Yüksek",    color: "text-orange-400", ring: "ring-orange-500/40" },
  { key: "critical", label: "Kritik",    color: "text-red-400",    ring: "ring-red-500/40" },
];

const DOMAIN_ICONS: Record<string, { icon: typeof DollarSign; color: string }> = {
  "CFO / Finance":     { icon: DollarSign, color: "text-emerald-400" },
  "CHRO / People":     { icon: Users,      color: "text-pink-400" },
  "CTO / Technology":  { icon: Cpu,        color: "text-blue-400" },
  "CMO / Marketing":   { icon: Megaphone,  color: "text-purple-400" },
  "COO / Operations":  { icon: Layers,     color: "text-orange-400" },
  "Risk / Compliance": { icon: Shield,     color: "text-red-400" },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function impactColors(level: string) {
  switch (level) {
    case "critical": return { bg: "bg-red-950/30 border-red-700/40",    badge: "bg-red-500/20 text-red-400",    bar: "bg-red-500" };
    case "high":     return { bg: "bg-orange-950/20 border-orange-700/30", badge: "bg-orange-500/20 text-orange-400", bar: "bg-orange-500" };
    case "medium":   return { bg: "bg-amber-950/20 border-amber-700/30",  badge: "bg-amber-500/20 text-amber-400",  bar: "bg-amber-500" };
    case "low":      return { bg: "bg-blue-950/10 border-blue-700/20",    badge: "bg-blue-500/20 text-blue-400",    bar: "bg-blue-500" };
    default:         return { bg: "bg-muted/20 border-border",             badge: "bg-muted text-muted-foreground",  bar: "bg-muted" };
  }
}

function overallRiskColor(level: string) {
  switch (level) {
    case "critical": return "text-red-400";
    case "high":     return "text-orange-400";
    case "medium":   return "text-amber-400";
    case "low":      return "text-blue-400";
    default:         return "text-muted-foreground";
  }
}

// ── API ───────────────────────────────────────────────────────────────────────

async function runCascade(req: CascadeRequest): Promise<CascadeResult> {
  const res = await apiClient.post<{ data: CascadeResult; error: string | null }>(
    "/risk/cascade",
    req
  );
  if (res.data.error) throw new Error(res.data.error);
  return res.data.data;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function DomainImpactCard({ impact }: { impact: DomainImpact }) {
  const [expanded, setExpanded] = useState(false);
  const colors = impactColors(impact.impact_level);
  const meta = DOMAIN_ICONS[impact.domain] ?? { icon: BarChart3, color: "text-muted-foreground" };
  const Icon = meta.icon;

  return (
    <div className={cn("rounded-lg border p-4 transition-colors", colors.bg)}>
      {/* Header */}
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <Icon className={cn("h-5 w-5 shrink-0", meta.color)} aria-hidden="true" />
          <span className="font-semibold text-sm">{impact.domain}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={cn("rounded px-2 py-0.5 text-[10px] font-semibold uppercase", colors.badge)}>
            {impact.impact_level}
          </span>
          <span className="text-lg font-bold tabular-nums">{impact.impact_score}</span>
        </div>
      </div>

      {/* Score bar */}
      <div className="mb-3 h-1.5 w-full overflow-hidden rounded-full bg-muted/30">
        <div
          className={cn("h-full rounded-full transition-all duration-700", colors.bar)}
          style={{ width: `${impact.impact_score}%` }}
          aria-label={`Impact score: ${impact.impact_score}/100`}
        />
      </div>

      {/* Primary effect */}
      <p className="text-sm text-foreground mb-2">{impact.primary_effect}</p>

      {/* Time to impact */}
      <div className="mb-3 flex items-center gap-1.5 text-xs text-muted-foreground">
        <Clock className="h-3 w-3" aria-hidden="true" />
        <span>{impact.time_to_impact_weeks} hafta içinde etki</span>
      </div>

      {/* Expand/collapse */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        aria-expanded={expanded}
      >
        <ChevronRight className={cn("h-3 w-3 transition-transform", expanded && "rotate-90")} aria-hidden="true" />
        {expanded ? "Gizle" : "Detaylar & Aksiyonlar"}
      </button>

      {expanded && (
        <div className="mt-3 space-y-3">
          {impact.secondary_effects.length > 0 && (
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                İkincil Etkiler
              </p>
              <ul className="space-y-1">
                {impact.secondary_effects.map((e, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-xs text-muted-foreground">
                    <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" aria-hidden="true" />
                    {e}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {impact.recommended_actions.length > 0 && (
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Önerilen Aksiyonlar
              </p>
              <ul className="space-y-1">
                {impact.recommended_actions.map((a, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-xs">
                    <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 text-[9px] font-bold text-emerald-400">
                      {i + 1}
                    </span>
                    {a}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function CascadeSimulatorPage() {
  const [triggerType, setTriggerType] = useState("cash_crisis");
  const [triggerDesc, setTriggerDesc] = useState("");
  const [severity, setSeverity] = useState("high");
  const [burnRate, setBurnRate] = useState("");
  const [revenue, setRevenue] = useState("");
  const [runway, setRunway] = useState("");
  const [headcount, setHeadcount] = useState("");

  // Pre-fill from CompanyContext if available
  const { data: ctx } = useFullContext();
  const companyName = ctx?.company_name ?? undefined;

  const mutation = useMutation({
    mutationFn: runCascade,
  });

  const result = mutation.data;
  const isLoading = mutation.isPending;

  function handleRun() {
    const trigger = TRIGGER_TYPES.find((t) => t.key === triggerType);
    mutation.mutate({
      trigger_type: triggerType,
      trigger_description: triggerDesc || trigger?.desc || triggerType,
      severity,
      monthly_burn_rate: burnRate ? parseFloat(burnRate) : undefined,
      monthly_revenue:   revenue  ? parseFloat(revenue)  : undefined,
      cash_runway_months: runway  ? parseFloat(runway)   : undefined,
      headcount:          headcount ? parseInt(headcount) : undefined,
      company_name:       companyName,
    });
  }

  const selectedTrigger = TRIGGER_TYPES.find((t) => t.key === triggerType);

  return (
    <main className="mx-auto max-w-screen-xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="rounded-lg bg-red-500/10 p-2">
          <Zap className="h-6 w-6 text-red-400" aria-hidden="true" />
        </div>
        <div>
          <h1 className="text-xl font-bold">Cascade Risk Simulator</h1>
          <p className="text-sm text-muted-foreground">
            "Ne olursa ne olur?" — Bir tetikleyici olay tüm departmanları nasıl etkiler?
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left — Config panel */}
        <div className="space-y-5 lg:col-span-1">
          {/* Trigger type */}
          <div className="rounded-lg border border-border bg-card p-4">
            <h2 className="mb-3 text-sm font-semibold">Tetikleyici Senaryo</h2>
            <div className="space-y-2">
              {TRIGGER_TYPES.map((t) => {
                const Icon = t.icon;
                const selected = triggerType === t.key;
                return (
                  <button
                    key={t.key}
                    type="button"
                    onClick={() => setTriggerType(t.key)}
                    className={cn(
                      "flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      selected ? cn("border-primary/50 bg-primary/5", t.bg) : "border-border hover:bg-muted/30"
                    )}
                  >
                    <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", t.color)} aria-hidden="true" />
                    <div className="min-w-0">
                      <p className="text-sm font-medium">{t.label}</p>
                      <p className="text-[10px] text-muted-foreground leading-snug">{t.desc}</p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Severity */}
          <div className="rounded-lg border border-border bg-card p-4">
            <h2 className="mb-3 text-sm font-semibold">Şiddet Seviyesi</h2>
            <div className="grid grid-cols-2 gap-2">
              {SEVERITY_LEVELS.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => setSeverity(s.key)}
                  className={cn(
                    "rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    severity === s.key
                      ? cn("ring-2", s.ring, "border-transparent bg-card", s.color)
                      : "border-border text-muted-foreground hover:bg-muted/30"
                  )}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          {/* Financial context */}
          <div className="rounded-lg border border-border bg-card p-4">
            <h2 className="mb-3 text-sm font-semibold">Finansal Bağlam (İsteğe Bağlı)</h2>
            <p className="mb-3 text-[10px] text-muted-foreground">
              Bu değerleri girerek simülasyonu daha gerçekçi yapın.
            </p>
            <div className="space-y-3">
              {[
                { id: "burn", label: "Aylık Burn Rate (TRY)", value: burnRate, set: setBurnRate, placeholder: "1000000" },
                { id: "rev",  label: "Aylık Gelir (TRY)",    value: revenue,  set: setRevenue,  placeholder: "2000000" },
                { id: "run",  label: "Cash Runway (ay)",      value: runway,   set: setRunway,   placeholder: "6" },
                { id: "hc",   label: "Çalışan Sayısı",        value: headcount,set: setHeadcount,placeholder: "50" },
              ].map(({ id, label, value, set, placeholder }) => (
                <div key={id}>
                  <label htmlFor={id} className="mb-1 block text-[10px] font-medium text-muted-foreground">
                    {label}
                  </label>
                  <input
                    id={id}
                    type="number"
                    value={value}
                    onChange={(e) => set(e.target.value)}
                    placeholder={placeholder}
                    className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Custom description */}
          {triggerType === "custom" && (
            <div className="rounded-lg border border-border bg-card p-4">
              <label htmlFor="custom-desc" className="mb-2 block text-sm font-semibold">
                Senaryo Açıklaması
              </label>
              <textarea
                id="custom-desc"
                value={triggerDesc}
                onChange={(e) => setTriggerDesc(e.target.value)}
                placeholder="Örn: Ana tedarikçimiz iflas etti ve 3 ay stok yok..."
                rows={3}
                className="w-full rounded border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring resize-none"
              />
            </div>
          )}

          {/* Run button */}
          <button
            type="button"
            onClick={handleRun}
            disabled={isLoading}
            className={cn(
              "flex w-full items-center justify-center gap-2 rounded-lg px-5 py-3 text-sm font-semibold transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "bg-red-500 text-white hover:bg-red-600 disabled:opacity-50"
            )}
          >
            {isLoading ? (
              <><RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />Simüle ediliyor…</>
            ) : (
              <><Play className="h-4 w-4" aria-hidden="true" />Simülasyonu Çalıştır</>
            )}
          </button>

          {mutation.isError && (
            <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
              Hata: {(mutation.error as Error)?.message ?? "Simülasyon başarısız"}
            </div>
          )}
        </div>

        {/* Right — Results */}
        <div className="space-y-6 lg:col-span-2">
          {!result && !isLoading && (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-20 text-center">
              <div className="mb-4 rounded-full bg-muted p-4">
                <Zap className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
              </div>
              <h3 className="text-base font-semibold">Simülasyon Hazır</h3>
              <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                Sol panelden bir senaryo ve şiddet seviyesi seçin, ardından "Simülasyonu Çalıştır" butonuna basın.
              </p>
            </div>
          )}

          {isLoading && (
            <div className="flex flex-col items-center justify-center rounded-lg border border-border bg-card py-20 text-center">
              <RefreshCw className="mb-4 h-8 w-8 animate-spin text-primary" aria-hidden="true" />
              <p className="text-sm font-medium">Etki hesaplanıyor…</p>
              <p className="mt-1 text-xs text-muted-foreground">Tüm domainlere zincirleme etkiler analiz ediliyor</p>
            </div>
          )}

          {result && !isLoading && (
            <>
              {/* Summary card */}
              <div className="rounded-lg border border-border bg-card p-5">
                <div className="mb-4 flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        Simülasyon #{result.simulation_id}
                      </span>
                    </div>
                    <h2 className="text-lg font-bold">{selectedTrigger?.label ?? result.trigger_type}</h2>
                    <p className="text-sm text-muted-foreground mt-0.5">{result.trigger_description}</p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className={cn("text-3xl font-bold tabular-nums", overallRiskColor(result.overall_risk_level))}>
                      {result.overall_risk_score}
                    </p>
                    <p className={cn("text-xs font-semibold uppercase", overallRiskColor(result.overall_risk_level))}>
                      {result.overall_risk_level} risk
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      ~{result.estimated_recovery_weeks} hafta kurtarma
                    </p>
                  </div>
                </div>

                <p className="rounded-md border border-border bg-muted/20 px-4 py-3 text-sm text-foreground leading-relaxed">
                  {result.executive_summary}
                </p>

                {/* Priorities */}
                {result.recommended_priorities.length > 0 && (
                  <div className="mt-4">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Acil Öncelikler
                    </p>
                    <div className="space-y-1.5">
                      {result.recommended_priorities.map((p, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-500/20 text-[10px] font-bold text-red-400">
                            {i + 1}
                          </span>
                          <span>{p}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Cascade sequence */}
              {result.cascade_sequence.length > 0 && (
                <div className="rounded-lg border border-border bg-card p-4">
                  <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
                    <ArrowRight className="h-4 w-4 text-primary" aria-hidden="true" />
                    Zincirleme Etki Akışı
                  </h3>
                  <div className="space-y-2">
                    {result.cascade_sequence.map((step, i) => (
                      <div key={i} className="flex items-start gap-3">
                        <div className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary">
                          {i + 1}
                        </div>
                        <p className="text-sm text-muted-foreground leading-snug">{step}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Domain impact grid */}
              <div>
                <h3 className="mb-3 text-sm font-semibold">Domain Etki Analizi</h3>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {result.domain_impacts.map((impact) => (
                    <DomainImpactCard key={impact.domain} impact={impact} />
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
