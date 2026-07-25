"use client";

export const dynamic = "force-dynamic";

import { useState, useMemo } from "react";
import {
  AlertTriangle, Grid3x3, Zap, Shield, Activity, TrendingUp, TrendingDown, Minus,
} from "lucide-react";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell, ReferenceLine,
} from "recharts";
import { apiClient } from "@/lib/api/client";
import { formatCurrency, formatPercent, valueToColor } from "@/lib/dashboard-utils";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface KRIData {
  kri_id: string;
  name: string;
  current_value: number;
  threshold: number;
  variance: number; // 0-1
  trend: string; // "up" | "down" | "stable"
  last_updated: string;
}

interface RiskItem {
  risk_id: string;
  name: string;
  probability: number; // 0-1
  impact: number; // 1-10
  financial_exposure: number;
  urgency: "critical" | "high" | "medium" | "low";
  mitigations: string[];
}

interface RiskResult {
  job_id: string;
  kris: KRIData[] | null;
  risks: RiskItem[] | null;
  correlations: number[][] | null;
  error: string | null;
}

// ── Sample Data ───────────────────────────────────────────────────────────────

const SAMPLE_DATA = {
  kri: `kri_id,name,current_value,threshold,variance,trend
KRI001,Operasyonel Gider Oranı,0.45,0.40,0.15,up
KRI002,Müşteri Kaybı Oranı,0.08,0.05,0.22,up
KRI003,Proje Teslimat Gecikmesi,0.12,0.10,0.18,stable
KRI004,Sistem Kullanılabilirliği,0.985,0.99,0.08,down
KRI005,Veri Yedekleme Başarısı,0.99,0.995,0.12,stable
KRI006,Uyum Denetim Bulgusu,0.25,0.15,0.35,up
KRI007,İnsan Kaynakları Devir,0.18,0.12,0.20,up
KRI008,Borç / EBITDA Oranı,2.5,2.0,0.25,up`,

  risks: `risk_id,name,probability,impact,financial_exposure,urgency
R001,Operasyonel Aksaması,0.35,8,5000000,high
R002,Siber Saldırı,0.20,9,15000000,critical
R003,Düzenleyici Değişiklik,0.40,6,3000000,high
R004,Tedarikçi Başarısızlığı,0.25,7,8000000,high
R005,Pazar Daralması,0.45,5,12000000,medium
R006,Teknoloji Küçülme,0.30,7,6000000,high
R007,Önemli Anahtar Personel Kaybı,0.50,6,4000000,medium
R008,Likidite Krizi,0.15,10,20000000,critical`,
};

// ── Helper functions ──────────────────────────────────────────────────────────

function fmt(n: unknown, decimals = 1): string {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  return isNaN(v) ? "—" : v.toFixed(decimals);
}

function getUrgencyColor(urgency: string): string {
  switch (urgency) {
    case "critical":
      return "#ef4444"; // red
    case "high":
      return "#f97316"; // orange
    case "medium":
      return "#eab308"; // yellow
    default:
      return "#10b981"; // green
  }
}

// ── KRI Gauge card ────────────────────────────────────────────────────────────

