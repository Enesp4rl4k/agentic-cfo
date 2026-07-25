"use client";

export const dynamic = "force-dynamic";

import { useState, useMemo } from "react";
import {
  TrendingUp, Download, BarChart3, Target, Zap, ChevronLeft, ChevronRight,
  FileText, ChevronDown,
} from "lucide-react";
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ComposedChart, Bar,
} from "recharts";
import { apiClient } from "@/lib/api/client";
import { formatPercent, formatNumber } from "@/lib/dashboard-utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface BoardSlide {
  slide_number: number;
  title: string;
  content: string;
  metrics?: Record<string, number>;
}

interface OKRObjective {
  objective_id: string;
  name: string;
  weight: number; // 0-1
  score: number; // 0-1
  momentum: "up" | "down" | "stable";
  key_results: Array<{ name: string; progress: number }>;
}

interface CEOResult {
  job_id: string;
  board_deck?: BoardSlide[];
  okr_status?: {
    company_score: number; // 0-1
    objectives: OKRObjective[];
  };
  financial_summary?: Record<string, any>;
  outlook?: {
    base_case: number[];
    optimistic: number[];
    pessimistic: number[];
  };
  error: string | null;
}

// ── Sample Data ───────────────────────────────────────────────────────────────

const SAMPLE_BOARD_DECK: BoardSlide[] = [
  {
    slide_number: 1,
    title: "Executive Summary",
    content: "H1 2024 sağlam finansal performans gösterdi. Revenue +18% YoY, EBITDA marjı 25%.",
    metrics: { revenue: 45.2, ebitda_margin: 0.25, growth: 0.18 },
  },
  {
    slide_number: 2,
    title: "Financial Performance",
    content: "Üç ana segment tümü beklentileri aştı. Operasyonel verimlilik %12 iyileşti.",
    metrics: { segment_1: 18.5, segment_2: 12.3, segment_3: 14.4 },
  },
  {
    slide_number: 3,
    title: "Market Expansion",
    content: "Yeni pazarlara giriş başarılı. Müşteri tabanı %35 genişledi.",
    metrics: { new_markets: 3, customer_growth: 0.35, market_share: 0.062 },
  },
  {
    slide_number: 4,
    title: "Risk Assessment",
    content: "Önemli riskler kontrol altında. Siber güvenlik altyapısı güçlendirildi.",
    metrics: { risk_score: 0.45, compliance_rate: 0.98, audit_score: 0.92 },
  },
  {
    slide_number: 5,
    title: "Strategic Priorities",
    content: "2025 stratejisi: Dijital transformasyon, ESG uyumu, jeopolitik çeşitlendirme.",
    metrics: { digital_investment: 0.35, esg_score: 0.78, diversification: 0.62 },
  },
  {
    slide_number: 6,
    title: "Outlook & Guidance",
    content: "2024 Full Year: Revenue $185-195M. 2025 Growth: 15-18% midpoint.",
    metrics: { fy2024_revenue: 190, fy2025_growth: 0.165, confidence: 0.88 },
  },
];

const SAMPLE_OKRS: OKRObjective[] = [
  {
    objective_id: "O1",
    name: "Revenue Growth & Profitability",
    weight: 0.30,
    score: 0.92,
    momentum: "up",
    key_results: [
      { name: "Revenue +20% YoY", progress: 0.95 },
      { name: "EBITDA Margin 26%", progress: 0.88 },
    ],
  },
  {
    objective_id: "O2",
    name: "Customer Satisfaction",
    weight: 0.25,
    score: 0.78,
    momentum: "stable",
    key_results: [
      { name: "NPS Score 60+", progress: 0.82 },
      { name: "Churn Rate <5%", progress: 0.75 },
    ],
  },
  {
    objective_id: "O3",
    name: "Digital Transformation",
    weight: 0.25,
    score: 0.65,
    momentum: "up",
    key_results: [
      { name: "Cloud Migration 80%", progress: 0.60 },
      { name: "Automation ROI $5M", progress: 0.70 },
    ],
  },
  {
    objective_id: "O4",
    name: "Team Excellence & Retention",
    weight: 0.20,
    score: 0.82,
    momentum: "down",
    key_results: [
      { name: "Employee Engagement 75%", progress: 0.85 },
      { name: "Turnover <12%", progress: 0.79 },
    ],
  },
];

// ── Helper functions ──────────────────────────────────────────────────────────

function fmt(n: unknown, decimals = 1): string {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  return isNaN(v) ? "—" : v.toFixed(decimals);
}

function getMomentumIcon(momentum: string) {
  switch (momentum) {
    case "up":
      return <TrendingUp className="h-4 w-4 text-green-400" />;
    case "down":
      return <TrendingUp className="h-4 w-4 text-red-400 rotate-180" />;
    default:
      return <div className="h-4 w-4 text-yellow-400">—</div>;
  }
}

function getMomentumColor(momentum: string): string {
  switch (momentum) {
    case "up":
      return "text-green-400";
    case "down":
      return "text-red-400";
    default:
      return "text-yellow-400";
  }
}

