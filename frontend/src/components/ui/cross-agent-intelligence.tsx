"use client";
/**
 * CrossAgentIntelligence — "Tüm agentlar birlikte ne söylüyor?"
 *
 * Reads CompanyContext and surfaces cross-domain correlations:
 *   - CFO cash crisis + CHRO high attrition + CTO low velocity = "talent-cash cascade"
 *   - CMO rising CAC + CFO shrinking margins = "growth efficiency crisis"
 *   - Risk open items + Audit coverage gaps = "regulatory exposure"
 *
 * Shown in Command Center and optionally on any page.
 */

import { useMemo } from "react";
import { AlertTriangle, TrendingDown, Users, Cpu, Megaphone, DollarSign, Shield, Zap, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ContextSummary } from "@/lib/api/context";
import type { CompanyContext } from "@/lib/api/context";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface CrossInsight {
  id: string;
  severity: "critical" | "high" | "medium" | "info";
  title: string;
  description: string;
  domains: string[];
  recommendation: string;
  chatPrompt: string;  // Pre-filled question for agent chat
  metric_ids?: string[];
}

function numMetric(metrics: Record<string, number> | undefined, id: string): number | null {
  if (!metrics || metrics[id] == null) return null;
  const v = Number(metrics[id]);
  return Number.isFinite(v) ? v : null;
}