function KRIGauge({ kri }: { kri: KRIData }) {
  // Arc gauge: 0° = left, 180° = right (semicircle)
  const r = 28;
  const cx = 36;
  const cy = 36;
  const circumference = Math.PI * r; // half circle
  const pct = Math.min(kri.current_value / (kri.threshold * 1.5), 1);
  const dashOffset = circumference * (1 - pct);

  const overThreshold = kri.current_value > kri.threshold;
  const arcColor = overThreshold
    ? kri.variance > 0.25 ? "#ef4444" : "#f97316"
    : "#10b981";

  const TrendIcon = kri.trend === "up" ? TrendingUp : kri.trend === "down" ? TrendingDown : Minus;
  const trendCls = overThreshold
    ? kri.trend === "up" ? "text-destructive" : "text-emerald-400"
    : kri.trend === "down" ? "text-destructive" : "text-emerald-400";

  return (
    <div className={cn(
      "rounded-lg border bg-card p-3 transition-colors",
      overThreshold ? "border-destructive/30" : "border-border"
    )}>
      {/* Arc gauge */}
      <div className="flex justify-center mb-1">
        <svg width="72" height="44" viewBox="0 0 72 44" aria-hidden="true">
          {/* Background arc */}
          <path
            d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
            fill="none"
            stroke="oklch(0.27 0.018 255)"
            strokeWidth="5"
            strokeLinecap="round"
          />
          {/* Value arc */}
          <path
            d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
            fill="none"
            stroke={arcColor}
            strokeWidth="5"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
          />
          {/* Threshold tick */}
          <line
            x1={cx + r * Math.cos(Math.PI * (1 - kri.threshold / (kri.threshold * 1.5)))}
            y1={cy - r * Math.sin(Math.PI * (1 - kri.threshold / (kri.threshold * 1.5))) + 0}
            x2={cx + (r + 5) * Math.cos(Math.PI * (1 - kri.threshold / (kri.threshold * 1.5)))}
            y2={cy - (r + 5) * Math.sin(Math.PI * (1 - kri.threshold / (kri.threshold * 1.5)))}
            stroke="#eab308"
            strokeWidth="2"
            strokeLinecap="round"
          />
          {/* Center value */}
          <text x={cx} y={cy - 4} textAnchor="middle" fontSize="10" fontWeight="600" fill={arcColor}>
            {fmt(kri.current_value * 100, 0)}%
          </text>
        </svg>
      </div>

      <p className="text-center text-xs font-medium leading-tight truncate" title={kri.name}>
        {kri.name.length > 18 ? kri.name.slice(0, 17) + "…" : kri.name}
      </p>
      <div className="mt-1 flex items-center justify-center gap-1.5 text-xs text-muted-foreground">
        <span>Eşik: {fmt(kri.threshold * 100, 0)}%</span>
        <TrendIcon className={cn("h-3 w-3", trendCls)} aria-hidden="true" />
      </div>
      {overThreshold && (
        <p className="mt-1 text-center text-[10px] font-medium text-destructive">
          Eşik aşıldı
        </p>
      )}
    </div>
  );
}

// ── KRI Gauge grid ────────────────────────────────────────────────────────────

function KRIGaugeGrid({ kris }: { kris: KRIData[] }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Activity className="h-4 w-4" />
        KRI Göstergeler
      </h3>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        {kris.slice(0, 8).map((kri) => (
          <KRIGauge key={kri.kri_id} kri={kri} />
        ))}
      </div>
    </div>
  );
}

// ── KRI Heatmap ───────────────────────────────────────────────────────────────

const HEATMAP_MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz"] as const;

// Deterministic "simulated" variance per KRI/month — no Math.random() on render
function simulatedVariance(base: number, monthIdx: number): number {
  const trend = Math.sin((monthIdx / HEATMAP_MONTHS.length) * Math.PI) * 0.08;
  // Use a fixed noise based on monthIdx to avoid re-rendering issues
  const noise = (((monthIdx * 17 + 3) % 11) - 5) * 0.009;
  return Math.min(1, Math.max(0, base + trend + noise));
}

