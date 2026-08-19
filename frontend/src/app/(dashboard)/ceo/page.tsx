"use client";

export const dynamic = "force-dynamic";

import { useState } from "react";
import { BarChart3, Download, ShieldAlert, TrendingUp, Users, Cpu } from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { BoardDeckViewer }     from "@/components/ceo/BoardDeckViewer";
import { OKRWeightedScorecard } from "@/components/ceo/OKRScorecard";
import { OutlookChart }         from "@/components/ceo/OutlookChart";
import { SWOTWidget }           from "@/components/ceo/SWOTWidget";
import { type CEOResult, type BoardSlide, type OKRObjective } from "@/components/ceo/types";
import { useCompanyContextStore } from "@/store/companyContext";

// ── Sample data ────────────────────────────────────────────────────────────────

const SAMPLE_BOARD_DECK: BoardSlide[] = [
  { slide_number: 1, title: "Executive Summary",    content: "H1 2024 sağlam finansal performans gösterdi. Revenue +18% YoY, EBITDA marjı 25%.",         metrics: { revenue: 45.2, ebitda_margin: 0.25, growth: 0.18 } },
  { slide_number: 2, title: "Financial Performance", content: "Üç ana segment tümü beklentileri aştı. Operasyonel verimlilik %12 iyileşti.",              metrics: { segment_1: 18.5, segment_2: 12.3, segment_3: 14.4 } },
  { slide_number: 3, title: "Market Expansion",      content: "Yeni pazarlara giriş başarılı. Müşteri tabanı %35 genişledi.",                              metrics: { new_markets: 3, customer_growth: 0.35, market_share: 0.062 } },
  { slide_number: 4, title: "Risk Assessment",       content: "Önemli riskler kontrol altında. Siber güvenlik altyapısı güçlendirildi.",                   metrics: { risk_score: 0.45, compliance_rate: 0.98, audit_score: 0.92 } },
  { slide_number: 5, title: "Strategic Priorities",  content: "2025 stratejisi: Dijital transformasyon, ESG uyumu, jeopolitik çeşitlendirme.",              metrics: { digital_investment: 0.35, esg_score: 0.78, diversification: 0.62 } },
  { slide_number: 6, title: "Outlook & Guidance",    content: "2024 Full Year: Revenue $185-195M. 2025 Growth: 15-18% midpoint.",                          metrics: { fy2024_revenue: 190, fy2025_growth: 0.165, confidence: 0.88 } },
];

const SAMPLE_OKRS: OKRObjective[] = [
  { objective_id: "O1", name: "Revenue Growth & Profitability", weight: 0.30, score: 0.92, momentum: "up",     key_results: [{ name: "Revenue +20% YoY", progress: 0.95 }, { name: "EBITDA Margin 26%", progress: 0.88 }] },
  { objective_id: "O2", name: "Customer Satisfaction",          weight: 0.25, score: 0.78, momentum: "stable", key_results: [{ name: "NPS Score 60+", progress: 0.82 }, { name: "Churn Rate <5%", progress: 0.75 }] },
  { objective_id: "O3", name: "Digital Transformation",         weight: 0.25, score: 0.65, momentum: "up",     key_results: [{ name: "Cloud Migration 80%", progress: 0.60 }, { name: "Automation ROI $5M", progress: 0.70 }] },
  { objective_id: "O4", name: "Team Excellence & Retention",    weight: 0.20, score: 0.82, momentum: "down",   key_results: [{ name: "Employee Engagement 75%", progress: 0.85 }, { name: "Turnover <12%", progress: 0.79 }] },
];

// ── PDF export ─────────────────────────────────────────────────────────────────
// Uses /advanced/board-deck-pdf which reads from CompanyContext directly —
// richer output than /ceo/export-pdf (includes all agent results).