function detectCrossInsights(
  ctx: CompanyContext,
  semanticMetrics?: Record<string, number>,
): CrossInsight[] {
  const insights: CrossInsight[] = [];

  const cfo  = ctx.last_cfo_result as Record<string, unknown> | null;
  const chro = ctx.last_chro_result as Record<string, unknown> | null;
  const cto  = ctx.last_cto_result  as Record<string, unknown> | null;
  const cmo  = ctx.last_cmo_result  as Record<string, unknown> | null;
  const risk = ctx.last_risk_result as Record<string, unknown> | null;

  const pnl      = (cfo?.pnl      as Record<string, number> | null) ?? null;
  const cashflow = (cfo?.cashflow  as Record<string, number> | null) ?? null;
  const forecast = (cfo?.forecast  as Record<string, unknown> | null) ?? null;

  // ── 1. Talent-Cash Cascade ────────────────────────────────────────────────
  // CFO low cash + CHRO high attrition + CTO low velocity
  const runwayMonths =
    numMetric(semanticMetrics, "finance.runway_months") ??
    ((forecast as Record<string, unknown>)?.scenarios as Record<string, Record<string, number>> | null)?.base?.runway_months ??
    99;
  const attritionRate =
    numMetric(semanticMetrics, "people.attrition_rate") ??
    ((chro?.attrition as Record<string, number> | null)?.annualized_attrition_rate ?? 0);
  const roas = numMetric(semanticMetrics, "growth.overall_roas");
  const ctoScore = (cto?.cto_summary as Record<string, number> | null)?.overall_health_score ?? 10;

  if (runwayMonths < 6 && attritionRate > 0.20 && ctoScore < 6) {
    insights.push({
      id: "talent-cash-cascade",
      severity: "critical",
      title: "Yetenek-Nakit Kaskadı",
      description: `Nakit ${runwayMonths.toFixed(1)} aylık runway, %${(attritionRate*100).toFixed(0)} attrition ve düşük mühendislik hızı aynı anda gerçekleşiyor. Bu üçlü kombinasyon şirket için kritik tehlike işareti.`,
      domains: ["CFO", "CHRO", "CTO"],
      recommendation: "Önce nakit sağlamlaştır (maliyet dondurma), sonra kilit çalışanları tut (retention paketi), ardından hız kurtarma sprinleri başlat.",
      chatPrompt: "Nakit sıkışması, yüksek attrition ve düşük mühendislik hızı aynı anda yaşanıyor. Hangi önlemi önce almalıyım?",
      metric_ids: ["finance.runway_months", "people.attrition_rate", "tech.health_score"].filter(
        (id) => semanticMetrics && id in semanticMetrics
      ),
    });
  }

  // ── 2. Growth Efficiency Crisis ───────────────────────────────────────────
  const grossMargin =
    numMetric(semanticMetrics, "finance.gross_margin") ?? (pnl?.gross_margin ?? 1);
  const netMargin =
    numMetric(semanticMetrics, "finance.net_margin") ?? (pnl?.net_margin ?? 1);
  const cmoScore    = (cmo?.cmo_summary as Record<string, number> | null)?.overall_marketing_score ?? 10;

  if (roas != null && roas < 1.5 && grossMargin < 0.25) {
    insights.push({
      id: "semantic-roas-pressure",
      severity: "high",
      title: "ROAS Under Pressure (semantic)",
      description: `Blended ROAS ${roas.toFixed(2)}x with gross margin ${(grossMargin * 100).toFixed(1)}% — marketing efficiency needs reallocation.`,
      domains: ["CFO", "CMO"],
      recommendation: "Shift spend to proven cohorts; pause sub-1.5x ROAS channels for 30 days.",
      chatPrompt: "ROAS is below 1.5x while margins are thin. Which channel should I cut first?",
      metric_ids: ["growth.overall_roas", "finance.gross_margin"],
    });
  }

  if (grossMargin < 0.20 && cmo && cmoScore < 5) {
    insights.push({
      id: "growth-efficiency-crisis",
      severity: "high",
      title: "Büyüme Verimliliği Krizi",
      description: `Brüt marj %${(grossMargin*100).toFixed(1)} ile düşük seyrederken pazarlama verimliliği de kritik seviyede. Müşteri kazanımı pahalılaşıyor, marjlar eriyiyor.`,
      domains: ["CFO", "CMO"],
      recommendation: "En yüksek ROI pazarlama kanalına odaklan, diğerlerini geçici olarak durdur. Mevcut müşteri genişletmesine öncelik ver.",
      chatPrompt: "Düşük brüt marj ve zayıf pazarlama verimliliği aynı anda var. Büyümeyi nasıl kârlı hale getirebilirim?",
    });
  }

  // ── 3. Regulatory Exposure ────────────────────────────────────────────────
  // Risk + Audit both flagging issues
  const riskScore  = (risk?.risk_summary as Record<string, number> | null)?.overall_risk_score ?? 0;

  if (riskScore > 70 && risk) {
    insights.push({
      id: "regulatory-exposure",
      severity: "high",
      title: "Yüksek Risk Yoğunlaşması",
      description: `Risk skoru ${riskScore}/100 ile kritik eşiğin üzerinde. Bu seviyede açık risk kalemleri, denetim ve uyum maliyetleri dramatik artabilir.`,
      domains: ["Risk"],
      recommendation: "En yüksek öncelikli 3 risk kalemini bu hafta kapatmaya odaklan. Hukuk danışmanını devreye al.",
      chatPrompt: "Risk skorum 70'in üzerinde. En önce hangi risk kalemini kapatmalıyım ve nasıl?",
    });
  }

  // ── 4. Cash Burn Warning ──────────────────────────────────────────────────
  const operatingCF = cashflow?.operating ?? 0;
  if (operatingCF < 0 && runwayMonths < 9) {
    insights.push({
      id: "cash-burn-warning",
      severity: runwayMonths < 3 ? "critical" : "high",
      title: "Nakit Yakma Uyarısı",
      description: `İşletme nakit akışı negatif ve ${runwayMonths.toFixed(1)} aylık runway kaldı. Mevcut hızda büyük bir düzeltme gerekiyor.`,
      domains: ["CFO"],
      recommendation: "Acil nakit planı: En büyük 3 gider kalemini gözden geçir, geciktirilebilir ödemeleri ertele, alacakları hızlandır.",
      chatPrompt: `Nakit ${runwayMonths.toFixed(1)} ayda bitiyor ve nakit akışım negatif. Hemen ne yapmalıyım?`,
    });
  }

  // ── 5. Hiring Freeze Risk ─────────────────────────────────────────────────
  // CFO tight cash + CHRO headcount growth
  const headcount = (chro?.headcount as Record<string, number> | null)?.total_headcount ?? 0;
  if (runwayMonths < 9 && headcount > 0 && chro) {
    insights.push({
      id: "hiring-freeze-signal",
      severity: "medium",
      title: "İşe Alım Dondurma Sinyali",
      description: `${runwayMonths.toFixed(1)} aylık nakit runway ile planlanan işe alımlar riske girebilir. CHRO ve CFO'nun işbirliği gerekiyor.`,
      domains: ["CFO", "CHRO"],
      recommendation: "Kritik pozisyonları önceliklendir. Kritik olmayan işe alımları en az 90 gün ertele.",
      chatPrompt: "Nakit kısıtlı olduğunda hangi pozisyonlara işe almaya devam etmeli, hangilerini durdurmalıyım?",
    });
  }

  // ── 6. Low Margin + High Opex ─────────────────────────────────────────────
  const opexRatio = pnl ? (((pnl.total_opex as number) ?? 0) / ((pnl.revenue as number) ?? 1)) : 0;
  if (netMargin < 0.02 && opexRatio > 0.40) {
    insights.push({
      id: "opex-margin-squeeze",
      severity: "high",
      title: "Faaliyet Gideri Baskısı",
      description: `Net marj %${(netMargin*100).toFixed(1)} iken faaliyet giderleri cironun %${(opexRatio*100).toFixed(0)}'unu oluşturuyor. Kârlılık tehdit altında.`,
      domains: ["CFO"],
      recommendation: "En büyük 3 gider kalemini incele. Her birinde %10-20 tasarruf hedefi koy.",
      chatPrompt: "Net marjım çok düşük, faaliyet giderlerim yüksek. Hangi gider kalemini önce kısmalıyım?",
    });
  }

  // Sort by severity
  const order = { critical: 0, high: 1, medium: 2, info: 3 };
  return insights.sort((a, b) => order[a.severity] - order[b.severity]);
}

// ── Severity styles ───────────────────────────────────────────────────────────