function KRIHeatmap({ kris }: { kris: KRIData[] }) {
  const [tooltip, setTooltip] = useState<string | null>(null);

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold">
        <Grid3x3 className="h-4 w-4" />
        KRI Heatmap (Varyans Yoğunluğu)
      </h3>

      {tooltip && (
        <p className="mb-2 rounded bg-muted/50 px-2 py-1 text-xs text-muted-foreground">
          {tooltip}
        </p>
      )}

      <div className="overflow-x-auto">
        <div className="inline-block min-w-full">
          {/* Month headers */}
          <div className="mb-1 flex">
            <div className="w-36 shrink-0" />
            {HEATMAP_MONTHS.map((m) => (
              <div key={m} className="w-10 text-center text-xs font-medium text-muted-foreground">
                {m}
              </div>
            ))}
          </div>

          {kris.slice(0, 8).map((kri) => (
            <div key={kri.kri_id} className="mb-1 flex items-center">
              <div
                className="w-36 shrink-0 truncate pr-2 text-xs text-muted-foreground"
                title={kri.name}
              >
                {kri.name}
              </div>
              {HEATMAP_MONTHS.map((month, monthIdx) => {
                const variance = simulatedVariance(kri.variance, monthIdx);
                const color = valueToColor(variance);
                const label = `${kri.name} · ${month}: ${fmt(variance * 100, 0)}%`;
                return (
                  <div
                    key={`${kri.kri_id}-${month}`}
                    className="mr-0.5 flex h-7 w-10 items-center justify-center rounded text-[10px] font-semibold text-white cursor-default"
                    style={{ backgroundColor: color }}
                    title={label}
                    onMouseEnter={() => setTooltip(label)}
                    onMouseLeave={() => setTooltip(null)}
                    aria-label={label}
                  >
                    {fmt(variance * 100, 0)}
                  </div>
                );
              })}
            </div>
          ))}

          {/* Legend */}
          <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
            <span>Düşük</span>
            <div className="flex gap-px">
              {[0, 0.2, 0.4, 0.6, 0.8, 1].map((v) => (
                <div
                  key={v}
                  className="h-3 w-6 rounded-sm"
                  style={{ backgroundColor: valueToColor(v) }}
                />
              ))}
            </div>
            <span>Yüksek</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Risk Matrix (probability × impact) ───────────────────────────────────────

function RiskMatrix({ risks }: { risks: RiskItem[] }) {
  const data = risks.map((r) => ({
    x: r.probability,
    y: r.impact,
    name: r.name,
    urgency: r.urgency,
    exposure: r.financial_exposure,
  }));

  const urgencyColor: Record<string, string> = {
    critical: "#ef4444",
    high:     "#f97316",
    medium:   "#eab308",
    low:      "#10b981",
  };

  // Zone reference lines
  const zones = [
    { x1: 0.33, x2: 0.33, y1: 0, y2: 10, color: "oklch(0.35 0.018 255)" },
    { x1: 0.66, x2: 0.66, y1: 0, y2: 10, color: "oklch(0.35 0.018 255)" },
  ];

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <Grid3x3 className="h-4 w-4" />
        Risk Matrisi (Olasılık × Etki)
      </h3>
      <p className="mb-4 text-xs text-muted-foreground">
        Sağ-üst köşe = en yüksek öncelik
      </p>
      <ResponsiveContainer width="100%" height={260}>
        <ScatterChart margin={{ top: 8, right: 8, left: -8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.22 0.018 255)" />
          <XAxis
            type="number"
            dataKey="x"
            name="Olasılık"
            domain={[0, 1]}
            tick={{ fontSize: 11, fill: "oklch(0.52 0.012 255)" }}
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
            axisLine={{ stroke: "oklch(0.27 0.018 255)" }}
            tickLine={false}
            label={{ value: "Olasılık →", position: "insideBottomRight", offset: -4, fontSize: 10, fill: "oklch(0.52 0.012 255)" }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name="Etki"
            domain={[0, 10]}
            tick={{ fontSize: 11, fill: "oklch(0.52 0.012 255)" }}
            axisLine={{ stroke: "oklch(0.27 0.018 255)" }}
            tickLine={false}
            label={{ value: "Etki ↑", angle: -90, position: "insideLeft", offset: 8, fontSize: 10, fill: "oklch(0.52 0.012 255)" }}
          />
          <Tooltip
            contentStyle={{
              background: "oklch(0.17 0.022 255)",
              border: "1px solid oklch(0.27 0.018 255)",
              borderRadius: "6px",
              fontSize: "12px",
              color: "oklch(0.92 0.008 255)",
              padding: "8px 12px",
            }}
            formatter={(_: unknown, __: string, props: { payload?: { name?: string; urgency?: string; exposure?: number } }) => {
              const p = props.payload;
              if (!p) return [];
              return [
                `${p.name} · ${p.urgency}`,
                formatCurrency(p.exposure ?? 0),
              ];
            }}
          />
          {/* Zone dividers */}
          <ReferenceLine x={0.33} stroke="oklch(0.30 0.018 255)" strokeDasharray="4 2" />
          <ReferenceLine x={0.66} stroke="oklch(0.30 0.018 255)" strokeDasharray="4 2" />
          <ReferenceLine y={3.3} stroke="oklch(0.30 0.018 255)" strokeDasharray="4 2" />
          <ReferenceLine y={6.6} stroke="oklch(0.30 0.018 255)" strokeDasharray="4 2" />

          <Scatter data={data} shape={(props: { cx?: number; cy?: number; payload?: { urgency?: string } }) => {
            const { cx = 0, cy = 0, payload } = props;
            const color = urgencyColor[(payload?.urgency ?? "low")] ?? "#6b7280";
            return (
              <circle
                cx={cx}
                cy={cy}
                r={7}
                fill={color}
                fillOpacity={0.8}
                stroke={color}
                strokeWidth={1.5}
              />
            );
          }} />
        </ScatterChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div className="mt-2 flex flex-wrap gap-3 text-xs">
        {Object.entries(urgencyColor).map(([k, v]) => (
          <span key={k} className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: v }} />
            <span className="capitalize text-muted-foreground">{k}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Risk Cascade Simulation (Interactive) ─────────────────────────────────────

interface RiskCascadeProps {
  risks: RiskItem[];
}

function RiskCascadeSimulation({ risks }: RiskCascadeProps) {
  const [selectedRisk, setSelectedRisk] = useState<RiskItem | null>(
    risks.length > 0 ? risks[0] : null
  );
  const [contagionLevel, setContagionLevel] = useState(0.5);

  const cascadeImpact = useMemo(() => {
    if (!selectedRisk) return { direct: 0, secondary: 0, total: 0 };

    const direct = selectedRisk.financial_exposure;
    const affectedRisks = risks.filter(
      (r) =>
        r.risk_id !== selectedRisk.risk_id &&
        Math.abs(
          (r.financial_exposure - selectedRisk.financial_exposure) /
            selectedRisk.financial_exposure
        ) < 0.5
    );
    const secondary = affectedRisks.reduce(
      (sum, r) => sum + r.financial_exposure * contagionLevel,
      0
    );
    return { direct, secondary, total: direct + secondary };
  }, [selectedRisk, risks, contagionLevel]);

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
        <Zap className="h-4 w-4" />
        Risk Bulaşması Simülasyonu
      </h3>

      <div className="mb-4">
        <label className="block text-xs font-medium mb-2">Risk Seçin</label>
        <select
          value={selectedRisk?.risk_id || ""}
          onChange={(e) => {
            const risk = risks.find((r) => r.risk_id === e.target.value);
            if (risk) setSelectedRisk(risk);
          }}
          className="w-full rounded border border-input bg-background px-3 py-2 text-sm"
        >
          {risks.map((r) => (
            <option key={r.risk_id} value={r.risk_id}>
              {r.name} ({formatCurrency(r.financial_exposure, "₺")})
            </option>
          ))}
        </select>
      </div>

      <div className="mb-4">
        <label className="block text-xs font-medium mb-2">
          Bulaşma Şiddeti: {(contagionLevel * 100).toFixed(0)}%
        </label>
        <input
          type="range"
          min="0"
          max="1"
          step="0.1"
          value={contagionLevel}
          onChange={(e) => setContagionLevel(parseFloat(e.target.value))}
          className="w-full"
        />
      </div>

      {selectedRisk && (
        <div className="space-y-3">
          <div className="rounded bg-muted/30 p-3">
            <p className="text-xs text-muted-foreground mb-1">Birincil Etki</p>
            <p className="text-lg font-bold text-red-400">
              {formatCurrency(cascadeImpact.direct, "₺")}
            </p>
          </div>

          <div className="rounded bg-muted/30 p-3">
            <p className="text-xs text-muted-foreground mb-1">İkincil Etki (Bulaşma)</p>
            <p className="text-lg font-bold text-orange-400">
              {formatCurrency(cascadeImpact.secondary, "₺")}
            </p>
          </div>

          <div className="rounded bg-muted/40 p-3 border border-border">
            <p className="text-xs text-muted-foreground mb-1">Toplam Maruz Kalma</p>
            <p className="text-xl font-bold text-yellow-400">
              {formatCurrency(cascadeImpact.total, "₺")}
            </p>
          </div>

          <p className="text-xs text-muted-foreground mt-3">
            {risks.filter((r) => r.risk_id !== selectedRisk.risk_id).length} ilişkili risk
            tespit edildi. Bulaşma oranı arttıkça etki büyüyor.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Top Risks Panel ───────────────────────────────────────────────────────────

interface TopRisksProps {
  risks: RiskItem[];
}

function TopRisksPanel({ risks }: TopRisksProps) {
  const sortedRisks = useMemo(
    () =>
      [...risks]
        .sort((a, b) => {
          const scoreA = a.probability * a.impact;
          const scoreB = b.probability * b.impact;
          return scoreB - scoreA;
        })
        .slice(0, 5),
    [risks]
  );

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
        <Shield className="h-4 w-4" />
        En Yüksek Riskler
      </h3>
      <div className="space-y-2">
        {sortedRisks.map((risk) => {
          const riskScore = (risk.probability * risk.impact) / 10;
          return (
            <div
              key={risk.risk_id}
              className="rounded border border-border bg-muted/20 p-3"
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <div>
                  <p className="font-medium text-sm">{risk.name}</p>
                  <div className="flex gap-2 mt-1">
                    <span className="text-xs px-2 py-0.5 rounded bg-muted">
                      P: {formatPercent(risk.probability)}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded bg-muted">
                      I: {fmt(risk.impact, 0)}/10
                    </span>
                  </div>
                </div>
                <span
                  className="text-xs px-2 py-0.5 rounded font-medium text-white shrink-0"
                  style={{ backgroundColor: getUrgencyColor(risk.urgency) }}
                >
                  {risk.urgency.toUpperCase()}
                </span>
              </div>

              <div className="mb-2">
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-muted-foreground">Risk Puanı</span>
                  <span className="font-semibold">{fmt(riskScore * 10, 0)}/100</span>
                </div>
                <div className="w-full bg-muted rounded h-1.5 overflow-hidden">
                  <div
                    className="h-full rounded"
                    style={{
                      width: `${riskScore * 10}%`,
                      backgroundColor: getUrgencyColor(risk.urgency),
                    }}
                  />
                </div>
              </div>

              <p className="text-xs text-muted-foreground">
                Finansal Maruz Kalma: {formatCurrency(risk.financial_exposure, "₺")}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function RiskDashboardPage() {
  const [kriCsv, setKriCsv] = useState("");
  const [riskCsv, setRiskCsv] = useState("");
  const [company, setCompany] = useState("");
  const [period, setPeriod] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RiskResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!kriCsv && !riskCsv) {
      setError("En az bir veri kaynağı (KRI veya Risk CSV) gereklidir.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<RiskResult>("/risk/analyze", {
        company_name: company || null,
        reporting_period: period || null,
        kri_csv: kriCsv || "",
        register_csv: riskCsv || "",
      });
      if (res.data.error) throw new Error(res.data.error);
      setResult(res.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Bilinmeyen hata");
    } finally {
      setLoading(false);
    }
  }

  // Parse CSV data
  const parsedKRIs = useMemo(() => {
    if (!kriCsv) return [];
    const lines = kriCsv.split("\n");
    return lines.slice(1).map((line) => {
      const values = line.split(",");
      return {
        kri_id: values[0]?.trim() || "",
        name: values[1]?.trim() || "",
        current_value: parseFloat(values[2]) || 0,
        threshold: parseFloat(values[3]) || 0,
        variance: parseFloat(values[4]) || 0.1,
        trend: (values[5]?.trim().toLowerCase() || "stable") as any,
        last_updated: new Date().toISOString().split("T")[0],
      };
    });
  }, [kriCsv]);

  const parsedRisks = useMemo(() => {
    if (!riskCsv) return [];
    const lines = riskCsv.split("\n");
    return lines.slice(1).map((line) => {
      const values = line.split(",");
      return {
        risk_id: values[0]?.trim() || "",
        name: values[1]?.trim() || "",
        probability: parseFloat(values[2]) || 0,
        impact: parseFloat(values[3]) || 0,
        financial_exposure: parseFloat(values[4]) || 0,
        urgency: (values[5]?.trim().toLowerCase() || "medium") as any,
        mitigations: ["Kontroller güçlendir", "İzleme artır"],
      };
    });
  }, [riskCsv]);

  return (
    <main className="mx-auto max-w-screen-2xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <AlertTriangle className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">Risk Yönetimi Panosu</h1>
          <p className="text-sm text-muted-foreground">
            KRI monitörü, korelasyon analizi ve risk bulaşması simülasyonu
          </p>
        </div>
      </div>

      {/* Input form */}
      <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-card p-4 sm:p-6">
        <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="risk-company" className="mb-1 block text-xs font-medium">
              Şirket Adı
            </label>
            <input
              id="risk-company"
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="Acme Corp"
              className="w-full rounded border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <div>
            <label htmlFor="risk-period" className="mb-1 block text-xs font-medium">
              Dönem
            </label>
            <input
              id="risk-period"
              type="text"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="2024-Q2"
              className="w-full rounded border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        </div>

        <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div>
            <label htmlFor="risk-kri" className="mb-1 block text-xs font-medium">
              KRI CSV
            </label>
            <textarea
              id="risk-kri"
              value={kriCsv}
              onChange={(e) => setKriCsv(e.target.value)}
              placeholder="CSV verisi yapıştırın..."
              rows={6}
              className="w-full rounded border border-input bg-background px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <div>
            <label htmlFor="risk-register" className="mb-1 block text-xs font-medium">
              Risk Defteri CSV
            </label>
            <textarea
              id="risk-register"
              value={riskCsv}
              onChange={(e) => setRiskCsv(e.target.value)}
              placeholder="CSV verisi yapıştırın..."
              rows={6}
              className="w-full rounded border border-input bg-background px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
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
            {loading ? "Analiz yapılıyor…" : "Risk Analizi Çalıştır"}
          </button>
          <button
            type="button"
            onClick={() => {
              setKriCsv(SAMPLE_DATA.kri);
              setRiskCsv(SAMPLE_DATA.risks);
            }}
            className="rounded border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
          >
            Örnek Veri Yükle
          </button>
        </div>
      </form>

      {/* Results */}
      {(parsedKRIs.length > 0 || parsedRisks.length > 0) && (
        <div className="space-y-6">
          {/* KRI Gauge grid */}
          {parsedKRIs.length > 0 && <KRIGaugeGrid kris={parsedKRIs} />}

          {/* Row 1: Heatmap + Risk Matrix */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {parsedKRIs.length > 0 && <KRIHeatmap kris={parsedKRIs} />}
            {parsedRisks.length > 0 && <RiskMatrix risks={parsedRisks} />}
          </div>

          {/* Row 2: Cascade + Top Risks */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {parsedRisks.length > 0 && <RiskCascadeSimulation risks={parsedRisks} />}
            {parsedRisks.length > 0 && <TopRisksPanel risks={parsedRisks} />}
          </div>

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