function PDFExportButtons({
  jobId,
  orgId,
}: {
  jobId?: string | null;
  orgId?: string | null;
}) {
  const [exporting, setExporting] = useState<"deck" | "one-pager" | null>(null);

  async function handleExport(type: "deck" | "one-pager") {
    setExporting(type);
    try {
      const res = await apiClient.post(
        "/advanced/board-deck-pdf",
        {
          job_id:  jobId  ?? null,
          org_id_param: orgId ?? null,
        },
        { responseType: "blob" }
      );
      const blob = res.data as Blob;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${type === "deck" ? "board-deck" : "one-pager"}-${new Date().toISOString().split("T")[0]}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      if (process.env.NODE_ENV === "development") {
        console.error("Board deck PDF export failed:", err);
      }
    } finally {
      setExporting(null);
    }
  }

  return (
    <div className="flex gap-2">
      <Button
        variant="default"
        size="sm"
        disabled={exporting !== null}
        onClick={() => handleExport("deck")}
        aria-label="Board deck PDF indir"
      >
        <Download className="h-4 w-4" aria-hidden="true" />
        {exporting === "deck" ? "İndiriliyor…" : "Board Deck PDF"}
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={exporting !== null}
        onClick={() => handleExport("one-pager")}
        aria-label="One-pager PDF indir"
      >
        <Download className="h-4 w-4" aria-hidden="true" />
        {exporting === "one-pager" ? "İndiriliyor…" : "One-Pager PDF"}
      </Button>
    </div>
  );
}

// ── Cross-Risk Timeline ────────────────────────────────────────────────────────

interface CrossRisk {
  domain:    string;
  risk_type: string;
  severity:  string;
  description: string;
}