function severityStyle(sev: CrossInsight["severity"]) {
  switch (sev) {
    case "critical": return {
      card: "border-red-700/40 bg-red-950/20",
      badge: "bg-red-500/15 text-red-400 border-red-500/25",
      icon: "text-red-400",
      label: "Kritik",
    };
    case "high": return {
      card: "border-orange-700/30 bg-orange-950/15",
      badge: "bg-orange-500/15 text-orange-400 border-orange-500/25",
      icon: "text-orange-400",
      label: "Yüksek",
    };
    case "medium": return {
      card: "border-amber-700/25 bg-amber-950/10",
      badge: "bg-amber-500/15 text-amber-400 border-amber-500/25",
      icon: "text-amber-400",
      label: "Orta",
    };
    default: return {
      card: "border-blue-700/20 bg-blue-950/10",
      badge: "bg-blue-500/15 text-blue-400 border-blue-500/25",
      icon: "text-blue-400",
      label: "Bilgi",
    };
  }
}

const DOMAIN_ICONS: Record<string, typeof DollarSign> = {
  CFO: DollarSign,
  CHRO: Users,
  CTO: Cpu,
  CMO: Megaphone,
  Risk: Shield,
};

// ── Main component ────────────────────────────────────────────────────────────

interface CrossAgentIntelligenceProps {
  context: CompanyContext;
  semanticMetrics?: Record<string, number>;
  onAskChat?: (prompt: string) => void;
  className?: string;
}

export function CrossAgentIntelligence({
  context,
  semanticMetrics,
  onAskChat,
  className,
}: CrossAgentIntelligenceProps) {
  const insights = useMemo(
    () => detectCrossInsights(context, semanticMetrics),
    [context, semanticMetrics]
  );

  if (insights.length === 0) {
    return (
      <div className={cn("rounded-lg border border-dashed border-border bg-muted/10 px-4 py-6 text-center", className)}>
        <Zap className="mx-auto mb-2 h-6 w-6 text-muted-foreground/30" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">
          Cross-domain korelasyon tespit edilmedi.
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground/60">
          Daha fazla agent analizi tamamlandıkça burada görünür.
        </p>
      </div>
    );
  }

  const criticalCount = insights.filter((i) => i.severity === "critical").length;
  const highCount     = insights.filter((i) => i.severity === "high").length;

  return (
    <div className={cn("space-y-4", className)}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/15">
            <Zap className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
          </div>
          <h3 className="text-sm font-semibold">Cross-Domain İstihbarat</h3>
          {criticalCount > 0 && (
            <span className="animate-bounce-subtle rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] font-semibold text-red-400">
              {criticalCount} kritik
            </span>
          )}
        </div>
        <span className="text-xs text-muted-foreground">{insights.length} korelasyon tespit edildi</span>
      </div>

      {/* Insight cards */}
      <div className="space-y-3">
        {insights.map((insight, i) => {
          const style = severityStyle(insight.severity);

          return (
            <div
              key={insight.id}
              className={cn(
                "rounded-lg border p-4 space-y-3",
                style.card,
                "animate-slide-up"
              )}
              style={{ animationDelay: `${i * 50}ms` }}
            >
              {/* Header row */}
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-2.5 flex-1 min-w-0">
                  <AlertTriangle className={cn("mt-0.5 h-4 w-4 shrink-0", style.icon)} aria-hidden="true" />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                      <span className="text-sm font-semibold">{insight.title}</span>
                      <span className={cn("rounded border px-1.5 py-0.5 text-[10px] font-semibold", style.badge)}>
                        {style.label}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground leading-relaxed">{insight.description}</p>
                  </div>
                </div>
              </div>

              {/* Domain badges */}
              <div className="flex flex-wrap gap-1.5">
                {insight.domains.map((domain) => {
                  const Icon = DOMAIN_ICONS[domain];
                  return (
                    <span
                      key={domain}
                      className="flex items-center gap-1 rounded-md bg-muted/50 px-2 py-0.5 text-[10px] font-medium text-muted-foreground"
                    >
                      {Icon && <Icon className="h-3 w-3" aria-hidden="true" />}
                      {domain}
                    </span>
                  );
                })}
                {(insight.metric_ids ?? []).map((mid) => (
                  <span
                    key={mid}
                    className="rounded-md bg-primary/10 px-2 py-0.5 font-mono text-[10px] text-primary"
                  >
                    {mid}
                  </span>
                ))}
              </div>

              {/* Recommendation */}
              <div className="rounded-md bg-muted/20 px-3 py-2">
                <p className="text-xs text-foreground">
                  <span className="font-semibold text-primary">→ Öneri: </span>
                  {insight.recommendation}
                </p>
              </div>

              {/* Ask AI */}
              {onAskChat && (
                <button
                  onClick={() => onAskChat(insight.chatPrompt)}
                  className={cn(
                    "flex items-center gap-1.5 text-[11px] text-muted-foreground",
                    "hover:text-primary transition-state"
                  )}
                >
                  <MessageSquare className="h-3 w-3" aria-hidden="true" />
                  AI ile bu konuyu derinlemesine incele
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