// ── Board Deck Viewer ─────────────────────────────────────────────────────────

interface BoardDeckViewerProps {
  slides: BoardSlide[];
}

function BoardDeckViewer({ slides }: BoardDeckViewerProps) {
  const [currentSlide, setCurrentSlide] = useState(0);
  const slide = slides[currentSlide];

  const goNext = () => setCurrentSlide((prev) => (prev + 1) % slides.length);
  const goPrev = () => setCurrentSlide((prev) => (prev - 1 + slides.length) % slides.length);

  if (!slide) return null;

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
        <FileText className="h-4 w-4" />
        Board Deck Viewer
      </h3>

      <div className="mb-4 aspect-video bg-muted rounded flex flex-col justify-between p-6">
        <div>
          <p className="text-xs text-muted-foreground mb-2">Slide {slide.slide_number} / {slides.length}</p>
          <h2 className="text-2xl font-bold mb-2">{slide.title}</h2>
          <p className="text-sm text-muted-foreground">{slide.content}</p>
        </div>

        {slide.metrics && (
          <div className="grid grid-cols-3 gap-2 mt-4">
            {Object.entries(slide.metrics).slice(0, 3).map(([key, value]) => (
              <div key={key} className="rounded bg-background/50 p-2">
                <p className="text-xs text-muted-foreground capitalize">{key.replace(/_/g, " ")}</p>
                <p className="font-semibold">
                  {typeof value === "number" && value < 1 ? formatPercent(value) : fmt(value, 1)}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between">
        <button
          onClick={goPrev}
          className="rounded border border-border p-2 hover:bg-muted"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>

        <div className="flex gap-1">
          {slides.map((_, i) => (
            <button
              key={i}
              onClick={() => setCurrentSlide(i)}
              className={`h-2 rounded-full transition ${
                i === currentSlide ? "bg-primary w-4" : "bg-muted w-2 hover:bg-muted-foreground"
              }`}
            />
          ))}
        </div>

        <button
          onClick={goNext}
          className="rounded border border-border p-2 hover:bg-muted"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// ── OKR Weighted Scorecard ────────────────────────────────────────────────────

interface OKRScorecardProps {
  objectives: OKRObjective[];
  companyScore: number;
}

function OKRWeightedScorecard({ objectives, companyScore }: OKRScorecardProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h3 className="text-sm font-semibold flex items-center gap-2 mb-3">
            <Target className="h-4 w-4" />
            OKR Ağırlıklı Puan Kartı
          </h3>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground mb-1">Şirket Puanı</p>
          <p className="text-3xl font-bold">{fmt(companyScore * 100, 0)}%</p>
        </div>
      </div>

      <div className="space-y-4">
        {objectives.map((obj) => {
          const weightedScore = obj.score * obj.weight;
          return (
            <div key={obj.objective_id} className="rounded border border-border bg-muted/20 p-4">
              <div className="flex items-start justify-between mb-2">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h4 className="font-medium text-sm">{obj.name}</h4>
                    {getMomentumIcon(obj.momentum)}
                  </div>
                  <div className="flex gap-2 text-xs text-muted-foreground">
                    <span>Ağırlık: {formatPercent(obj.weight)}</span>
                    <span>Puan: {fmt(obj.score * 100, 0)}%</span>
                    <span className="font-semibold">Ağ. Puan: {fmt(weightedScore * 100, 0)}%</span>
                  </div>
                </div>
              </div>

              {/* Progress bar */}
              <div className="mb-2 w-full bg-muted rounded h-2 overflow-hidden">
                <div
                  className="h-full rounded bg-gradient-to-r from-blue-500 to-purple-500"
                  style={{ width: `${obj.score * 100}%` }}
                />
              </div>

              {/* Key Results */}
              <div className="space-y-1">
                {obj.key_results.map((kr, idx) => (
                  <div key={idx} className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">{kr.name}</span>
                    <span className="font-medium">{formatPercent(kr.progress)}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Summary */}
      <div className="mt-6 pt-4 border-t border-border">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded bg-muted/30 p-2">
            <p className="text-xs text-muted-foreground mb-1">Ortalama Puan</p>
            <p className="text-lg font-bold">
              {fmt(
                objectives.reduce((sum, o) => sum + o.score, 0) / objectives.length * 100,
                0
              )}%
            </p>
          </div>
          <div className="rounded bg-muted/30 p-2">
            <p className="text-xs text-muted-foreground mb-1">Ağırlıklı Ortalama</p>
            <p className="text-lg font-bold">{fmt(companyScore * 100, 0)}%</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 12-Month Outlook Scenario Bands ───────────────────────────────────────────

interface OutlookChartProps {
  baseCase: number[];
  optimistic: number[];
  pessimistic: number[];
}

function OutlookChart({ baseCase, optimistic, pessimistic }: OutlookChartProps) {
  const months = ["Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara", "Oca", "Şub", "Mar", "Nis", "May", "Haz"];
  const data = months.map((month, i) => ({
    month,
    base: baseCase[i] || 0,
    optimistic: optimistic[i] || 0,
    pessimistic: pessimistic[i] || 0,
  }));

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
        <TrendingUp className="h-4 w-4" />
        12 Aylık Outlook (Senaryo Bantları)
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.1} />
          <XAxis dataKey="month" stroke="currentColor" opacity={0.5} />
          <YAxis stroke="currentColor" opacity={0.5} />
          <Tooltip contentStyle={{ backgroundColor: "transparent", border: "none" }} />
          <Legend />
          <Area
            type="monotone"
            dataKey="optimistic"
            fill="#10b981"
            stroke="#10b981"
            fillOpacity={0.2}
            name="İyimser"
          />
          <Line type="monotone" dataKey="base" stroke="#3b82f6" strokeWidth={2} name="Temel" />
          <Area
            type="monotone"
            dataKey="pessimistic"
            fill="#ef4444"
            stroke="#ef4444"
            fillOpacity={0.2}
            name="Kötümser"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── PDF Export Handler ────────────────────────────────────────────────────────

interface PDFExportProps {
  boardDeck: BoardSlide[];
  okrStatus: any;
}

function PDFExportButtons({ boardDeck, okrStatus }: PDFExportProps) {
  const [exporting, setExporting] = useState(false);

  async function handleExport(type: "deck" | "one-pager") {
    setExporting(true);
    try {
      const res = await apiClient.post(
        "/ceo/export-pdf",
        {
          board_deck: boardDeck,
          okr_status: okrStatus,
        },
        {
          responseType: "blob",
        }
      );

      const url = URL.createObjectURL(res.data as Blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${type === "deck" ? "board-deck" : "one-pager"}-${new Date().toISOString().split("T")[0]}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Export failed:", error);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="flex gap-2">
      <button
        onClick={() => handleExport("deck")}
        disabled={exporting}
        className="flex items-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
      >
        <Download className="h-4 w-4" />
        Board Deck PDF (A4)
      </button>
      <button
        onClick={() => handleExport("one-pager")}
        disabled={exporting}
        className="flex items-center gap-2 rounded border border-border px-4 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50"
      >
        <Download className="h-4 w-4" />
        One-Pager PDF
      </button>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function CEODashboardPage() {
  const [company, setCompany] = useState("");
  const [period, setPeriod] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CEOResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<CEOResult>("/ceo/analyze", {
        company_name: company || null,
        period: period || null,
        transactions: [
          { date: "2024-01-01", amount: 100000, category: "Revenue", type: "income" },
        ],
      });
      if (res.data.error) throw new Error(res.data.error);
      setResult(res.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Bilinmeyen hata");
    } finally {
      setLoading(false);
    }
  }

  // Use sample data for demo
  const displayResult = result || {
    board_deck: SAMPLE_BOARD_DECK,
    okr_status: {
      company_score: 0.83,
      objectives: SAMPLE_OKRS,
    },
    outlook: {
      base_case: [100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 120, 122],
      optimistic: [100, 105, 110, 115, 120, 125, 130, 135, 140, 145, 150, 155],
      pessimistic: [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 89],
    },
  };

  return (
    <main className="mx-auto max-w-screen-2xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <BarChart3 className="h-6 w-6 text-primary" />
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
          <div>
            <label htmlFor="ceo-company" className="mb-1 block text-xs font-medium">
              Şirket Adı
            </label>
            <input
              id="ceo-company"
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="Acme Corp"
              className="w-full rounded border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <div>
            <label htmlFor="ceo-period" className="mb-1 block text-xs font-medium">
              Dönem
            </label>
            <input
              id="ceo-period"
              type="text"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="2024-H1"
              className="w-full rounded border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        </div>

        {error && (
          <p role="alert" className="mb-3 rounded border border-red-400/30 bg-red-400/10 px-3 py-2 text-xs text-red-400">
            {error}
          </p>
        )}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={loading}
            className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            {loading ? "Yükleniyor…" : "CEO Analizi Çalıştır"}
          </button>
          {displayResult && (
            <PDFExportButtons
              boardDeck={displayResult.board_deck || SAMPLE_BOARD_DECK}
              okrStatus={displayResult.okr_status}
            />
          )}
        </div>
      </form>

      {/* Results */}
      {displayResult && (
        <div className="space-y-6">
          {/* Row 1: Board Deck + OKR */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              {displayResult.board_deck && (
                <BoardDeckViewer slides={displayResult.board_deck} />
              )}
            </div>
            {displayResult.okr_status && (
              <div>
                <OKRWeightedScorecard
                  objectives={displayResult.okr_status.objectives}
                  companyScore={displayResult.okr_status.company_score}
                />
              </div>
            )}
          </div>

          {/* Row 2: Outlook Chart */}
          {displayResult.outlook && (
            <OutlookChart
              baseCase={displayResult.outlook.base_case}
              optimistic={displayResult.outlook.optimistic}
              pessimistic={displayResult.outlook.pessimistic}
            />
          )}

          {result?.error && (
            <div role="alert" className="rounded border border-red-400/30 bg-red-400/10 p-3 text-xs text-red-400">
              Hata: {result.error}
            </div>
          )}
        </div>
      )}
    </main>
  );
}