function CrossRiskTimeline({ risks }: { risks: CrossRisk[] }) {
  if (!risks.length) return null;

  const domainIcon = (d: string) => {
    switch (d) {
      case "finance": return <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />;
      case "tech":    return <Cpu className="h-3.5 w-3.5 text-cyan-400" />;
      case "hr":      return <Users className="h-3.5 w-3.5 text-purple-400" />;
      default:        return <ShieldAlert className="h-3.5 w-3.5 text-orange-400" />;
    }
  };

  const severityColor = (s: string) =>
    s === "critical" ? "border-red-500/30 bg-red-500/5" :
    s === "high"     ? "border-orange-500/30 bg-orange-500/5" :
    s === "medium"   ? "border-yellow-500/30 bg-yellow-500/5" :
                       "border-border bg-muted/20";

  const severityBadge = (s: string) =>
    s === "critical" ? "bg-red-500/20 text-red-400" :
    s === "high"     ? "bg-orange-500/20 text-orange-400" :
    s === "medium"   ? "bg-yellow-500/20 text-yellow-400" :
                       "bg-muted text-muted-foreground";

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center gap-2">
        <ShieldAlert className="h-4 w-4 text-orange-400" />
        <h3 className="font-semibold text-sm">Cross-Domain Risk Timeline</h3>
        <span className="rounded-full bg-orange-500/10 border border-orange-500/20 px-1.5 py-0.5 text-[10px] text-orange-400 font-medium">
          {risks.length} risk
        </span>
      </div>

      <div className="relative space-y-2 pl-4">
        {/* Vertical timeline line */}
        <div className="absolute left-[7px] top-2 bottom-2 w-px bg-border" />

        {risks.map((risk, i) => (
          <div key={i} className={cn("relative rounded-lg border p-2.5 pl-3", severityColor(risk.severity))}>
            {/* Timeline dot */}
            <div className={cn(
              "absolute -left-[17px] top-3 h-2.5 w-2.5 rounded-full border-2 border-background",
              risk.severity === "critical" ? "bg-red-400" :
              risk.severity === "high"     ? "bg-orange-400" :
              risk.severity === "medium"   ? "bg-yellow-400" : "bg-muted-foreground"
            )} />

            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-1.5 min-w-0">
                {domainIcon(risk.domain)}
                <p className="text-xs font-medium truncate capitalize">{risk.domain}</p>
                <span className={cn("rounded px-1 py-0.5 text-[9px] font-medium uppercase tracking-wide", severityBadge(risk.severity))}>
                  {risk.severity}
                </span>
              </div>
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground leading-relaxed">{risk.description}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function CEODashboardPage() {
  const { activeCFOJobId, orgId } = useCompanyContextStore();
  const [company, setCompany] = useState("");
  const [period,  setPeriod]  = useState("");
  const [loading, setLoading] = useState(false);
  const [result,  setResult]  = useState<CEOResult | null>(null);
  const [error,   setError]   = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<CEOResult>("/ceo/analyze", {
        company_name: company || null,
        period:       period  || null,
        transactions: [{ date: "2024-01-01", amount: 100000, category: "Revenue", type: "income" }],
      });
      if (res.data.error) throw new Error(res.data.error);
      setResult(res.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Bilinmeyen hata");
    } finally {
      setLoading(false);
    }
  }

  const display = result ?? {
    board_deck: SAMPLE_BOARD_DECK,
    okr_status: { company_score: 0.83, objectives: SAMPLE_OKRS },
    outlook: {
      base_case:   [100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 120, 122],
      optimistic:  [100, 105, 110, 115, 120, 125, 130, 135, 140, 145, 150, 155],
      pessimistic: [100,  99,  98,  97,  96,  95,  94,  93,  92,  91,  90,  89],
    },
  };

  return (
    <main className="mx-auto max-w-screen-2xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <BarChart3 className="h-6 w-6 text-primary" aria-hidden="true" />
        <div>
          <h1 className="text-2xl font-bold">CEO Yönetim Panosu</h1>
          <p className="text-sm text-muted-foreground">
            Board deck, OKR puan kartı ve 12 aylık outlook
          </p>
        </div>
      </div>

      {/* Input form */}
      <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-card p-4 sm:p-6">
        <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="ceo-company">Şirket Adı</Label>
            <Input
              id="ceo-company"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="Acme Corp"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ceo-period">Dönem</Label>
            <Input
              id="ceo-period"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="2024-H1"
            />
          </div>
        </div>

        {error && (
          <p role="alert" className="mb-3 rounded border border-red-400/30 bg-red-400/10 px-3 py-2 text-xs text-red-400">
            {error}
          </p>
        )}

        <Separator className="mb-4" />

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={loading}>
            {loading ? "Yükleniyor…" : "CEO Analizi Çalıştır"}
          </Button>
          {display.board_deck && (
            <PDFExportButtons
              jobId={activeCFOJobId ?? null}
              orgId={orgId ?? null}
            />
          )}
        </div>
      </form>

      {/* Results */}
      <div className="space-y-6">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            {display.board_deck && <BoardDeckViewer slides={display.board_deck} />}
          </div>
          {display.okr_status && (
            <OKRWeightedScorecard
              objectives={display.okr_status.objectives}
              companyScore={display.okr_status.company_score}
            />
          )}
        </div>

        {display.outlook && <OutlookChart outlook={display.outlook} />}

        {/* SWOT + Cross-Risk row */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <SWOTWidget
            data={(result as CEOResult & { swot?: { strengths: string[]; weaknesses: string[]; opportunities: string[]; threats: string[]; strategic_priorities?: string[] } })?.swot ?? null}
            jobId={activeCFOJobId}
            orgId={orgId}
          />
          <CrossRiskTimeline
            risks={(result as CEOResult & { cross_risks?: CrossRisk[] })?.cross_risks ?? [
              { domain: "finance",    risk_type: "liquidity",  severity: "high",   description: "Nakit pisti 4 ayın altında — opex kısıtı değerlendirin" },
              { domain: "tech",       risk_type: "debt",       severity: "medium", description: "Tech debt birikimi sprint hızını yavaşlatıyor" },
              { domain: "hr",         risk_type: "retention",  severity: "high",   description: "3 kilit pozisyonda ayrılma riski tespit edildi" },
              { domain: "compliance", risk_type: "regulatory", severity: "medium", description: "KVKK VERBİS kaydı yenileme tarihi yaklaşıyor" },
            ]}
          />
        </div>

        {result?.error && (
          <div role="alert" className="rounded border border-red-400/30 bg-red-400/10 p-3 text-xs text-red-400">
            Hata: {result.error}
          </div>
        )}
      </div>
    </main>
  );
}
